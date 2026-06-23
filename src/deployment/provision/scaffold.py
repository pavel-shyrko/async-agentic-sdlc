"""Deployment plane — E4 post-batch deploy-scaffolding (``--scaffold-deploy``).

After the E3 batch (``run_batch``, nexus plane) has merged every ticket, generate and land the finished
application's CI/CD config (archetype-aware Dockerfile + GitHub Actions deploy workflow, Cloud Run via
WIF). ``run_batch`` invokes ``run_devops_scaffold`` through a LAZY import — that import is what breaks the
deployment→nexus cycle (this module imports the transaction/forge/incident/FinOps SSOTs from
``src.nexus.runner`` at load time). The canonical CI commands fed to the DevOps agent come straight from
the environments SSOT (``_env_ci_commands``), keeping engine-green ⇒ CI-green. See ADR 0020/0021 and the
deploy-scaffolding-and-ci-parity rule."""
import os
import json
from decimal import Decimal
from pathlib import Path

from src.shared.core.observability import log, reconfigure_logging
from src.shared.core.config import PIPELINE_APP_BUDGET_USD, EFFECTIVE_BUDGET_USD
from src.shared.core.models import GlobalPipelineContext, PipelineTelemetry
from src.shared.core.runs import Projects
from src.shared.core.environments import SUPPORTED_ENVIRONMENTS
from src.shared.core.prompts import generate_repo_map
from src.shared.utils.git_helpers import get_git_root
from src.deployment.agents.devops import run_devops_node
from src.deployment.provision.gates import run_devops_gate
from src.nexus.runner import (
    RunConfig, bootstrap_session, finalize_transaction, finalize_pr,
    _abort_with_incident, _has_staged_changes, write_finops_report, log_finops_summary,
    enforce_financial_circuit_breaker,
)

DEVOPS_MAX_RETRIES = int(os.environ.get("DEVOPS_MAX_RETRIES", "1"))  # E4: self-heal retries on a deploy-manifest static-lint failure before Hard Halt


def _repo_has_source(repo_dir: Path) -> bool:
    """True if the clone holds ≥1 non-doc/non-metadata file — i.e. there is an application to deploy.

    The empty-state guard for E4: a degenerate batch (all tickets skipped) or a misused flag would leave
    nothing but README/LICENSE/git metadata, and scaffolding a deploy for nothing is wrong."""
    doc_or_meta = {
        "readme.md", "readme", "readme.rst", "readme.txt", "license", "license.md", "license.txt",
        ".gitignore", ".gitattributes", ".gitmodules",
    }
    for root, dirs, files in os.walk(repo_dir):
        if ".git" in dirs:
            dirs.remove(".git")  # never descend into git internals
        for name in files:
            if name.lower() not in doc_or_meta:
                return True
    return False


def _nexus_environment_ids(nexus_run_dir: Path) -> str:
    """Best-effort comma list of the unique environment_id(s) the plan's tickets ran on (from the Nexus
    checkpoint). Feeds the DevOps agent the runtime(s) of the finished app; '' if unreadable."""
    try:
        data = json.loads((nexus_run_dir / "reports" / "checkpoint.json").read_text(encoding="utf-8"))
        ids: list[str] = []
        for task in data.get("tasks", []):
            env = (task or {}).get("environment_id")
            if env and env not in ids:
                ids.append(env)
        return ", ".join(ids)
    except Exception:
        return ""


