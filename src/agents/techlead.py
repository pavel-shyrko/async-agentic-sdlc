from src.core.observability import log, log_token_usage
from src.core.config import TECHLEAD_MODEL
from src.core.models import TechLeadContract, GlobalPipelineContext
from src.core.prompts import get_system_prompt, build_agent_context, generate_repo_map
from src.utils.llm import run_structured_llm

# ==========================================
# AGENT NODES
# ==========================================
async def run_techlead_node(ctx: GlobalPipelineContext) -> None:
    model_name = TECHLEAD_MODEL
    log.info(f"🔷 [ROLE] TechLead Agent | [MODEL] {model_name}")

    code_prefix = ctx.workspace_paths.code_dir.relative_to(ctx.workspace_paths.repo_dir).as_posix()

    if not ctx.repository_map:
        ctx.repository_map = generate_repo_map(ctx.workspace_paths.repo_dir)

    # Deterministic early language detection: the techlead produces domain_tags, so its own
    # context cannot route on the (not-yet-built) contract. Infer the stack from the repo map.
    early_tags = ["python"] if ".py" in ctx.repository_map else []
    sys_prompt = get_system_prompt("techlead") + "\n\n" + await build_agent_context(
        "techlead", ctx, topology_kwargs={"code_prefix": code_prefix}, inferred_tags=early_tags
    )

    contract, raw_response = await run_structured_llm(
        "techlead",
        TechLeadContract,
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
    log_token_usage(ctx, "TechLead", raw_response, TECHLEAD_MODEL)

    log.info(f"   [THOUGHT] {ctx.contract.techlead_reasoning}")
    log.info(f"   [ARTIFACT] Contract locked for: {ctx.contract.files_to_modify}\n")
    log.debug(f"TechLead Node Output: {ctx.contract.model_dump_json(indent=2)}")
