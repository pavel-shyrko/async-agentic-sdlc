from src.shared.core.observability import log, log_token_usage
from src.shared.core.config import DB_ARCHITECT_MODEL
from src.shared.core.models import SchemaContract, GateViolation, PipelineTelemetry
from src.shared.core.prompts import get_system_prompt
from src.shared.utils.llm import run_structured_llm


async def run_db_architect_node(
    telemetry: PipelineTelemetry,
    *,
    blueprint_text: str,
    gate_violations: list[GateViolation] | None = None,
) -> SchemaContract:
    """Generate a complete PostgreSQL SchemaContract from the nexus blueprint (E7).

    Called once on the first attempt; re-called with ``gate_violations`` on a schema-gate
    failure so the model corrects only the failing constraints instead of starting from scratch.
    Mirrors the ``run_devops_node`` pattern: prompt only, no git operations.
    """
    log.info(f"🔷 [ROLE] DB Architect Agent | [MODEL] {DB_ARCHITECT_MODEL}")

    user_content = f"=== APPLICATION BLUEPRINT ===\n{blueprint_text}"
    if gate_violations:
        feedback = "\n".join(f"- {v.table_name}: {v.violation}" for v in gate_violations)
        user_content += f"\n\n=== SCHEMA GATE VIOLATIONS FROM PREVIOUS ATTEMPT ===\n{feedback}"

    result, raw_response = await run_structured_llm(
        "db_architect",
        SchemaContract,
        [
            {"role": "system", "content": get_system_prompt("db_architect")},
            {"role": "user",   "content": user_content},
        ],
    )
    log_token_usage(telemetry, "DB Architect Agent", raw_response, DB_ARCHITECT_MODEL)
    log.info(f"   [ARTIFACT] DB Architect: {len(result.tables)} tables, "
             f"{len(result.indexes)} indexes, {len(result.views)} views.\n")
    return result
