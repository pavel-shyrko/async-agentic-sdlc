from src.core.observability import log
from src.core.config import DEVELOPER_MODEL_LABEL
from src.core.models import GlobalPipelineContext
from src.core.prompts import get_system_prompt, build_agent_context
from src.utils.subprocess_helpers import run_claude_cli

async def run_developer_node(ctx: GlobalPipelineContext, error_trace: str = "") -> None:
    model_name = DEVELOPER_MODEL_LABEL
    log.info(f"🟩 [ROLE] Developer Agent | [MODEL] {model_name}")

    repo_dir_path = ctx.workspace_paths.repo_dir
    repo_dir = str(repo_dir_path)

    prompt = get_system_prompt("developer").format(
        instruction=ctx.contract.instruction,
        function_signatures=ctx.contract.function_signatures,
        strict_type_validation_rules=ctx.contract.strict_type_validation_rules,
        code_dir=repo_dir,
    )
    prompt += "\n\n" + await build_agent_context(
        "developer", ctx, is_retry=bool(error_trace), topology_kwargs={"code_dir": repo_dir}
    )

    if error_trace:
        prompt += f"\n\nValidation Failure Context:\n{error_trace}"

    # The clone is already a git repo on feat/ticket-<id>; agents only mutate the working tree.
    code_files = [str(repo_dir_path / f) for f in ctx.contract.files_to_modify]
    returncode = await run_claude_cli(prompt, code_files, allowed_root=repo_dir)

    log.info(f"   [TOKENS] Developer Agent | Tracked out-of-band via ccusage")

    # The orchestrator's build_production_snapshot() captures the real working-tree delta after this
    # node returns; the Developer no longer self-reports the snapshot (which caused Reviewer desync).
    log.info(f"   [MUTATION] Developer node complete (Exit Code: {returncode}).\n")
