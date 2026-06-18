import re
import sys
from pathlib import Path

from src.shared.core.observability import log, log_token_usage
from src.shared.core.config import QA_MODEL
from src.shared.core.models import QATestSuite, GlobalPipelineContext
from src.shared.core.environments import get_qa_profile, is_testable_source, derive_test_target, env_language, is_test_file
from src.shared.core.prompts import get_system_prompt_sections, build_agent_context, generate_repo_map
from src.shared.utils.llm import run_structured_llm
from src.shared.utils.git_helpers import get_git_root, get_pipeline_snapshot_files
from src.executor.nodes.gates import run_format_pass

# Edge markdown fences the model occasionally wraps a code field in (belt-and-braces; the
# QATestSuite validator already strips these at construction). Language-neutral: the opening
# fence may carry ANY language tag (```python, ```go, ```csharp, ```typescript) or none.
_FENCE_RE = (
    (re.compile(r"^```[A-Za-z0-9_+-]*\s*"), ""),   # opening fence + optional language tag
    (re.compile(r"\s*```$"), ""),                   # closing fence
)


def _strip_fences(code: str) -> str:
    for pattern, repl in _FENCE_RE:
        code = pattern.sub(repl, code)
    return code.strip()


def _test_name_predicate(environment_id: str):
    """Return a predicate matching a basename to the env's test-file naming convention.

    Thin wrapper over the shared ``is_test_file`` SSOT so QA and the production-snapshot filter agree.
    """
    return lambda n: is_test_file(environment_id, n)


def _dispose_zombie_tests(root_dir: Path, names: set[str], name_ok) -> None:
    """Mechanically delete Reviewer-flagged zombie test files, strictly contained within ``root_dir``.

    A zombie test targets a production module the TechLead intentionally removed/renamed, so it can
    never collect. The Reviewer (not the orchestrator) decides disposal; this only executes it. Every
    path is resolved and verified to live inside ``root_dir`` and match the language's test-file naming
    convention (``name_ok`` — the env's SSOT ``is_test_file`` predicate, supplied by the caller) before
    unlink — rejecting traversal (``..``, absolute escapes) so a hallucinated path can never delete
    outside the tree. ``root_dir`` is the tests dir for a separate layout (python) or the repo root for
    a colocated layout (go/node/.NET).
    """
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


def _assemble_suite(existing_source: str, suite: QATestSuite) -> str:
    """Whole-file assembly, identical for every language (no language-specific parser).

    The QA system prompt + per-language skill instruct the model to return the COMPLETE test file
    (header in ``new_imports``, every test in ``new_test_code``, ``overwrite_existing=true``), so we
    treat that as the authoritative content and write it verbatim. Correct packaging/namespacing/
    placement is the agent's responsibility (driven by the skills + the production snapshot); a wrong
    package is caught by the compile gate and routed back to QA, never silently rewritten here.

    Safety net: if the model returns nothing new and an existing file is present (and overwrite was not
    requested), keep the existing file rather than truncating it — an empty delta must not clobber a
    good suite.
    """
    new_imports = _strip_fences(suite.new_imports)
    new_test_code = _strip_fences(suite.new_test_code)
    overwrite = getattr(suite, "overwrite_existing", False)

    body = "\n\n".join(s for s in (new_imports, new_test_code) if s.strip())
    if not body.strip() and existing_source.strip() and not overwrite:
        return existing_source if existing_source.endswith("\n") else existing_source + "\n"
    return body + "\n"


def _environment_profile_block(env_id: str, profile: dict) -> str:
    """The `=== TARGET ENVIRONMENT PROFILE ===` block — PURE registry DATA, no instructions.

    What to do with these values (native framework only, placement by layout, assembly contract) lives
    in qa.md / the per-language skill, which reference this block by name. Keeping the block
    instruction-free is the language-neutral, single-source-of-truth boundary: code assembles data,
    prompts carry behavior.
    """
    return (
        "\n\n=== TARGET ENVIRONMENT PROFILE ===\n"
        f"environment_id: {env_id}\n"
        f"language: {env_language(env_id)}\n"
        f"test framework: {profile['framework_label']}\n"
        f"layout: {profile['layout']}\n"
    )


