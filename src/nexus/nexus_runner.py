# Nexus Control Plane orchestrator. Drives the PO -> SA -> TPM trio for a raw idea and
# materialises the Epic, Blueprint, and per-task tickets under tickets/generated/ for observability.
import os
import re
import sys
from pathlib import Path

from src.shared.core.observability import log
from src.nexus.po import run_po
from src.nexus.sa import run_sa
from src.nexus.tpm import run_tpm

# Default output dir for generated control-plane artifacts. Env-overridable so tests/parallel
# runs can relocate it off the repo tree.
OUTPUT_DIR = Path(os.environ.get("NEXUS_OUTPUT_DIR", "tickets/generated"))

# Filesystem-safe ticket id (used verbatim in the TASK-XX.md filename).
_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_ticket_id(ticket_id: str, index: int) -> str:
    """Sanitise a model-provided ticket id into a safe filename stem; fall back to TASK-NN."""
    slug = _SLUG_RE.sub("-", (ticket_id or "").strip()).strip("-")
    return slug or f"TASK-{index:02d}"


async def run_nexus(raw_idea: str, output_dir: Path | None = None) -> Path:
    """Run the full Nexus pipeline for one raw idea and write all artifacts; returns the output dir.

    Flow: raw_idea -> PO (Epic) -> SA (Blueprint) -> TPM (tasks). The Epic and Blueprint are
    persisted for observability, and every planned task becomes a discrete Markdown ticket.
    """
    # Lightweight env guard: the control plane only needs Gemini (instructor client). The executor's
    # full check_environment() additionally demands docker/claude/bandit, which this PoC does not use.
    if not os.environ.get("GEMINI_API_KEY"):
        log.error("🚨 CRITICAL: GEMINI_API_KEY is not set — the Nexus pipeline cannot reach the LLM.")
        sys.exit(1)

    out_dir = Path(output_dir) if output_dir is not None else OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    log.info(f"🧭 [NEXUS] Control Plane PoC starting → {out_dir}")

    epic_text = await run_po(raw_idea)
    (out_dir / "epic.md").write_text(epic_text, encoding="utf-8")

    # Pass the verbatim raw idea so the SA honors any stack the USER explicitly mandated (the Epic is
    # deliberately language-neutral and would otherwise drop it before the stack-decider sees it).
    blueprint_text = await run_sa(epic_text, raw_idea)
    (out_dir / "blueprint.md").write_text(blueprint_text, encoding="utf-8")

    tasks = await run_tpm(epic_text, blueprint_text)

    written = []
    for i, task in enumerate(tasks, start=1):
        ticket_id = _safe_ticket_id(task.get("ticket_id", ""), i)
        title = task.get("title", "").strip() or ticket_id
        description = task.get("description", "").strip()
        ticket_path = out_dir / f"{ticket_id}.md"
        ticket_path.write_text(f"# {title}\n\n{description}\n", encoding="utf-8")
        written.append(ticket_path.name)

    log.info(f"✅ [NEXUS] Wrote epic.md, blueprint.md, and {len(written)} ticket(s): {written}")
    return out_dir
