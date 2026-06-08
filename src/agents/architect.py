from src.core.observability import log, log_token_usage
from src.core.config import ARCHITECT_MODEL
from src.core.models import ArchitectureContract, GlobalPipelineContext
from src.core.prompts import get_system_prompt, build_agent_context
from src.utils.llm import run_structured_llm

# ==========================================
# AGENT NODES
# ==========================================
async def run_architect_node(ctx: GlobalPipelineContext) -> None:
    model_name = ARCHITECT_MODEL
    log.info(f"🔷 [ROLE] Architect Agent | [MODEL] {model_name}")

    code_prefix = ctx.workspace_paths.code_dir.relative_to(ctx.workspace_paths.repo_dir).as_posix()
    sys_prompt = get_system_prompt("architect") + "\n\n" + await build_agent_context(
        "architect", ctx, topology_kwargs={"code_prefix": code_prefix}
    )

    contract, raw_response = await run_structured_llm(
        "architect",
        ArchitectureContract,
        [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": ctx.pr_description},
        ],
    )
    ctx.contract = contract
    log_token_usage("Architect", raw_response)

    log.info(f"   [THOUGHT] {ctx.contract.architecture_reasoning}")
    log.info(f"   [ARTIFACT] Contract locked for: {ctx.contract.files_to_modify}\n")
    log.debug(f"Architect Node Output: {ctx.contract.model_dump_json(indent=2)}")