def _env_ci_commands(environment_ids: str) -> str:
    """The CANONICAL build/test/lint commands for the finished app's environment(s), formatted for the
    DevOps prompt. This is the SSOT coupling: the generated CI MUST run exactly these (the same commands
    the engine's own gates ran), so engine-green ⇒ CI-green. Unknown/blank ids yield ''."""
    blocks: list[str] = []
    for env_id in [e.strip() for e in environment_ids.split(",") if e.strip()]:
        spec = SUPPORTED_ENVIRONMENTS.get(env_id)
        if not spec:
            continue
        lines = [f"- environment_id: {env_id}"]
        for key in ("setup_cmd", "build_cmd", "test_cmd", "lint_cmd"):
            if spec.get(key):
                lines.append(f"    {key}: {spec[key]}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


async def run_devops_scaffold(projects: Projects, project, cfg: RunConfig, nexus_run_dir: Path,
                              budget_usd_ceiling: Decimal | None = None,
                              app_telemetry: PipelineTelemetry | None = None) -> None:
    """E4: after the batch has merged every ticket, scaffold deploy config for the finished application.

    Clones the completed base branch FRESH, has the DevOps agent generate a Dockerfile + GitHub Actions
    deploy workflow (Cloud Run via WIF for a web service; a build/release matrix for a CLI tool/library),
    static-lints them (exactly ``DEVOPS_MAX_RETRIES`` self-heal retries), and lands them through the SAME
    E2 forge flow tickets use — open → approve → squash-merge of ``chore/devops-scaffold`` — never a raw
    push to ``main``. The merged application code is untouched on any failure; a persistently invalid
    manifest writes an incident and exits 1 (the deploy config simply didn't land).

    E5 — ``budget_usd_ceiling`` is the remaining application budget (from ``run_batch``); the financial
    breaker is enforced after every DevOps generation so an exhaustion mid-self-heal halts correctly. When
    ``app_telemetry`` is provided, this phase's spend is merged into it in a ``finally`` — so even a
    ``PipelineHalt`` raised inside the self-heal loop still folds the partial DevOps spend into the
    application-wide total before propagating, and the batch's app report stays accurate."""
    devops_branch = "chore/devops-scaffold"
    budget_usd = budget_usd_ceiling if budget_usd_ceiling is not None else PIPELINE_APP_BUDGET_USD
    # Publish the deploy phase's effective ceiling so its FinOps GRAND TOTAL / halt report render against
    # the same remaining budget the breaker gates on (parity with run_executor). Never persisted.
    EFFECTIVE_BUDGET_USD.set(budget_usd)
    cfg.repo = cfg.repo or project.repo
    cfg.base_branch = project.base_branch
    run_dir = projects.allocate(project.slug, "devops", "scaffold")
    reconfigure_logging(run_dir / "logs")
    log.info(f"🚀 [E4] Deploy-scaffolding for project '{project.slug}' → {run_dir.name} "
             f"| ${budget_usd:.4f} of the app budget remaining.")

    cfg.ticket = "devops"
    ws = await bootstrap_session(cfg, run_dir, branch=devops_branch)

    # Empty-state guard — nothing to deploy if the cloned base branch carries no source. (No ctx yet, so
    # no spend to fold into app_telemetry.)
    if not _repo_has_source(ws.repo_dir):
        log.warning("⏭️  --scaffold-deploy: cloned main has no source — skipping deploy scaffolding.")
        return

    ctx = GlobalPipelineContext(
        pr_description="scaffold deployment (Dockerfile + GitHub Actions deploy workflow)",
        ticket="devops", base_branch=cfg.base_branch, workspace_paths=ws,
    )
    try:
        blueprint = nexus_run_dir / "artifacts" / "blueprint.md"
        blueprint_text = blueprint.read_text(encoding="utf-8") if blueprint.exists() else "(no blueprint available)"
        repo_map = generate_repo_map(ws.repo_dir)
        environment_ids = _nexus_environment_ids(nexus_run_dir)
        ci_commands = _env_ci_commands(environment_ids)  # SSOT: CI must run these exact commands

        # Self-heal loop: exactly DEVOPS_MAX_RETRIES retries (default 1). Generate → static-lint; on a gate
        # failure feed the errors back and regenerate; only a persistently invalid manifest Hard-Halts.
        gate_feedback = ""
        problems: list[str] = []
        for attempt in range(1, DEVOPS_MAX_RETRIES + 2):
            await run_devops_node(
                ctx, blueprint_text=blueprint_text, repo_map=repo_map,
                environment_ids=environment_ids, ci_commands=ci_commands, gate_feedback=gate_feedback,
            )
            enforce_financial_circuit_breaker(ctx, budget_usd)  # E5: halt if this phase breaches the remaining budget
            problems = run_devops_gate(ws.repo_dir)
            if not problems:
                break
            gate_feedback = "\n".join(f"- {p}" for p in problems)
            log.warning(f"🔁 [E4] Deploy-manifest static lint failed (attempt {attempt}): {gate_feedback}")
        if problems:
            _abort_with_incident(
                ctx,
                "\n🚨 [E4] Deploy scaffolding failed static validation after retry (the application code is "
                f"already merged to {cfg.base_branch}; only the deploy config did not land):\n{gate_feedback}",
            )

        # Land the manifests through the SAME E2 forge flow (no raw push). Skip cleanly when nothing is staged —
        # an idempotent re-run after a prior scaffold already merged identical manifests.
        repo_root = await get_git_root(str(ws.repo_dir))
        if not await _has_staged_changes(repo_root):
            log.info("🟢 [E4] No manifest changes vs the base branch — deploy config already present; nothing to merge.")
            return
        await finalize_transaction(ctx, push=True)
        try:
            await finalize_pr(ctx, cfg, head_branch=devops_branch)
        finally:
            write_finops_report(ctx)
            log_finops_summary(ctx)
        log.info(f"🏁 [E4] Deploy scaffolding merged into {cfg.base_branch}.")
    finally:
        # Fold this phase's spend into the application-wide total on EVERY exit — clean finish, early
        # skip-return, or a PipelineHalt from the breaker/gate above — so the batch's app report is accurate.
        if app_telemetry is not None:
            app_telemetry.merge(ctx.telemetry)
