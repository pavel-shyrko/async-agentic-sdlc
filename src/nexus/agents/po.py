# Nexus Control Plane — Product Owner agent. Turns a raw idea string into a Markdown Epic.
from pydantic import BaseModel, Field

from src.shared.core.config import PO_MODEL
from src.shared.core.models import PipelineTelemetry
from src.shared.core.observability import log, log_token_usage
from src.shared.core.prompts import get_system_prompt
from src.shared.utils.llm import run_structured_llm


class EpicDocument(BaseModel):
    """Structured wrapper so the markdown Epic comes back through the (structured-only) LLM utility."""
    markdown: str = Field(description="The full Epic as Markdown: Title, Goal, measurable Success Metrics, and 3-5 User Stories. Every story carries explicit Given/When/Then acceptance criteria, in/out-of-scope boundaries, edge cases, and numeric success metrics. No marketing speak.")


async def run_po(raw_idea: str, telemetry: PipelineTelemetry | None = None) -> str:
    """Invoke the Product Owner to expand a raw idea into a Markdown Epic; returns the markdown.

    Logs token/cost telemetry into ``telemetry`` when provided (executor-parity observability)."""
    log.info(f"🟦 [ROLE] Product Owner Agent | [PROVIDER] Gemini | [MODEL] {PO_MODEL}")
    result, raw_response = await run_structured_llm(
        "po",
        EpicDocument,
        [
            {"role": "system", "content": get_system_prompt("po")},
            {"role": "user", "content": raw_idea},
        ],
    )
    if telemetry is not None:
        log_token_usage(telemetry, "Product Owner Agent", raw_response, PO_MODEL)
    log.info("   [THOUGHT] Expanded the raw idea into a structured Epic (goal, success metrics, user stories with Given/When/Then).")
    log.info(f"   [ARTIFACT] Epic drafted ({len(result.markdown)} chars).")
    return result.markdown
