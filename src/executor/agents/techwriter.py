# subprocess: only fixed-argument `git` exec with no shell=True, never untrusted input as a command.
import subprocess  # nosec B404

from src.shared.core.observability import log, log_token_usage
from src.shared.core.config import TECHWRITER_MODEL
from src.shared.core.models import ArchitectureUpdate, GlobalPipelineContext
from src.shared.core.prompts import get_system_prompt
from src.shared.utils.llm import run_structured_llm

# ==========================================
# AGENT NODES
# ==========================================
async def run_techwriter_node(ctx: GlobalPipelineContext) -> None:
    """Maintain the living ADR (docs/architecture_state.md) on verified success, then stage it.

    Runs only inside the success branch, after the Reviewer has approved and the production delta is
    already staged. Reads the PREVIOUS on-disk document, the completed task, the TechLead contract,
    and the production code snapshot, rewrites the cumulative architecture document, and `git add`s it
    so finalize_transaction's single atomic commit includes the update. Does NOT call
    build_agent_context (which would re-inject the very document it is about to rewrite).
    """
    log.info(f"🔷 [ROLE] Technical Writer Agent | [MODEL] {TECHWRITER_MODEL}")

    repo_dir = ctx.workspace_paths.repo_dir
    adr_path = repo_dir / "docs" / "architecture_state.md"
    # GUARD: the document does not exist on the first task — never do a bare read_text().
    previous_adr = (
        adr_path.read_text(encoding="utf-8").strip()
        if adr_path.exists()
        else "(No architecture state documented yet. This is the first iteration.)"
    )

    contract_text = ctx.contract.model_dump_json(indent=2) if ctx.contract else "(no contract)"
    code_text = "\n\n".join(
        f"### {path}\n{content}" for path, content in sorted(ctx.production_code_snapshot.items())
    )
    user_content = (
        f"=== COMPLETED TASK ===\n{ctx.pr_description}\n\n"
        f"=== TECHLEAD CONTRACT ===\n{contract_text}\n\n"
        f"=== PRODUCTION CODE SNAPSHOT ===\n{code_text}\n\n"
        f"=== PREVIOUS ARCHITECTURE DOCUMENT ===\n{previous_adr}"
    )

    result, raw_response = await run_structured_llm(
        "techwriter",
        ArchitectureUpdate,
        [
            {"role": "system", "content": get_system_prompt("techwriter")},
            {"role": "user", "content": user_content},
        ],
    )
    log_token_usage(ctx.telemetry, "Technical Writer", raw_response, TECHWRITER_MODEL)

    adr_path.parent.mkdir(parents=True, exist_ok=True)
    adr_path.write_text(result.updated_architecture_document, encoding="utf-8")
    # Stage so finalize_transaction's atomic success commit includes the updated ADR.
    subprocess.run(  # nosec B603 B607 — fixed git argv, no shell
        ["git", "add", "docs/architecture_state.md"], cwd=str(repo_dir), check=True,
    )
    log.info("   [ARTIFACT] Technical Writer updated and staged docs/architecture_state.md\n")