async def run_qa_agent_node(ctx: GlobalPipelineContext, error_trace: str = "") -> None:
    model_name = QA_MODEL
    log.info(f"🔶 [ROLE] QA Agent | [MODEL] {model_name}")

    if not ctx.contract or not ctx.contract.files_to_modify:
        log.error("🚨 CRITICAL: Cannot generate tests without a locked TechLead Contract.")
        sys.exit(1)

    # Environment-aware test generation: the ticket's environment_id (SSOT) drives test file
    # extension, placement, framework idioms, and which contract files are even testable source.
    env_id = ctx.contract.environment_id
    profile = get_qa_profile(env_id)
    repo_dir = ctx.workspace_paths.repo_dir
    # Colocated stacks (go/node/.NET) write tests next to source under the repo root; the separate
    # layout (python) keeps them under repo/<test_root> (the profile owns the convention). The zombie
    # disposer is rooted accordingly.
    test_root = (repo_dir / profile["test_root"]) if profile["layout"] == "separate" else repo_dir
    zombie_root = test_root
    test_name_ok = _test_name_predicate(env_id)

    # Structured zombie disposal: the Reviewer names obsolete test files directly (typed array),
    # so we delete them deterministically here — no log parsing, no LLM round-trip. Reuses the
    # sandbox-guarded disposer; safe to run before the per-module generation loop.
    if ctx.review_report and ctx.review_report.zombie_tests_to_delete:
        zombies = set(ctx.review_report.zombie_tests_to_delete)
        log.info(f"🧹 Reviewer-directed structured test pruning triggered for: {zombies}")
        _dispose_zombie_tests(zombie_root, zombies, name_ok=test_name_ok)

    qa_system_prompt, user_template = get_system_prompt_sections("qa")
    qa_system_prompt += "\n\n" + await build_agent_context("qa", ctx, is_retry=bool(error_trace))

    # Project intent as REFERENCE so the tester understands WHAT the system is for; the contract
    # files / production snapshot remain the authoritative source for what to assert. Empty → omitted.
    if ctx.contract.shared_context:
        qa_system_prompt += "\n\n=== PROJECT CONTEXT (reference) ===\n" + ctx.contract.shared_context

    qa_system_prompt += _environment_profile_block(env_id, profile)

    if not ctx.repository_map:
        ctx.repository_map = generate_repo_map(ctx.workspace_paths.repo_dir)
    qa_system_prompt += f"\n\n=== EXISTING REPOSITORY TOPOLOGY ===\n{ctx.repository_map}\n"

    # Authoritative module map: every imported symbol must come from one of these contract paths.
    qa_system_prompt += (
        "\n\n=== CONTRACT FILES (authoritative module map) ===\n"
        + "\n".join(ctx.contract.files_to_modify)
    )

    # Language-neutral dependency graph (SSOT). QA translates depends_on links into real imports.
    if ctx.contract.topology_contract:
        topo = "\n".join(
            f"{n.file_path} | exports: {', '.join(n.exports)} | depends_on: {', '.join(n.depends_on)}"
            for n in ctx.contract.topology_contract
        )
        qa_system_prompt += "\n\n=== TOPOLOGY CONTRACT (language-neutral dependency graph) ===\n" + topo

    # When production code already exists (any regeneration after the Developer has run) it is the
    # source of truth for symbol locations — this is what stops the import guessing that breaks
    # test collection and triggers the QA↔Developer loop.
    if ctx.production_code_snapshot:
        snapshot = "\n\n".join(
            f"=== FILE: {path} ===\n{content}"
            for path, content in ctx.production_code_snapshot.items()
        )
        qa_system_prompt += f"\n\n=== PRODUCTION CODE SNAPSHOT (source of truth for imports) ===\n{snapshot}"

    if error_trace and ctx.test_code_snapshot:
        qa_system_prompt += f"\n\n=== PREVIOUS TEST SUITE STATE ===\n{ctx.test_code_snapshot}"

    feedback = f"\n\nPrevious failure feedback to address:\n{error_trace}" if error_trace else ""

    def _build_prompt(module_ref: str) -> str:
        return user_template.format(
            module_ref=module_ref,
            function_signatures=ctx.contract.function_signatures,
            feedback=feedback,
        )

    async def _generate(module_file: str) -> tuple[Path, str, object, object]:
        # environment_id decides the test file name, extension, and placement (colocated vs separate).
        rel_test_path, module_ref = derive_test_target(env_id, module_file)
        test_path = test_root / rel_test_path  # colocated → repo root; separate → repo/<test_root>
        test_path.parent.mkdir(parents=True, exist_ok=True)
        # Surface the current on-disk suite as the agent's WORKING DRAFT so it returns the complete
        # corrected file (preserve valid cases, fix flagged ones). Read once; reused for the empty-delta
        # safety net in _assemble_suite.
        user_prompt = _build_prompt(module_ref)
        existing_source = test_path.read_text(encoding="utf-8") if test_path.exists() else ""
        if existing_source:
            user_prompt += f"\n\n=== EXISTING TEST SUITE ===\n{existing_source}"
        suite, raw_response = await run_structured_llm(
            "qa",
            QATestSuite,
            [
                {"role": "system", "content": qa_system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return test_path, existing_source, suite, raw_response

    # Only real source files of the target stack get tests — never docs/config/package markers
    # (README.md, LICENSE, .gitignore, go.mod/go.sum, package.json, *.csproj, __init__.py, ...).
    target_modules = [m for m in ctx.contract.files_to_modify if is_testable_source(env_id, m)]

    results = []
    for m in target_modules:
        results.append(await _generate(m))

    written_paths = []
    assembled = []
    for test_path, existing_source, suite, raw_response in results:
        log_token_usage(ctx.telemetry, "QA Agent", raw_response, QA_MODEL)
        # One language-neutral assembly path: the model returns the complete file (header + tests);
        # correct package/namespace/placement is enforced by the skills + the compile-gate→QA loop,
        # not by any per-language post-processing here.
        final_code = _assemble_suite(existing_source, suite)
        with open(test_path, "w", encoding="utf-8") as f:
            f.write(final_code)
        written_paths.append(str(test_path))
        assembled.append(final_code)

    # Deterministic cleanup over the freshly written tests BEFORE snapshotting/reviewing: strips unused
    # imports (a HARD compile error in Go) so the generated suite doesn't bounce the compile gate and
    # burn a QA→Reviewer cycle. Non-fatal — a formatter hiccup never blocks the run. Runs before the
    # snapshot below so ctx.test_code_snapshot captures the cleaned files.
    if written_paths:
        await run_format_pass(env_id, str(repo_dir))

    # Reviewer-routed zombie disposal: delete whole test files whose target module was intentionally
    # removed/renamed (they can never collect). Aggregated across per-module suites, deduped, guarded.
    _dispose_zombie_tests(
        zombie_root, {f for _, _, suite, _ in results for f in suite.files_to_delete}, name_ok=test_name_ok
    )

    # Snapshot the test delta from the real git root, then keep only the stack's test files (works for
    # both colocated and separate layouts; captures additions and Reviewer-directed deletions).
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

    fallback = "\n\n".join(assembled)
    ctx.test_code_snapshot = "\n\n".join(parts) if parts else fallback

    generated = written_paths
    log.info(f"   [THOUGHT] Generated deterministic per-module {profile['framework_label']} suites targeting strict type enforcement and contract safety.")
    log.info(f"   [ARTIFACT] Instantiated {len(generated)} test file(s): {generated}\n")
    log.debug(f"QA Agent generated test files: {generated}")
