from src.core.observability import log
from src.core.config import DEVELOPER_MODEL_LABEL
from src.core.models import GlobalPipelineContext
from src.core.prompts import get_system_prompt, get_skill
from src.utils.subprocess_helpers import run_claude_cli

async def run_developer_node(ctx: GlobalPipelineContext, error_trace: str = "") -> None:
    model_name = DEVELOPER_MODEL_LABEL
    log.info(f"🟩 [ROLE] Developer Agent | [MODEL] {model_name}")

    prompt = get_system_prompt("developer").format(
        instruction=ctx.contract.instruction,
        function_signatures=ctx.contract.function_signatures,
        strict_type_validation_rules=ctx.contract.strict_type_validation_rules,
        code_dir=ctx.workspace_paths.code_dir,
    ) + "\n\n" + get_skill("engineering_guide")

    # Strict pathing guardrail: stop the Developer nesting dirs (e.g. src/src/), which desyncs the snapshot.
    prompt += (
        "\n\nCRITICAL PATHING RULE: All file paths in the contract are strictly relative to the "
        "repository root. Do NOT nest directories (e.g., writing to `src/src/`). Obey exact paths."
    )

    if error_trace:
        prompt += f"\n\nValidation Failure Context:\n{error_trace}"
        prompt += "\n\n" + get_skill("deterministic_mutation")

    code_dir_path = ctx.workspace_paths.code_dir
    code_dir = str(code_dir_path)

    # The clone is already a git repo on feat/ticket-<id>; agents only mutate the working tree.
    code_files = [str(code_dir_path / f) for f in ctx.contract.files_to_modify]
    returncode = await run_claude_cli(prompt, code_files, allowed_root=code_dir)

    log.info(f"   [TOKENS] Developer Agent | Tracked out-of-band via ccusage")

    # The orchestrator's build_production_snapshot() captures the real working-tree delta after this
    # node returns; the Developer no longer self-reports the snapshot (which caused Reviewer desync).
    log.info(f"   [MUTATION] Developer node complete (Exit Code: {returncode}).\n")
