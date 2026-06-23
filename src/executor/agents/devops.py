# subprocess: only fixed-argument `git` exec with no shell=True, never untrusted input as a command.
import subprocess  # nosec B404

from src.shared.core.observability import log, log_token_usage
from src.shared.core.config import DEVOPS_MODEL
from src.shared.core.models import DevOpsManifests, GlobalPipelineContext
from src.shared.core.prompts import get_system_prompt, get_skill, _parse_frontmatter
from src.shared.utils.llm import run_structured_llm

# The three archetype skills (REST API / CRUD / CLI). All are injected so the agent can self-classify
# the finished app and follow the matching branch — the chosen class is recorded in DevOpsManifests.archetype.
_DEVOPS_SKILLS = ("devops_rest_api", "devops_crud_app", "devops_cli_tool")

# Files the node writes into the clone (relative to repo root). Dockerfile/.env.example are conditional.
_WORKFLOW_PATH = ".github/workflows/deploy.yml"
_DOCKERFILE_PATH = "Dockerfile"
_ENV_EXAMPLE_PATH = ".env.example"


def _archetype_guidance() -> str:
    """Concatenate the archetype skill bodies (frontmatter stripped) for the system prompt."""
    blocks = []
    for name in _DEVOPS_SKILLS:
        _meta, body = _parse_frontmatter(get_skill(name))
        blocks.append(body.strip())
    return "\n\n".join(blocks)


# ==========================================
# AGENT NODES
# ==========================================
async def run_devops_node(
    ctx: GlobalPipelineContext,
    *,
    blueprint_text: str,
    repo_map: str,
    environment_ids: str = "",
    ci_commands: str = "",
    gate_feedback: str = "",
) -> None:
    """Generate deploy manifests for the finished app and stage them (E4 deploy-scaffolding).

    Runs once, in the post-batch ``run_devops_scaffold`` phase, against a fresh clone of the completed
    base branch. Classifies the application archetype (web service vs CLI/library), then writes a
    GitHub Actions deploy workflow — and, for a web service, a multi-stage non-root Dockerfile — into
    the clone and ``git add``s them so ``finalize_transaction``'s atomic commit includes them. Builds
    its prompt directly (no ``build_agent_context``: there is no TechLeadContract in this phase).
    ``gate_feedback`` carries the static-lint errors from a prior attempt on a self-heal retry.
    """
    log.info(f"🔷 [ROLE] DevOps Agent | [MODEL] {DEVOPS_MODEL}")

    repo_dir = ctx.workspace_paths.repo_dir
    system_prompt = f"{get_system_prompt('devops')}\n\n=== ARCHETYPE GUIDANCE ===\n{_archetype_guidance()}"

    user_content = (
        f"=== APPLICATION BLUEPRINT ===\n{blueprint_text}\n\n"
        f"=== PLATFORM / ENVIRONMENT ID(S) ===\n{environment_ids or '(unknown)'}\n\n"
    )
    if ci_commands:
        user_content += (
            "=== CANONICAL PROJECT COMMANDS (the CI build/test/lint steps MUST run EXACTLY these — they are\n"
            "the same commands the engine validated this code with; do NOT invent extra linters/type-checkers) ===\n"
            f"{ci_commands}\n\n"
        )
    user_content += f"=== FINISHED REPOSITORY MAP (base branch) ===\n{repo_map}"
    if gate_feedback:
        user_content += (
            "\n\n=== STATIC-VALIDATION ERRORS FROM YOUR PREVIOUS ATTEMPT (fix exactly these) ===\n"
            f"{gate_feedback}"
        )

    result, raw_response = await run_structured_llm(
        "devops",
        DevOpsManifests,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    )
    log_token_usage(ctx.telemetry, "DevOps Agent", raw_response, DEVOPS_MODEL)
    ctx.devops_manifests = result

    # Write the manifests into the clone. The workflow is always written; the Dockerfile only for a web
    # service (null for a CLI tool); the env scaffold only when provided.
    staged: list[str] = []
    workflow_file = repo_dir / _WORKFLOW_PATH
    workflow_file.parent.mkdir(parents=True, exist_ok=True)
    workflow_file.write_text(result.workflow_content, encoding="utf-8")
    staged.append(_WORKFLOW_PATH)

    if result.dockerfile_content:
        (repo_dir / _DOCKERFILE_PATH).write_text(result.dockerfile_content, encoding="utf-8")
        staged.append(_DOCKERFILE_PATH)

    if result.env_scaffold_content:
        (repo_dir / _ENV_EXAMPLE_PATH).write_text(result.env_scaffold_content, encoding="utf-8")
        staged.append(_ENV_EXAMPLE_PATH)

    # Stage so finalize_transaction's atomic commit includes the manifests.
    subprocess.run(  # nosec B603 B607 — fixed git argv, no shell
        ["git", "add", *staged], cwd=str(repo_dir), check=True,
    )
    log.info(f"   [ARTIFACT] DevOps Agent ({result.archetype}) staged: {', '.join(staged)}\n")
