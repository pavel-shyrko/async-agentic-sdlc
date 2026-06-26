from src.shared.core.observability import log, log_token_usage
from src.shared.core.config import SEED_DATA_MODEL
from src.shared.core.models import SchemaContract, SeedOutput, PipelineTelemetry
from src.shared.core.prompts import get_system_prompt
from src.shared.utils.llm import run_structured_llm


async def run_seed_agent_node(
    telemetry: PipelineTelemetry,
    *,
    contract: SchemaContract,
    env: str,
) -> SeedOutput:
    """Generate safe, realistic INSERT statements from the provisioned schema (E7).

    Only called for ``env in ("dev", "staging")`` — never in production. Mirrors the
    ``run_devops_node`` pattern: structured output, no git operations.
    """
    log.info(f"🔷 [ROLE] Seed Data Agent | [MODEL] {SEED_DATA_MODEL} | env={env}")

    table_names = "\n".join(f"- {t.table_name}" for t in contract.tables)
    user_content = (
        f"=== ENVIRONMENT ===\n{env}\n\n"
        f"=== TABLES (dependency order) ===\n{table_names}"
    )

    result, raw_response = await run_structured_llm(
        "seed_data",
        SeedOutput,
        [
            {"role": "system", "content": get_system_prompt("seed_agent")},
            {"role": "user",   "content": user_content},
        ],
    )
    log_token_usage(telemetry, "Seed Data Agent", raw_response, SEED_DATA_MODEL)
    log.info(f"   [ARTIFACT] Seed Agent: {len(result.inserts)} INSERT statements.\n")
    return result
