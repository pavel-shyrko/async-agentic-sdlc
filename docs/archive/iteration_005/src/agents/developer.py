from pathlib import Path

from src.core.observability import log
from src.core.config import DEVELOPER_MODEL_LABEL
from src.core.models import GlobalPipelineContext
from src.utils.subprocess_helpers import run_claude_cli
from src.utils.git_helpers import init_sandbox_git, get_pipeline_snapshot_files

async def run_developer_node(ctx: GlobalPipelineContext, error_trace: str = "") -> None:
    model_name = DEVELOPER_MODEL_LABEL
    log.info(f"🟩 [ROLE] Developer Agent | [MODEL] {model_name}")

    prompt = (
        f"Implement the core logic. Directives: {ctx.contract.instruction}. "
        f"Signatures: {ctx.contract.function_signatures}. "
        f"Strict type rules: {ctx.contract.strict_type_validation_rules}. "
        f"Save all files under: {ctx.workspace_paths.code_dir}"
    )
    if error_trace:
        prompt += f"\n\nValidation Failure Context:\n{error_trace}"

    code_dir = str(ctx.workspace_paths.code_dir)
    await init_sandbox_git(code_dir, ctx.base_branch)

    code_files = [str(ctx.workspace_paths.code_dir / f) for f in ctx.contract.files_to_modify]
    returncode = await run_claude_cli(prompt, code_files, allowed_root=code_dir)

    log.info(f"   [TOKENS] Developer Agent | Tracked out-of-band via ccusage")

    changed_files = await get_pipeline_snapshot_files(code_dir, ctx.base_branch)
    parts = []
    for rel_path in changed_files:
        abs_path = Path(code_dir) / rel_path
        if abs_path.exists():
            parts.append(f"=== FILE: {rel_path} ===\n{abs_path.read_text(encoding='utf-8')}")
        else:
            parts.append(f"=== FILE: {rel_path} (DELETED) ===")
    if parts:
        ctx.production_code_snapshot = "\n\n".join(parts)

    log.info(f"   [MUTATION] Modified: {changed_files} (Exit Code: {returncode})\n")
    log.debug(f"Developer code snapshot:\n{ctx.production_code_snapshot}")
