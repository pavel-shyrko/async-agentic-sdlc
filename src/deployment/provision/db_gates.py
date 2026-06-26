"""E7 DB provisioning gates — no live database required for the validation gate.

Two gates mirror the pattern in ``provision/gates.py``:

* ``run_schema_gate`` — offline FK resolution + topological sort (cycle detection).
  Called BEFORE touching Postgres so a mis-specified contract fails fast at zero cost.

* ``run_smoke_gate`` — post-provision ``information_schema`` check that every contracted
  table and materialized view was actually created.
"""
import re
from collections import defaultdict, deque

import psycopg

from src.shared.core.observability import log
from src.shared.core.models import SchemaContract, SchemaGateResult, GateViolation

_REF_RE = re.compile(r"\bREFERENCES\s+(?:\w+\.)?(\w+)\b", re.IGNORECASE)
_CREATE_TABLE_RE = re.compile(r"\bCREATE\s+TABLE\b", re.IGNORECASE)
_VIEW_NAME_RE = re.compile(r"CREATE\s+MATERIALIZED\s+VIEW\s+(?:\w+\.)?(\w+)", re.IGNORECASE)

_FETCH_TABLES_SQL = """
    SELECT table_name FROM information_schema.tables
    WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
"""
_FETCH_VIEWS_SQL = "SELECT matviewname FROM pg_matviews WHERE schemaname = 'public'"


def _topological_sort(names: set[str], deps: dict[str, list[str]]) -> list[str] | None:
    """Kahn's algorithm — returns ``None`` if a cycle is detected."""
    in_degree: dict[str, int] = {n: 0 for n in names}
    adj: dict[str, list[str]] = defaultdict(list)
    for child, parents in deps.items():
        for parent in parents:
            if parent in names:
                adj[parent].append(child)
                in_degree[child] += 1
    queue = deque(n for n, d in in_degree.items() if d == 0)
    order: list[str] = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for child in adj[node]:
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)
    return order if len(order) == len(names) else None


def run_schema_gate(contract: SchemaContract) -> SchemaGateResult:
    """Validate the SchemaContract offline — no live DB required.

    Checks (1) every table DDL is a valid CREATE TABLE, (2) every REFERENCES target exists
    in the contract, (3) no circular FK dependencies.  Returns a ``SchemaGateResult``; the
    scaffold re-invokes the architect with violations on failure.
    """
    violations: list[GateViolation] = []
    table_names = {t.table_name for t in contract.tables}
    deps: dict[str, list[str]] = {}

    for table in contract.tables:
        ddl = table.ddl
        if not _CREATE_TABLE_RE.search(ddl):
            violations.append(GateViolation(
                table_name=table.table_name,
                violation="DDL does not contain a CREATE TABLE statement.",
            ))
        unknown = [r for r in _REF_RE.findall(ddl) if r.lower() not in {n.lower() for n in table_names}]
        for ref in unknown:
            violations.append(GateViolation(
                table_name=table.table_name,
                violation=f"REFERENCES unknown table '{ref}'.",
            ))
        deps[table.table_name] = [d for d in (table.dependencies or []) if d in table_names]

    if _topological_sort(table_names, deps) is None:
        violations.append(GateViolation(
            table_name="(schema)",
            violation="Circular foreign-key dependency detected — reorder tables to break the cycle.",
        ))

    result = SchemaGateResult(passed=not violations, violations=violations)
    if result.passed:
        log.info("🟢 [DB-GATE] Schema validation PASSED.")
    else:
        log.warning(f"🔴 [DB-GATE] Schema validation FAILED ({len(violations)} violation(s)).")
    return result


async def run_smoke_gate(contract: SchemaContract, db_url: str) -> list[str]:
    """Query information_schema after provisioning to confirm all tables and views exist.

    Returns a list of problem strings (empty = PASS).  Mirrors ``run_devops_gate``'s return
    convention so the scaffold can feed the problems into a retry loop if needed.
    """
    problems: list[str] = []
    async with await psycopg.AsyncConnection.connect(db_url) as conn:
        rows = await (await conn.execute(_FETCH_TABLES_SQL)).fetchall()
        existing_tables = {r[0] for r in rows}
        view_rows = await (await conn.execute(_FETCH_VIEWS_SQL)).fetchall()
        existing_views = {r[0] for r in view_rows}

    missing_tables = {t.table_name for t in contract.tables} - existing_tables
    expected_views = {m.group(1) for ddl in contract.views if (m := _VIEW_NAME_RE.search(ddl))}
    missing_views = expected_views - existing_views

    if missing_tables:
        problems.append(f"Missing tables: {sorted(missing_tables)}")
    if missing_views:
        problems.append(f"Missing views: {sorted(missing_views)}")

    if not problems:
        log.info("🟢 [DB-GATE] Smoke test PASSED — all tables and views present.")
    else:
        log.warning(f"🔴 [DB-GATE] Smoke test FAILED: {'; '.join(problems)}")
    return problems
