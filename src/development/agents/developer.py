from src.shared.core.observability import log
from src.shared.core.config import DEVELOPER_MODEL, DEVELOPER_EFFORT, DEVELOPER_CLI_TIMEOUT, DEVELOPER_CLI_IDLE_TIMEOUT
from src.shared.core.models import GlobalPipelineContext
from src.shared.core.prompts import get_system_prompt, build_agent_context
from src.shared.utils.subprocess_helpers import run_claude_cli

async def run_developer_node(
    ctx: GlobalPipelineContext, error_trace: str = "", focus_files: list[str] | None = None
) -> None:
    log.info(f"🟩 [ROLE] Developer Agent | [PROVIDER] Claude | [MODEL] {DEVELOPER_MODEL} | [EFFORT] {DEVELOPER_EFFORT}")

    repo_dir_path = ctx.workspace_paths.repo_dir
    repo_dir = str(repo_dir_path)

    prompt = get_system_prompt("developer").format(
        instruction=ctx.contract.instruction,
        core_libraries="\n".join(f"- {x}" for x in ctx.contract.core_libraries) or "- (none specified)",
        architectural_constraints="\n".join(f"- {x}" for x in ctx.contract.architectural_constraints) or "- (none specified)",
        function_signatures=ctx.contract.function_signatures,
        strict_type_validation_rules=ctx.contract.strict_type_validation_rules,
        code_dir=repo_dir,
    )
    prompt += "\n\n" + await build_agent_context(
        "developer", ctx, is_retry=bool(error_trace), topology_kwargs={"code_dir": repo_dir}
    )

    # Authoritative file placement (SSOT the TechLead already produced). The `developer_topology` skill
    # carries the RULE ("obey exact paths"); this block carries the DATA — the exact file_path for every
    # contracted node — so the Developer stops inventing layouts (e.g. nesting contracted root files
    # under src/). Mirrors the QA node's topology injection; rendered identically (file_path | exports |
    # depends_on). Placed at high salience right after the Contract Directives.
    if ctx.contract.topology_contract:
        topo = "\n".join(
            f"{n.file_path} | exports: {', '.join(n.exports)} | depends_on: {', '.join(n.depends_on)}"
            for n in ctx.contract.topology_contract
        )
        prompt += (
            "\n\n=== TOPOLOGY CONTRACT (authoritative file placement — write EXACTLY these paths, "
            "repo-root-relative; never add a `src/` or other parent prefix) ===\n" + topo
        )

    # Project intent as REFERENCE (subordinate to the Contract Directives above) so the Developer
    # understands WHAT it is building and does not fabricate goals — the raw ticket/blueprint never
    # reach this node. Omitted entirely when empty so no stray header pollutes the prompt.
    if ctx.contract.shared_context:
        prompt += (
            "\n\n=== PROJECT CONTEXT (reference only — the Contract Directives above are "
            f"authoritative) ===\n{ctx.contract.shared_context}"
        )

    # On a reroute the Developer is a FRESH Claude session — it has no memory of the prior correction.
    # A trailing footer loses to the strong system-prompt directives above it, so the correction is
    # PREPENDED as a mandatory, contract-overriding header: highest salience, read first.
    if error_trace:
        prompt = (
            "⚠️ MANDATORY CORRECTION (overrides the Contract below for this turn) — your previous "
            "attempt was REJECTED. You MUST resolve the following before doing anything else:\n"
            f"{error_trace}\n"
            + "=" * 60 + "\n\n"
            + prompt
        )

    # The clone is already a git repo on feat/ticket-<id>; agents only mutate the working tree.
    code_files = [str(repo_dir_path / f) for f in ctx.contract.files_to_modify]
    # Surface the exact files a reroute targets (e.g. out-of-scope files to delete) so the CLI focuses
    # the agent on them; they stay under allowed_root so _assert_within_root passes.
    if focus_files:
        code_files += [str(repo_dir_path / f) for f in focus_files]
    returncode, usage = await run_claude_cli(
        prompt, code_files, allowed_root=repo_dir, model=DEVELOPER_MODEL, effort=DEVELOPER_EFFORT,
        timeout=DEVELOPER_CLI_TIMEOUT, idle_timeout=DEVELOPER_CLI_IDLE_TIMEOUT,
    )

    if usage:
        ctx.telemetry.record(
            "Developer Agent", usage["input_tokens"], usage["output_tokens"], usage["cost_usd"],
            provider="claude",
            cache_read_tokens=usage["cache_read_tokens"],
            cache_write_tokens=usage["cache_write_tokens"],
        )
        log.info(
            f"   [TOKENS] Developer Agent | Input(fresh): {usage['input_tokens']} | "
            f"Cache-write: {usage['cache_write_tokens']} | Cache-read: {usage['cache_read_tokens']} | "
            f"Output: {usage['output_tokens']} | "
            f"Budgeted: {usage['input_tokens'] + usage['output_tokens']} | "
            f"Cost: ${usage['cost_usd']:.4f} | Cumulative: {ctx.telemetry.total_tokens}t / "
            f"${ctx.telemetry.total_cost_usd:.4f}"
        )
    else:
        log.info("   [TOKENS] Developer Agent | usage unavailable — reconcile out-of-band via ccusage")

    # The orchestrator's build_production_snapshot() captures the real working-tree delta after this
    # node returns; the Developer no longer self-reports the snapshot (which caused Reviewer desync).
    log.info(f"   [MUTATION] Developer node complete (Exit Code: {returncode}).\n")
