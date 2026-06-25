# subprocess: only fixed-argument `git` exec with no shell=True, never untrusted input as a command.
import subprocess  # nosec B404

from src.shared.core.observability import log, log_token_usage
from src.shared.core.config import TECHWRITER_MODEL
from src.shared.core.boilerplate import render_apache_license
from src.shared.core.models import DocumentationUpdate, GlobalPipelineContext
from src.shared.core.prompts import get_system_prompt_with_platforms
from src.shared.utils.llm import run_structured_llm

# ==========================================
# AGENT NODES
# ==========================================
async def run_techwriter_node(ctx: GlobalPipelineContext) -> None:
    """Maintain the human-facing documentation set on verified success, then stage it.

    Owns README.md, the root CHANGELOG.md, LICENSE, and the living ADR (docs/architecture_state.md). Runs
    only inside the success branch, after the Reviewer has approved and the production delta is already
    staged. Reads the PREVIOUS on-disk documents (absence → first-iteration placeholder, so the very first
    task creates them), the completed task, the TechLead contract, and the production code snapshot, then
    rewrites README / CHANGELOG / ADR cumulatively. The LICENSE is written DETERMINISTICALLY (engine-curated
    Apache 2.0 text via render_apache_license — no LLM, RECITATION-safe) and ONLY when absent. Every touched
    file is `git add`ed so finalize_transaction's single atomic commit includes the docs. Does NOT call
    build_agent_context (which would re-inject the very ADR it is about to rewrite).
    """
    log.info(f"🔷 [ROLE] Technical Writer Agent | [MODEL] {TECHWRITER_MODEL}")

    repo_dir = ctx.workspace_paths.repo_dir
    adr_path = repo_dir / "docs" / "architecture_state.md"
    readme_path = repo_dir / "README.md"
    changelog_path = repo_dir / "CHANGELOG.md"
    usage_path = repo_dir / "docs" / "USAGE.md"
    license_path = repo_dir / "LICENSE"

    # GUARD: a document may not exist on the first task — never do a bare read_text().
    previous_adr = (
        adr_path.read_text(encoding="utf-8").strip()
        if adr_path.exists()
        else "(No architecture state documented yet. This is the first iteration.)"
    )
    previous_readme = (
        readme_path.read_text(encoding="utf-8").strip()
        if readme_path.exists()
        else "(No README yet. This is the first iteration — author it from scratch.)"
    )
    previous_changelog = (
        changelog_path.read_text(encoding="utf-8").strip()
        if changelog_path.exists()
        else "(No CHANGELOG yet. This is the first iteration — author it from scratch.)"
    )
    previous_usage = (
        usage_path.read_text(encoding="utf-8").strip()
        if usage_path.exists()
        else "(No usage guide yet.)"
    )

    contract_text = ctx.contract.model_dump_json(indent=2) if ctx.contract else "(no contract)"
    environment_id = ctx.contract.environment_id if ctx.contract else "(unknown)"
    code_text = "\n\n".join(
        f"### {path}\n{content}" for path, content in sorted(ctx.production_code_snapshot.items())
    )
    idea_block = f"=== ORIGINAL USER REQUEST ===\n{ctx.idea}\n\n" if ctx.idea else ""
    # The final ticket is when the application is functionally complete — only then does the usage guide
    # for the compiled/deployed release get authored (signalled to the prompt as a data flag).
    final_flag = "true" if ctx.is_final_ticket else "false"
    user_content = (
        f"{idea_block}"
        f"=== TARGET ENVIRONMENT ID ===\n{environment_id}\n\n"
        f"=== FINAL ITERATION ===\n{final_flag}\n\n"
        f"=== COMPLETED TASK ===\n{ctx.pr_description}\n\n"
        f"=== TECHLEAD CONTRACT ===\n{contract_text}\n\n"
        f"=== PRODUCTION CODE SNAPSHOT ===\n{code_text}\n\n"
        f"=== PREVIOUS ARCHITECTURE DOCUMENT ===\n{previous_adr}\n\n"
        f"=== PREVIOUS README ===\n{previous_readme}\n\n"
        f"=== PREVIOUS CHANGELOG ===\n{previous_changelog}\n\n"
        f"=== PREVIOUS USAGE GUIDE ===\n{previous_usage}"
    )

    result, raw_response = await run_structured_llm(
        "techwriter",
        DocumentationUpdate,
        [
            {"role": "system", "content": get_system_prompt_with_platforms("techwriter")},
            {"role": "user", "content": user_content},
        ],
    )
    log_token_usage(ctx.telemetry, "Technical Writer", raw_response, TECHWRITER_MODEL)

    # LLM-authored documents — full-file cumulative rewrites.
    adr_path.parent.mkdir(parents=True, exist_ok=True)
    adr_path.write_text(result.architecture_document, encoding="utf-8")
    readme_path.write_text(result.readme, encoding="utf-8")
    changelog_path.write_text(result.changelog, encoding="utf-8")
    staged = ["docs/architecture_state.md", "README.md", "CHANGELOG.md"]

    # Usage guide for the finished/deployable application — authored ONLY on the batch's final ticket.
    if ctx.is_final_ticket and result.usage_guide.strip():
        usage_path.write_text(result.usage_guide, encoding="utf-8")
        staged.append("docs/USAGE.md")

    # LICENSE — engine-curated literal, written deterministically and ONLY on the first task (idempotent:
    # never regenerated, so an existing/edited LICENSE is preserved). No LLM → no RECITATION risk.
    if not license_path.exists():
        license_path.write_text(render_apache_license(), encoding="utf-8")
        staged.append("LICENSE")

    # Stage so finalize_transaction's atomic success commit includes the documentation.
    subprocess.run(  # nosec B603 B607 — fixed git argv, no shell
        ["git", "add", *staged], cwd=str(repo_dir), check=True,
    )
    log.info(f"   [ARTIFACT] Technical Writer updated and staged: {', '.join(staged)}\n")
