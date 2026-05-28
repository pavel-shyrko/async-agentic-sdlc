import asyncio

from src.core.observability import log, log_token_usage
from src.core.config import instructor_client, ARCHITECT_MODEL
from src.core.models import ArchitectureContract, GlobalPipelineContext
from src.utils.api_retry import with_api_retry

# ==========================================
# AGENT NODES
# ==========================================
async def run_architect_node(ctx: GlobalPipelineContext) -> None:
    model_name = ARCHITECT_MODEL
    log.info(f"🔷 [ROLE] Architect Agent | [MODEL] {model_name}")

    sys_prompt = "You are a Principal Architect. Define strict production file mappings, type guards, and function signatures. Be concise. No prose."

    @with_api_retry(max_retries=3, agent_name="Architect Agent")
    async def _invoke_llm() -> tuple:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: instructor_client.chat.completions.create_with_completion(
                model=model_name,
                response_model=ArchitectureContract,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": ctx.pr_description}
                ]
            )
        )

    contract, raw_response = await _invoke_llm()
    ctx.contract = contract
    log_token_usage("Architect", raw_response)

    log.info(f"   [THOUGHT] {ctx.contract.architecture_reasoning}")
    log.info(f"   [ARTIFACT] Contract locked for: {ctx.contract.files_to_modify}\n")
    log.debug(f"Architect Node Output: {ctx.contract.model_dump_json(indent=2)}")
