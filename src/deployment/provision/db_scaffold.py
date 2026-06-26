"""Deployment plane — E7 post-batch database provisioning (``--provision-db``).

After the E4 deploy-scaffolding has landed the application's CI/CD config, this phase connects to
the target PostgreSQL instance, has the DatabaseArchitectAgent generate the schema from the nexus
blueprint, validates the schema offline, provisions it, smoke-tests it, and optionally seeds
reference data (dev/staging only).

``run_batch`` invokes ``run_db_provisioning`` through a LAZY import at call time — the same
pattern as ``run_devops_scaffold`` — to break the deployment→nexus import cycle.

The DATABASE_URL env var must be set before this phase runs (Cloud SQL proxy URL in GCP, or the
docker-compose service URL in local dev).  Without it the phase halts with a clear error instead
of attempting a connection.
"""
import os
import re
from decimal import Decimal
from pathlib import Path

import psycopg

from src.shared.core.observability import log, log_finops_summary
from src.shared.core.config import DB_PROVISION_MAX_RETRIES, PIPELINE_APP_BUDGET_USD
from src.shared.core.models import PipelineTelemetry, ProvisioningResult
from src.shared.core.runs import Projects
from src.deployment.agents.db_architect import run_db_architect_node
from src.deployment.agents.seed_agent import run_seed_agent_node
from src.deployment.provision.db_gates import run_schema_gate, run_smoke_gate

# Extensions required by the Ghostwire schema.
_EXTENSIONS = [
    "CREATE EXTENSION IF NOT EXISTS pgcrypto",
    "CREATE EXTENSION IF NOT EXISTS vector",
]


async def _provision_schema(contract, db_url: str) -> ProvisioningResult:
    """Execute the SchemaContract DDL against a live Postgres instance."""
    result = ProvisioningResult(success=False)
    async with await psycopg.AsyncConnection.connect(db_url, autocommit=True) as ext_conn:
        for ext_ddl in _EXTENSIONS:
            try:
                await ext_conn.execute(ext_ddl)
            except psycopg.Error as exc:
                log.warning("Extension skipped (%s): %s", ext_ddl.split()[-1], exc)

    async with await psycopg.AsyncConnection.connect(db_url, autocommit=False) as conn:
        async with conn.transaction():
            for table in contract.tables:
                # Nested transaction = SAVEPOINT: a DuplicateTable rolls back only this DDL,
                # not the whole provisioning transaction — makes E7 safe to re-run on --resume.
                async with conn.transaction():
                    try:
                        await conn.execute(table.ddl)
                        result.tables_created.append(table.table_name)
                        log.info("  ✓ table: %s", table.table_name)
                    except psycopg.errors.DuplicateTable:
                        log.info("  ~ table already exists (resume): %s", table.table_name)
                        result.tables_created.append(table.table_name)
                    except psycopg.Error as exc:
                        result.tables_failed.append(table.table_name)
                        result.errors.append(f"{table.table_name}: {exc}")
                        log.error("  ✗ table FAILED: %s — %s", table.table_name, exc)
            for idx in contract.indexes:
                async with conn.transaction():
                    try:
                        await conn.execute(idx.ddl)
                    except (psycopg.errors.DuplicateTable, psycopg.errors.DuplicateObject):
                        log.info("  ~ index already exists (resume): %s", idx.index_name)
                    except psycopg.Error as exc:
                        result.errors.append(f"index:{idx.index_name}: {exc}")
                        log.error("  ✗ index FAILED: %s — %s", idx.index_name, exc)
            for view_ddl in contract.views:
                async with conn.transaction():
                    try:
                        await conn.execute(view_ddl)
                        log.info("  ✓ materialized view created.")
                    except psycopg.errors.DuplicateTable:
                        log.info("  ~ materialized view already exists (resume).")
                    except psycopg.Error as exc:
                        result.errors.append(f"view: {exc}")
                        log.error("  ✗ view FAILED — %s", exc)

    result.success = not result.tables_failed
    return result


async def _execute_seed(inserts: list[str], db_url: str) -> None:
    """Execute seed INSERT statements inside a single transaction (all-or-nothing)."""
    async with await psycopg.AsyncConnection.connect(db_url, autocommit=False) as conn:
        async with conn.transaction():
            for stmt in inserts:
                await conn.execute(stmt)
    log.info("  ✓ %d seed rows inserted.", len(inserts))


_SAFE_TABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")


async def _verify_seed(expected: dict[str, int], db_url: str) -> list[str]:
    """Verify each seeded table has at least the expected row count."""
    problems: list[str] = []
    async with await psycopg.AsyncConnection.connect(db_url) as conn:
        for table, min_rows in expected.items():
            if not _SAFE_TABLE_RE.match(table):
                problems.append(f"{table}: rejected — unsafe identifier")
                continue
            row = await (await conn.execute(f"SELECT count(*) FROM {table}")).fetchone()  # nosec B608
            actual = row[0] if row else 0
            if actual < min_rows:
                problems.append(f"{table}: expected >={min_rows}, got {actual}")
    return problems


