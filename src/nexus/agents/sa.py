# Nexus Control Plane — Solution Architect agent. Turns an Epic into a technical Markdown Blueprint.
from pydantic import BaseModel, Field, field_validator

from src.shared.core.config import SA_MODEL
from src.shared.core.environments import SUPPORTED_ENVIRONMENTS
from src.shared.core.models import PipelineTelemetry
from src.shared.core.observability import log, log_token_usage
from src.shared.core.prompts import get_system_prompt_with_platforms
from src.shared.utils.llm import run_structured_llm


class Blueprint(BaseModel):
    """Structured wrapper carrying the architect's Markdown Blueprint."""
    environment_id: str = Field(description="The single supported Paved-Road platform id this Blueprint targets (selection rules in the system prompt).")
    markdown: str = Field(description="The Technical Blueprint as Markdown, structured per the OUTPUT CONTRACT in the system prompt.")

    @field_validator("environment_id")
    @classmethod
    def _validate_environment_id(cls, v: str) -> str:
        if v not in SUPPORTED_ENVIRONMENTS:
            raise ValueError(
                f"Unsupported environment_id '{v}'. "
                f"Choose one of: {sorted(SUPPORTED_ENVIRONMENTS)}."
            )
        return v


async def run_sa(epic_text: str, raw_idea: str = "", telemetry: PipelineTelemetry | None = None) -> str:
    """Invoke the Solution Architect on the Epic; returns the Blueprint markdown.

    Passes the verbatim ``raw_idea`` alongside the Epic as labeled data blocks; the rule for what to do
    with them (honor an explicitly user-mandated stack) lives in sa.md, which references these block
    names. Assembly only — no instructions here. ``telemetry`` collects token/cost (executor parity).
    """
    user_content = epic_text
    if raw_idea.strip():
        user_content = (
            f"=== ORIGINAL USER REQUEST ===\n{raw_idea}\n\n"
            f"=== EPIC ===\n{epic_text}"
        )
    log.info(f"🟪 [ROLE] Solution Architect Agent | [PROVIDER] Gemini | [MODEL] {SA_MODEL}")
    result, raw_response = await run_structured_llm(
        "sa",
        Blueprint,
        [
            {"role": "system", "content": get_system_prompt_with_platforms("sa")},
            {"role": "user", "content": user_content},
        ],
    )
    if telemetry is not None:
        log_token_usage(telemetry, "Solution Architect Agent", raw_response, SA_MODEL)
    log.info(f"   [THOUGHT] Selected the Paved-Road platform and drafted the technical Blueprint.")
    log.info(f"   [ARTIFACT] Blueprint drafted (environment_id: {result.environment_id}, {len(result.markdown)} chars).")
    return result.markdown
