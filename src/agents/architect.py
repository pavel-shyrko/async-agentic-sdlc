from src.core.observability import log, log_token_usage
from src.core.config import ARCHITECT_MODEL
from src.core.models import ArchitectureContract, GlobalPipelineContext
from src.core.prompts import get_system_prompt, build_agent_context, generate_repo_map
from src.utils.llm import run_structured_llm

# ==========================================
# AGENT NODES
# ==========================================
async def run_architect_node(ctx: GlobalPipelineContext) -> None:
    model_name = ARCHITECT_MODEL
    log.info(f"🔷 [ROLE] Architect Agent | [MODEL] {model_name}")

    code_prefix = ctx.workspace_paths.code_dir.relative_to(ctx.workspace_paths.repo_dir).as_posix()

    if not ctx.repository_map:
        ctx.repository_map = generate_repo_map(ctx.workspace_paths.repo_dir)

    # Deterministic early language detection: the architect produces domain_tags, so its own
    # context cannot route on the (not-yet-built) contract. Infer the stack from the repo map.
    early_tags = ["python"] if ".py" in ctx.repository_map else []
    sys_prompt = get_system_prompt("architect") + "\n\n" + await build_agent_context(
        "architect", ctx, topology_kwargs={"code_prefix": code_prefix}, inferred_tags=early_tags
    )

    contract, raw_response = await run_structured_llm(
        "architect",
        ArchitectureContract,
        [
            {"role": "system", "content": sys_prompt},
            {
                "role": "user",
                "content": f"=== EXISTING REPOSITORY TOPOLOGY ===\n{ctx.repository_map}\n\n"
                + ctx.pr_description,
            },
        ],
    )
    ctx.contract = contract
    log_token_usage("Architect", raw_response)

    log.info(f"   [THOUGHT] {ctx.contract.architecture_reasoning}")
    log.info(f"   [ARTIFACT] Contract locked for: {ctx.contract.files_to_modify}\n")
    log.debug(f"Architect Node Output: {ctx.contract.model_dump_json(indent=2)}")
