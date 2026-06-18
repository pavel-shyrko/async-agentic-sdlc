import re

from src.shared.core.observability import log, log_token_usage
from src.shared.core.config import TECHLEAD_MODEL
from src.shared.core.models import TechLeadContract, GlobalPipelineContext
from src.shared.core.environments import env_language
from src.shared.core.prompts import get_system_prompt, build_agent_context, generate_repo_map
from src.shared.utils.llm import run_structured_llm

# Source-extension → language tag for deterministic early skill routing (precise: the negative
# lookahead stops `.js` matching inside `.json`, `.ts` inside `.tsx`/`tsconfig`, `.cs` inside `.csproj`).
_EXT_LANG = {
    ".py": "python", ".go": "go", ".cs": "dotnet",
    ".ts": "node", ".tsx": "node", ".js": "node", ".jsx": "node",
}

# ==========================================
# AGENT NODES
# ==========================================
async def run_techlead_node(ctx: GlobalPipelineContext) -> None:
    model_name = TECHLEAD_MODEL
    log.info(f"🔷 [ROLE] Technical Lead Agent | [MODEL] {model_name}")

    if not ctx.repository_map:
        ctx.repository_map = generate_repo_map(ctx.workspace_paths.repo_dir)

    # Deterministic early language detection: the techlead produces domain_tags, so its own context
    # cannot route on the (not-yet-built) contract. Prefer a known environment_id on retry; otherwise
    # infer the stack from the repo map's file extensions (all supported languages, not just Python).
    if ctx.contract is not None:
        early_tags = [env_language(ctx.contract.environment_id)]
    else:
        early_tags = sorted({
            lang for ext, lang in _EXT_LANG.items()
            if re.search(re.escape(ext) + r"(?![A-Za-z0-9])", ctx.repository_map)
        })
    sys_prompt = get_system_prompt("techlead") + "\n\n" + await build_agent_context(
        "techlead", ctx, inferred_tags=early_tags
    )

    contract, raw_response = await run_structured_llm(
        "techlead",
        TechLeadContract,
        [
            {"role": "system", "content": sys_prompt},
            {
                "role": "user",
                "content": f"=== EXISTING REPOSITORY TOPOLOGY ===\n{ctx.repository_map}\n\n"
                + (ctx.techlead_brief or ctx.pr_description),
            },
        ],
    )
    ctx.contract = contract
    log_token_usage(ctx.telemetry, "TechLead", raw_response, TECHLEAD_MODEL)

    log.info(f"   [THOUGHT] {ctx.contract.techlead_reasoning}")
    log.info(f"   [ARTIFACT] Contract locked for: {ctx.contract.files_to_modify}\n")
    log.debug(f"TechLead Node Output: {ctx.contract.model_dump_json(indent=2)}")
