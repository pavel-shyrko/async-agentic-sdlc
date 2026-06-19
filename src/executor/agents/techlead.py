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
async def run_techlead_node(ctx: GlobalPipelineContext, amendment_feedback: str = "") -> None:
    """Derive (or, when ``amendment_feedback`` is set, AMEND) the TechLead contract.

    Amendment mode is driven by the Arbiter: given the existing contract + a spec-correction directive +
    the failing evidence, the TechLead re-emits a REVISED contract that resolves a contract-level
    conflict (the runner additionally pins ``environment_id`` so the platform never thrashes).
    """
    model_name = TECHLEAD_MODEL
    amending = bool(amendment_feedback) and ctx.contract is not None
    label = "Technical Lead Agent (AMENDMENT)" if amending else "Technical Lead Agent"
    log.info(f"🔷 [ROLE] {label} | [MODEL] {model_name}")

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

    if amending:
        # Re-derivation: hand the model the failing contract + the Arbiter directive + the evidence so it
        # can produce a corrected spec. environment_id MUST stay byte-identical (pinned again in runner).
        production_code = "\n\n".join(
            f"=== FILE: {p} ===\n{c}" for p, c in ctx.production_code_snapshot.items()
        ) or "No production code captured."
        review = ctx.review_report.model_dump_json(indent=2) if ctx.review_report else "None"
        user_content = (
            "=== CONTRACT AMENDMENT MODE ===\n"
            "The current contract led the pipeline into a STUCK loop. Produce a REVISED contract that "
            "resolves the conflict described below. Keep `environment_id` UNCHANGED.\n\n"
            f"=== ARBITER AMENDMENT DIRECTIVE ===\n{amendment_feedback}\n\n"
            f"=== CURRENT (FAILING) CONTRACT ===\n{ctx.contract.model_dump_json(indent=2)}\n\n"
            f"=== REVIEWER REPORT ===\n{review}\n\n"
            f"=== GENERATED PRODUCTION CODE ===\n{production_code}\n\n"
            f"=== GENERATED TEST SUITE ===\n{ctx.test_code_snapshot}\n\n"
            f"=== EXISTING REPOSITORY TOPOLOGY ===\n{ctx.repository_map}\n\n"
            + (ctx.techlead_brief or ctx.pr_description)
        )
    else:
        user_content = (
            f"=== EXISTING REPOSITORY TOPOLOGY ===\n{ctx.repository_map}\n\n"
            + (ctx.techlead_brief or ctx.pr_description)
        )

    contract, raw_response = await run_structured_llm(
        "techlead",
        TechLeadContract,
        [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_content},
        ],
    )
    ctx.contract = contract
    log_token_usage(ctx.telemetry, "TechLead", raw_response, TECHLEAD_MODEL)

    log.info(f"   [THOUGHT] {ctx.contract.techlead_reasoning}")
    verb = "Contract amended" if amending else "Contract locked"
    log.info(f"   [ARTIFACT] {verb} for: {ctx.contract.files_to_modify}\n")
    log.debug(f"TechLead Node Output: {ctx.contract.model_dump_json(indent=2)}")
