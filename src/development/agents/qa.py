import sys
import time
from pathlib import Path

from src.shared.core.observability import log
from src.shared.core.config import QA_MODEL, QA_EFFORT, QA_CLI_TIMEOUT, QA_CLI_IDLE_TIMEOUT
from src.shared.core.models import GlobalPipelineContext
from src.shared.core.environments import (
    get_qa_profile, is_testable_source, derive_test_target, env_language,
    is_test_file, resolve_test_project_dir, test_manifest_suffix,
)
from src.shared.core.prompts import get_system_prompt, build_agent_context, generate_repo_map
from src.shared.utils.subprocess_helpers import run_claude_cli
from src.shared.utils.git_helpers import get_git_root, get_pipeline_snapshot_files
from src.development.gates import run_format_pass

# Instructional preamble prepended on a correction cycle (mirrors Developer's _RETRY_PREAMBLE).
_RETRY_PREAMBLE = (
    "⚠️ MANDATORY CORRECTION (overrides the Contract below for this turn) — your previous "
    "attempt was REJECTED. You MUST resolve the following before doing anything else:\n"
)


def _test_name_predicate(environment_id: str):
    return lambda n: is_test_file(environment_id, n)


def _dispose_zombie_tests(root_dir: Path, names: set[str], name_ok) -> None:
    """Delete Reviewer-flagged zombie test files, strictly contained within root_dir."""
    root = root_dir.resolve()
    for name in names:
        if not name or not name.strip():
            continue
        candidate = (root_dir / name).resolve()
        if not candidate.is_relative_to(root):
            log.warning(f"🛑 Zombie-test disposal rejected (escapes root): {name!r}")
            continue
        if not name_ok(candidate.name):
            log.warning(f"🛑 Zombie-test disposal rejected (not a recognized test file): {name!r}")
            continue
        candidate.unlink(missing_ok=True)
        log.info(f"🗑️  Zombie test disposed: {candidate.name}")


def _environment_profile_block(env_id: str, profile: dict) -> str:
    return (
        "\n\n=== TARGET ENVIRONMENT PROFILE ===\n"
        f"environment_id: {env_id}\n"
        f"language: {env_language(env_id)}\n"
        f"test framework: {profile['framework_label']}\n"
        f"layout: {profile['layout']}\n"
    )


