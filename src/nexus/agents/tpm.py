# Nexus Control Plane — TPM agent. Breaks an Epic + Blueprint into atomic Developer task tickets.
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

from src.shared.core.config import TPM_MODEL
from src.shared.core.environments import SUPPORTED_ENVIRONMENTS
from src.shared.core.models import PipelineTelemetry
from src.shared.core.observability import log, log_token_usage
from src.shared.core.prompts import get_system_prompt_with_platforms
from src.shared.utils.llm import run_structured_llm


class ComponentType(str, Enum):
    """Component classification for a task ticket in a monorepo or multi-component project."""
    BACKEND = "BACKEND"
    FRONTEND = "FRONTEND"
    INFRA = "INFRA"
    SHARED = "SHARED"


class TaskTicket(BaseModel):
    ticket_id: str = Field(description="Stable ticket id (e.g. TASK-01, TASK-02); numbering/ordering rules in the system prompt.")
    title: str = Field(description="Short imperative title for the task.")
    environment_id: str = Field(description="The supported Paved-Road platform id this ticket runs on, copied from the Blueprint.")
    component: ComponentType = Field(
        default=ComponentType.BACKEND,
        description="Component this ticket belongs to — exactly ONE of BACKEND, FRONTEND, INFRA, or SHARED. "
                    "ALWAYS set it; a ticket NEVER spans two components. It is the universal driver of the "
                    "gate working_directory (BACKEND->backend/, FRONTEND->frontend/). A single-component app "
                    "still sets it (a backend-only app is all BACKEND).")
    depends_on: list[str] = Field(
        default_factory=list,
        description="The explicit cross-plane dependency graph: the prior TASK-XX id(s) this ticket is "
                    "BLOCKED by. A FRONTEND ticket MUST list the BACKEND ticket(s) whose API contract it "
                    "consumes. Every referenced id MUST be an EARLIER ticket in the plan (dependencies "
                    "precede dependents); empty for a ticket with no blockers (e.g. TASK-01).")
    description: str = Field(description="The full, self-contained ticket body following the PER-TICKET STRUCTURE in the system prompt (and, for TASK-01, a leading repository-preparation block).")

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

    @model_validator(mode="after")
    def _validate_dependency_graph(self) -> "ProjectPlan":
        """Enforce the cross-plane dependency graph so the existing TPM-order execution is correct:
        every ``depends_on`` edge points to an EARLIER ticket (dependencies precede dependents, which also
        makes a cycle impossible), references resolve, and a BACKEND ticket is never blocked by a FRONTEND
        one (the backend-before-frontend plane invariant). On a violation, instructor re-prompts the TPM.
        """
        index = {t.ticket_id: i for i, t in enumerate(self.tasks)}
        by_id = {t.ticket_id: t for t in self.tasks}
        for i, t in enumerate(self.tasks):
            for dep in dict.fromkeys(t.depends_on):  # dedupe, preserve order
                if dep == t.ticket_id:
                    raise ValueError(f"{t.ticket_id} cannot depend on itself.")
                if dep not in index:
                    raise ValueError(f"{t.ticket_id} depends_on unknown ticket '{dep}'.")
                if index[dep] >= i:
                    raise ValueError(
                        f"{t.ticket_id} depends_on '{dep}', which is not ordered before it — "
                        f"dependencies must precede dependents."
                    )
                if t.component == ComponentType.BACKEND and by_id[dep].component == ComponentType.FRONTEND:
                    raise ValueError(
                        f"{t.ticket_id} (BACKEND) cannot depend on {dep} (FRONTEND) — "
                        f"backend tickets precede frontend tickets."
                    )
        return self


async def run_tpm(epic_text: str, blueprint_text: str, telemetry: PipelineTelemetry | None = None) -> list[dict]:
    """Invoke the TPM on the Epic + Blueprint; returns a list of task dicts (ticket_id/title/description).

    Logs token/cost telemetry into ``telemetry`` when provided (executor-parity observability)."""
    log.info(f"🟨 [ROLE] Technical Project Manager Agent | [PROVIDER] Gemini | [MODEL] {TPM_MODEL}")
    user_content = (
        f"=== EPIC ===\n{epic_text}\n\n"
        f"=== BLUEPRINT ===\n{blueprint_text}"
    )
    result, raw_response = await run_structured_llm(
        "tpm",
        ProjectPlan,
        [
            {"role": "system", "content": get_system_prompt_with_platforms("tpm")},
            {"role": "user", "content": user_content},
        ],
    )
    if telemetry is not None:
        log_token_usage(telemetry, "Technical Project Manager Agent", raw_response, TPM_MODEL)
    log.info("   [THOUGHT] Decomposed the Blueprint into atomic, ordered Developer task tickets.")
    log.info(f"   [ARTIFACT] Planned {len(result.tasks)} task ticket(s).")
    return [t.model_dump(mode="json") for t in result.tasks]
