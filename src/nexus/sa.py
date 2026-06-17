# Nexus Control Plane — Solution Architect agent. Turns an Epic into a technical Markdown Blueprint.
from pydantic import BaseModel, Field, field_validator

from src.shared.core.environments import SUPPORTED_ENVIRONMENTS
from src.shared.core.observability import log
from src.shared.core.prompts import get_system_prompt_with_platforms
from src.shared.utils.llm import run_structured_llm


class Blueprint(BaseModel):
    """Structured wrapper carrying the architect's Markdown Blueprint."""
    environment_id: str = Field(description="The single Paved-Road platform id this Blueprint targets. MUST be one of the strictly supported environments — you cannot invent a tech stack.")
    markdown: str = Field(description="Technical Blueprint as Markdown: version-pinned tech stack, hard Non-Functional Requirements with numeric limits, exact File Topology tree, and core Data Contracts & Interfaces (inputs, outputs, exceptions). Every constraint a discrete, quotable bullet. Zero ambiguity.")

    @field_validator("environment_id")
    @classmethod
    def _validate_environment_id(cls, v: str) -> str:
        if v not in SUPPORTED_ENVIRONMENTS:
            raise ValueError(
                f"Unsupported environment_id '{v}'. "
                f"Choose one of: {sorted(SUPPORTED_ENVIRONMENTS)}."
            )
        return v


async def run_sa(epic_text: str, raw_idea: str = "") -> str:
    """Invoke the Solution Architect on the Epic; returns the Blueprint markdown.

    Passes the verbatim ``raw_idea`` alongside the Epic as labeled data blocks; the rule for what to do
    with them (honor an explicitly user-mandated stack) lives in sa.md, which references these block
    names. Assembly only — no instructions here.
    """
    user_content = epic_text
    if raw_idea.strip():
        user_content = (
            f"=== ORIGINAL USER REQUEST ===\n{raw_idea}\n\n"
            f"=== EPIC ===\n{epic_text}"
        )
    log.info("🟪 [ROLE] Solution Architect Agent | [PROVIDER] Gemini")
    result, _ = await run_structured_llm(
        "sa",
        Blueprint,
        [
            {"role": "system", "content": get_system_prompt_with_platforms("sa")},
            {"role": "user", "content": user_content},
        ],
    )
    log.info("   [ARTIFACT] Blueprint drafted.")
    return result.markdown