async def run_qa_agent_node(ctx: GlobalPipelineContext, error_trace: str = "") -> None:
    log.info(f"🔶 [ROLE] QA Agent | [PROVIDER] Claude | [MODEL] {QA_MODEL} | [EFFORT] {QA_EFFORT}")

    if not ctx.contract or not ctx.contract.files_to_modify:
        log.error("🚨 CRITICAL: Cannot generate tests without a locked TechLead Contract.")
        sys.exit(1)

    env_id = ctx.contract.environment_id
    profile = get_qa_profile(env_id)
    repo_dir = ctx.workspace_paths.repo_dir

    # Test placement by layout (registry-driven — same logic as before).
    if profile["layout"] == "separate":
        _wd = ctx.contract.working_directory
        test_root = (repo_dir / _wd if _wd else repo_dir) / profile["test_root"]
    elif profile["layout"] == "project":
        proj_dir = resolve_test_project_dir(ctx.contract.files_to_modify, repo_dir, env_id)
        if not proj_dir:
            log.warning(
                "🔶 QA: no test-project manifest in the contract's files_to_modify — placing tests "
                "in the fallback repo/tests dir (the test project should be contracted; see the "
                "stack's domain skill)."
            )
        elif not any(
            f.rsplit("/", 1)[-1].endswith(test_manifest_suffix(env_id) or "\0")
            for f in ctx.contract.files_to_modify
        ):
            log.info(f"🔹 QA: test project resolved from the existing clone → {proj_dir}.")
        test_root = repo_dir / (proj_dir or "tests")
    else:
        test_root = repo_dir
    zombie_root = test_root
    test_name_ok = _test_name_predicate(env_id)

    # Reviewer-directed zombie disposal (deterministic before Claude runs).
    if ctx.review_report and ctx.review_report.zombie_tests_to_delete:
        zombies = set(ctx.review_report.zombie_tests_to_delete)
        log.info(f"🧹 Reviewer-directed structured test pruning triggered for: {zombies}")
        _dispose_zombie_tests(zombie_root, zombies, name_ok=test_name_ok)

    # Build prompt — system rules + all context sections.
    prompt = get_system_prompt("qa")
    prompt += "\n\n" + await build_agent_context("qa", ctx, is_retry=bool(error_trace))

    if ctx.contract.shared_context:
        prompt += "\n\n=== PROJECT CONTEXT ===\n" + ctx.contract.shared_context

    prompt += _environment_profile_block(env_id, profile)

    if not ctx.repository_map:
        ctx.repository_map = generate_repo_map(ctx.workspace_paths.repo_dir)
    prompt += f"\n\n=== EXISTING REPOSITORY TOPOLOGY ===\n{ctx.repository_map}\n"

    prompt += (
        "\n\n=== CONTRACT FILES (authoritative module map) ===\n"
        + "\n".join(ctx.contract.files_to_modify)
    )

    if ctx.contract.acceptance_examples:
        examples = "\n".join(
            f"- input: {e.input} | expected: {e.expected or '—'} | raises: {e.raises or '—'}"
            for e in ctx.contract.acceptance_examples
        )
        prompt += "\n\n=== ACCEPTANCE EXAMPLES (authoritative expected behavior) ===\n" + examples

    if ctx.contract.topology_contract:
        topo = "\n".join(
            f"{n.file_path} | exports: {', '.join(n.exports)} | depends_on: {', '.join(n.depends_on)}"
            for n in ctx.contract.topology_contract
        )
        prompt += "\n\n=== TOPOLOGY CONTRACT (language-neutral dependency graph) ===\n" + topo

    # Claude CLI reads source files directly via the Read tool — no need to embed content.
    # Inject only the paths so Claude knows WHERE to look.
    if ctx.production_code_snapshot:
        paths_only = "\n".join(ctx.production_code_snapshot.keys())
        prompt += f"\n\n=== PRODUCTION SOURCE FILES (read these with the Read tool) ===\n{paths_only}"

    # Compute target test file paths and inject as DATA (instructions are in qa.md).
    target_modules = [m for m in ctx.contract.files_to_modify if is_testable_source(env_id, m)]
    test_file_map: dict[str, Path] = {}
    for module_file in target_modules:
        rel_test_path, _ = derive_test_target(env_id, module_file)
        test_path = test_root / rel_test_path
        test_path.parent.mkdir(parents=True, exist_ok=True)
        test_file_map[module_file] = test_path

    if test_file_map:
        mappings = "\n".join(
            f"  {module_file}  →  {test_path.relative_to(repo_dir)}"
            for module_file, test_path in test_file_map.items()
        )
        prompt += f"\n\n=== TEST FILES TO WRITE ===\n{mappings}"

    # On a rework cycle, tell Claude which test files already exist (it will Read them directly).
    if error_trace and test_file_map:
        existing = [
            str(test_path.relative_to(repo_dir))
            for test_path in test_file_map.values()
            if test_path.exists()
        ]
        if existing:
            prompt += f"\n\n=== EXISTING TEST FILES (read these to understand what to fix) ===\n" + "\n".join(existing)

    # Correction header goes FIRST so it is highest-salience on a reroute.
    if error_trace:
        prompt = _RETRY_PREAMBLE + f"{error_trace}\n" + "=" * 60 + "\n\n" + prompt

    # Source files + any existing test files (for reading context on rework).
    code_files = [str(repo_dir / f) for f in ctx.contract.files_to_modify]
    for test_path in test_file_map.values():
        if test_path.exists():
            code_files.append(str(test_path))

    _cli_start = time.perf_counter()
    returncode, usage = await run_claude_cli(
        prompt, code_files, allowed_root=str(repo_dir), model=QA_MODEL, effort=QA_EFFORT,
        timeout=QA_CLI_TIMEOUT, idle_timeout=QA_CLI_IDLE_TIMEOUT,
    )
    _cli_elapsed = time.perf_counter() - _cli_start

    if usage:
        ctx.telemetry.record(
            "QA Agent", usage["input_tokens"], usage["output_tokens"], usage["cost_usd"],
            provider="claude",
            cache_read_tokens=usage["cache_read_tokens"],
            cache_write_tokens=usage["cache_write_tokens"],
            plane="development",
            duration_seconds=_cli_elapsed,
        )
        log.info(
            f"   [TOKENS] QA Agent | Input(fresh): {usage['input_tokens']} | "
            f"Cache-write: {usage['cache_write_tokens']} | Cache-read: {usage['cache_read_tokens']} | "
            f"Output: {usage['output_tokens']} | "
            f"Budgeted: {usage['input_tokens'] + usage['output_tokens']} | "
            f"Cost: ${usage['cost_usd']:.4f} | Cumulative: {ctx.telemetry.total_tokens}t / "
            f"${ctx.telemetry.total_cost_usd:.4f}"
        )
    else:
        log.info("   [TOKENS] QA Agent | usage unavailable — reconcile out-of-band via ccusage")

    # Format pass: strip unused imports (hard compile error in some languages); non-fatal.
    written_paths = [str(p) for p in test_file_map.values() if p.exists()]
    if written_paths:
        await run_format_pass(env_id, str(repo_dir))

    # Snapshot from real git delta so the Reviewer sees exactly what was written/deleted.
    repo_root = Path(await get_git_root(str(repo_dir)))
    changed_files = await get_pipeline_snapshot_files(str(repo_root), ctx.base_branch)

    parts = []
    for rel_path in changed_files:
        if not test_name_ok(rel_path.rsplit("/", 1)[-1]):
            continue
        abs_path = repo_root / rel_path
        if abs_path.exists():
            parts.append(f"=== FILE: {rel_path} ===\n{abs_path.read_text(encoding='utf-8')}")
        else:
            parts.append(f"=== FILE: {rel_path} (DELETED) ===")

    # Fallback: content of written files when git diff is empty (first cycle, clean tree).
    fallback = "\n\n".join(
        p.read_text(encoding="utf-8") for p in test_file_map.values() if p.exists()
    )
    ctx.test_code_snapshot = "\n\n".join(parts) if parts else fallback

    log.info(f"   [THOUGHT] Generated test suites via direct file writes (Read + Write tools).")
    log.info(f"   [ARTIFACT] Targeted {len(test_file_map)} test file(s): {written_paths}\n")
