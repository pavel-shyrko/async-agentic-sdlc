# Nexus Control Plane — TPM agent. Breaks an Epic + Blueprint into atomic Developer task tickets.
from pydantic import BaseModel, Field, field_validator

from src.shared.core.environments import SUPPORTED_ENVIRONMENTS
from src.shared.core.observability import log
from src.shared.core.prompts import get_system_prompt_with_platforms
from src.shared.utils.llm import run_structured_llm


class TaskTicket(BaseModel):
    ticket_id: str = Field(description="Stable ticket id, e.g. TASK-01.")
    title: str = Field(description="Short imperative title for the task.")
    environment_id: str = Field(description="The Paved-Road platform id this ticket executes on, copied verbatim from the Blueprint. MUST be one of the strictly supported environments.")
    description: str = Field(description="A 100% self-contained ticket body. Embed inline (copied from the Blueprint, never referenced): Objective, exact File Path(s), version-pinned Tech Stack, Dependencies, Architectural Constraints with numeric NFRs, Data Contracts/Signatures (names, inputs, outputs, exceptions), and Given/When/Then Acceptance Criteria. NEVER write 'as per the blueprint' or 'see epic' — an agent that never saw the Blueprint must implement this with zero further questions. For the mandatory baseline ticket TASK-01, embed the FULL literal contents inline: the exact .gitignore patterns tailored to environment_id, the README.md structure (Project Goal, Tech Stack, Local Setup/Execution Commands), and the complete MIT LICENSE text (year 2026, copyright holder set to the repository author). These files may already exist: instruct the executor to update/merge them idempotently (add missing patterns/sections, preserve existing content) rather than blindly overwrite.")

    @field_validator("environment_id")
    @classmethod
    def _validate_environment_id(cls, v: str) -> str:
        if v not in SUPPORTED_ENVIRONMENTS:
            raise ValueError(
                f"Unsupported environment_id '{v}'. "
                f"Choose one of: {sorted(SUPPORTED_ENVIRONMENTS)}."
            )
        return v


class ProjectPlan(BaseModel):
    """Structured plan: the TPM returns its JSON array of tickets as this typed list."""
    tasks: list[TaskTicket] = Field(description="Atomic, ordered Developer tasks covering the whole project.")


async def run_tpm(epic_text: str, blueprint_text: str) -> list[dict]:
    """Invoke the TPM on the Epic + Blueprint; returns a list of task dicts (ticket_id/title/description)."""
    log.info("🟨 [ROLE] Technical Project Manager Agent | [PROVIDER] Gemini")
    user_content = (
        f"=== EPIC ===\n{epic_text}\n\n"
        f"=== BLUEPRINT ===\n{blueprint_text}"
    )
    result, _ = await run_structured_llm(
        "tpm",
        ProjectPlan,
        [
            {"role": "system", "content": get_system_prompt_with_platforms("tpm")},
            {"role": "user", "content": user_content},
        ],
    )
    log.info(f"   [ARTIFACT] Planned {len(result.tasks)} task ticket(s).")
    return [t.model_dump() for t in result.tasks]