async def run_db_provisioning(
    projects: Projects,
    project,
    nexus_run_dir: Path,
    budget_usd_ceiling: Decimal | None = None,
    app_telemetry: PipelineTelemetry | None = None,
    env: str = "staging",
) -> None:
    """E7: provision the Ghostwire PostgreSQL schema from the nexus blueprint.

    Reads the blueprint from ``nexus_run_dir/artifacts/blueprint.md``, calls the
    DatabaseArchitectAgent to generate a ``SchemaContract``, validates it offline, provisions it
    against ``DATABASE_URL``, smoke-tests it, and optionally seeds reference data.

    Budget tracking: this phase's ``PipelineTelemetry`` is merged into ``app_telemetry`` in a
    ``finally`` — identical to ``run_devops_scaffold`` — so even a halt mid-generation records
    the partial spend in the application-wide total.
    """
    from src.nexus.runner import PipelineHalt  # lazy import — breaks the deployment→nexus cycle

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        log.error("🚨 [E7] DATABASE_URL is not set — skipping DB provisioning.")
        return

    budget_usd = budget_usd_ceiling if budget_usd_ceiling is not None else PIPELINE_APP_BUDGET_USD
    telemetry = PipelineTelemetry()

    log.info(f"🗄️  [E7] DB provisioning for project '{project.slug}' | env={env} "
             f"| ${budget_usd:.4f} of the app budget remaining.")

    try:
        # ── Step 1: Read blueprint ──────────────────────────────────────────────────
        blueprint_path = nexus_run_dir / "artifacts" / "blueprint.md"
        blueprint_text = (blueprint_path.read_text(encoding="utf-8")
                          if blueprint_path.exists() else "(no blueprint available)")

        # ── Step 2: Architect + validation gate (retry loop) ───────────────────────
        gate_violations = None
        contract = None
        for attempt in range(1, DB_PROVISION_MAX_RETRIES + 2):
            contract = await run_db_architect_node(
                telemetry, blueprint_text=blueprint_text, gate_violations=gate_violations,
            )
            if telemetry.total_cost_usd > budget_usd:
                raise PipelineHalt(
                    f"🛑 [E7] DB provisioning budget exceeded "
                    f"(${telemetry.total_cost_usd:.4f} > ${budget_usd:.4f})."
                )

            gate_result = run_schema_gate(contract)
            if gate_result.passed:
                break
            if attempt > DB_PROVISION_MAX_RETRIES:
                violation_summary = "\n".join(
                    f"  - [{v.table_name}] {v.violation}" for v in gate_result.violations
                )
                raise PipelineHalt(
                    f"🛑 [E7] Schema gate failed after {attempt} attempts:\n{violation_summary}\n"
                    "(The application code is already merged; only the DB schema did not land.)"
                )
            log.warning(f"🔁 [E7] Schema gate failed (attempt {attempt}/{DB_PROVISION_MAX_RETRIES + 1}) "
                        f"— re-invoking architect with {len(gate_result.violations)} violation(s).")
            gate_violations = gate_result.violations

        # ── Step 3: Provision ───────────────────────────────────────────────────────
        log.info("[E7] Provisioning schema against DATABASE_URL …")
        result = await _provision_schema(contract, db_url)
        if not result.success:
            error_summary = "\n".join(f"  - {e}" for e in result.errors)
            raise PipelineHalt(
                f"🛑 [E7] Schema provisioning failed:\n{error_summary}\n"
                "(The application code is already merged; only the DB schema did not land.)"
            )

        # ── Step 4: Smoke test ──────────────────────────────────────────────────────
        smoke_problems = await run_smoke_gate(contract, db_url)
        if smoke_problems:
            raise PipelineHalt(
                f"🛑 [E7] DB smoke gate failed: {'; '.join(smoke_problems)}"
            )

        # ── Step 5 & 6: Seed (dev/staging only) ────────────────────────────────────
        if env == "prod":
            log.info("[E7] Production environment — seed data skipped.")
        else:
            seed_output = await run_seed_agent_node(telemetry, contract=contract, env=env)
            if telemetry.total_cost_usd > budget_usd:
                raise PipelineHalt(
                    f"🛑 [E7] DB provisioning budget exceeded during seed generation "
                    f"(${telemetry.total_cost_usd:.4f} > ${budget_usd:.4f})."
                )
            await _execute_seed(seed_output.inserts, db_url)
            seed_problems = await _verify_seed(seed_output.row_counts, db_url)
            if seed_problems:
                log.warning("[E7] Seed verification warnings:\n%s", "\n".join(seed_problems))

        log.info(f"🏁 [E7] DB provisioning complete for project '{project.slug}'.")

    finally:
        if app_telemetry is not None:
            app_telemetry.merge(telemetry)
        log_finops_summary(telemetry, budget_usd)
