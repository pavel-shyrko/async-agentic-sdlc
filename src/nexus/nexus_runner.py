# Nexus Control Plane orchestrator. Drives the PO -> SA -> TPM trio for a raw idea inside a per-run,
# isolated session (runs/run_<uuid>/) that mirrors the executor's contract: logs/, reports/ (checkpoint
# + finops + incident), and artifacts/ (the generated Epic, Blueprint, and per-task tickets). Each
# phase checkpoints so a terminal failure can be resumed from reports/checkpoint.json.
import os
import re
import sys
import json
from pathlib import Path

from src.shared.core.boilerplate import build_gitignore_baseline_block
from src.shared.core.config import effective_budget_usd
from src.shared.core.models import PipelineTelemetry
from src.shared.core.observability import log, log_finops_summary, describe_finish_reason
from src.shared.utils.redaction import redact
from src.nexus.state import NexusState
from src.nexus.agents.po import run_po
from src.nexus.agents.sa import run_sa
from src.nexus.agents.tpm import run_tpm

# Filesystem-safe ticket id (used verbatim in the TASK-XX.md filename).
_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_ticket_id(ticket_id: str, index: int) -> str:
    """Sanitise a model-provided ticket id into a safe filename stem; fall back to TASK-NN."""
    slug = _SLUG_RE.sub("-", (ticket_id or "").strip()).strip("-")
    return slug or f"TASK-{index:02d}"


def _natural_sort_key(stem: str):
    """Sort key that orders by a trailing integer when present (so TASK-2 precedes TASK-10), and
    pushes stems with no trailing number to the end (sorted by name). The leading 0/1 group flag means
    int-keyed and name-keyed stems are never compared against each other."""
    m = re.search(r"(\d+)$", stem)
    return (0, int(m.group(1))) if m else (1, stem)


def get_tasks_for_nexus_run(run_dir: Path) -> list[str]:
    """Return the planned ticket ids for a Nexus run, in true TPM order.

    Primary (authoritative): read the run's ``reports/checkpoint.json`` and map ``NexusState.tasks``
    PRESERVING list order — the list already encodes TPM order, so no sorting is applied (and arbitrary
    model-authored ids are handled correctly). Fallback when no/unreadable checkpoint: enumerate
    ``artifacts/*.md`` (minus epic/blueprint) with a NATURAL numeric sort so ``TASK-2`` precedes
    ``TASK-10`` rather than the other way round. Returns ``[]`` when there is nothing to run.
    """
    run_dir = Path(run_dir)
    checkpoint = run_dir / "reports" / "checkpoint.json"
    if checkpoint.exists():
        try:
            state = NexusState.load_checkpoint(checkpoint)
            return [_safe_ticket_id(t.get("ticket_id", ""), i) for i, t in enumerate(state.tasks, start=1)]
        except Exception as e:  # unreadable/garbage checkpoint → fall back to the on-disk artifacts
            log.debug(f"get_tasks_for_nexus_run: checkpoint unreadable ({e}); scanning artifacts/.")
    artifacts_dir = run_dir / "artifacts"
    if not artifacts_dir.is_dir():
        return []
    stems = [p.stem for p in artifacts_dir.glob("*.md") if p.stem not in ("epic", "blueprint")]
    return sorted(stems, key=_natural_sort_key)


async def run_nexus(
    raw_idea: str | None = None, *, run_dir: Path | None = None, resume: Path | None = None,
) -> Path:
    """Run (or resume) the full Nexus pipeline for one raw idea inside a git-anchored run dir.

    Flow: raw_idea -> PO (Epic) -> SA (Blueprint) -> TPM (tasks). Each phase persists its artifact to
    ``artifacts/`` and checkpoints to ``reports/checkpoint.json``; a ``--resume`` reloads that
    checkpoint and skips the already-finished phases. Returns the run dir.
    """
    # Lightweight env guard: the control plane only needs Gemini (instructor client). The executor's
    # full check_environment() additionally demands docker/claude/bandit, which this PoC does not use.
    if not os.environ.get("GEMINI_API_KEY"):
        log.error("🚨 CRITICAL: GEMINI_API_KEY is not set — the Nexus pipeline cannot reach the LLM.")
        sys.exit(1)

    if resume is not None:
        state = NexusState.load_checkpoint(resume)
        state.ensure_dirs()
        log.info(f"▶️ [NEXUS] RESUMING from {resume} (last completed phase: {state.completed_phase or 'none'})")
    else:
        if not raw_idea:
            log.error("🚨 CRITICAL: run_nexus requires a raw idea (or a --resume checkpoint).")
            sys.exit(1)
        state = NexusState.new(raw_idea, run_dir)
        state.ensure_dirs()
        log.info(f"🧭 [NEXUS] Control Plane starting → {state.run_dir}")

    phase = "PO"
    try:
        # Phase 1 — Product Owner → Epic. Skipped on resume if already finished (epic_text reused).
        if not state.is_done("PO"):
            state.epic_text = await run_po(state.raw_idea, state.telemetry)
            (state.artifacts_dir / "epic.md").write_text(state.epic_text, encoding="utf-8")
            state.mark_done("PO")
            state.save_checkpoint()
            log.info("   [NEXUS] Phase 1/3 complete — Epic persisted + checkpointed.")

        # Phase 2 — Solution Architect → Blueprint. Pass the verbatim raw idea so the SA honors any
        # stack the USER explicitly mandated (the Epic is language-neutral and would otherwise drop it).
        phase = "SA"
        if not state.is_done("SA"):
            state.blueprint_text = await run_sa(state.epic_text, state.raw_idea, state.telemetry)
            (state.artifacts_dir / "blueprint.md").write_text(state.blueprint_text, encoding="utf-8")
            state.mark_done("SA")
            state.save_checkpoint()
            log.info("   [NEXUS] Phase 2/3 complete — Blueprint persisted + checkpointed.")

        # Phase 3 — TPM → task plan.
        phase = "TPM"
        if not state.is_done("TPM"):
            state.tasks = await run_tpm(state.epic_text, state.blueprint_text, state.telemetry)
            state.mark_done("TPM")
            state.save_checkpoint()
            log.info("   [NEXUS] Phase 3/3 complete — task plan returned + checkpointed.")
    except SystemExit:
        raise  # an inner guard (e.g. quota) already logged + chose the exit code
    except Exception as exc:
        # Terminal LLM failure (e.g. Gemini RECITATION → empty completion → pydantic ValidationError).
        # Surface the ROOT cause in one line + a redacted incident report instead of a raw traceback.
        reason = describe_finish_reason(exc) or f"{type(exc).__name__}: {exc}"
        log.error(f"🚨 CRITICAL: Nexus halted at the {phase} phase — {reason}")
        _write_incident_report(state)
        _write_finops_report(state)
        log_finops_summary(state.telemetry, effective_budget_usd())
        sys.exit(1)

    # Materialise every planned task as a discrete Markdown ticket under artifacts/. TASK-01 (the
    # repository-preparation ticket) gets the engine-curated .gitignore appended deterministically — the
    # TPM no longer reproduces it verbatim (that tripped Gemini RECITATION). README.md/LICENSE/CHANGELOG.md
    # are no longer scaffolded here: the Technical Writer owns them post-implementation.
    # Collect all unique environment_ids across the plan so TASK-01's .gitignore covers every
    # technology layer (e.g. both python + node for a fullstack monorepo).
    all_env_ids = list(dict.fromkeys(
        t.get("environment_id", "") for t in state.tasks if t.get("environment_id")
    ))
    written = []
    for i, task in enumerate(state.tasks, start=1):
        ticket_id = _safe_ticket_id(task.get("ticket_id", ""), i)
        title = task.get("title", "").strip() or ticket_id
        description = task.get("description", "").strip()
        # Write the component tag as a byte-stable engine-authored section BEFORE the LLM description
        # so the TechLead reads it directly and never has to infer working_directory from file paths.
        component = task.get("component", "BACKEND")
        if i == 1:
            description = f"{description}\n\n{build_gitignore_baseline_block(all_env_ids)}"
        ticket_path = state.artifacts_dir / f"{ticket_id}.md"
        ticket_path.write_text(f"# {title}\n\n## Component: {component}\n\n{description}\n", encoding="utf-8")
        written.append(ticket_path.name)

    log.info(f"✅ [NEXUS] Wrote epic.md, blueprint.md, and {len(written)} ticket(s): {written}")
    _write_finops_report(state)
    log_finops_summary(state.telemetry, effective_budget_usd())
    return state.run_dir


def _write_finops_report(state: NexusState) -> None:
    """Persist the cumulative FinOps breakdown to ``reports/finops_report.json`` (executor parity).
    Non-fatal: a reporting hiccup must never mask the real run outcome."""
    try:
        report = state.telemetry.finops_report(effective_budget_usd())
        # default=str serialises Decimal money as exact strings (json can't encode Decimal natively).
        (state.reports_dir / "finops_report.json").write_text(
            json.dumps(report, indent=2, default=str), encoding="utf-8"
        )
    except Exception as e:
        log.debug(f"Failed to write Nexus finops_report.json: {e}")


def _write_incident_report(state: NexusState) -> None:
    """Persist the redacted run state to ``reports/incident_report.json`` on a terminal halt (mirrors
    the executor's _abort_with_incident). Non-fatal."""
    try:
        incident_file = state.reports_dir / "incident_report.json"
        incident_file.write_text(redact(state.model_dump_json(indent=2)), encoding="utf-8")
        log.error(f"  └── Incident report written to {incident_file}")
    except Exception as e:
        log.debug(f"Failed to write Nexus incident_report.json: {e}")
