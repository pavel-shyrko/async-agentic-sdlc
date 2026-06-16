import os
import re
import ast
import sys
from pathlib import Path

from src.shared.core.observability import log, log_token_usage
from src.shared.core.config import QA_MODEL
from src.shared.core.models import QATestSuite, GlobalPipelineContext
from src.shared.core.prompts import get_system_prompt_sections, build_agent_context, generate_repo_map
from src.shared.utils.llm import run_structured_llm
from src.shared.utils.git_helpers import get_git_root, get_pipeline_snapshot_files

# Edge markdown fences the model occasionally wraps a code field in (belt-and-braces; the
# QATestSuite validator already strips these at construction).
_FENCE_RE = (
    (re.compile(r"^```python\s*", re.IGNORECASE), ""),
    (re.compile(r"^```\s*"), ""),
    (re.compile(r"\s*```$"), ""),
)


def _strip_fences(code: str) -> str:
    for pattern, repl in _FENCE_RE:
        code = pattern.sub(repl, code)
    return code.strip()


def _dispose_zombie_tests(tests_dir: Path, names: set[str]) -> None:
    """Mechanically delete Reviewer-flagged zombie test files, strictly contained within ``tests_dir``.

    A zombie test targets a production module the TechLead intentionally removed/renamed, so it can
    never collect. The Reviewer (not the orchestrator) decides disposal; this only executes it. Every
    path is resolved and verified to live inside ``tests_dir`` and match ``test_*.py`` before unlink —
    rejecting traversal (``..``, absolute escapes) so a hallucinated path can never delete outside the
    suite.
    """
    root = tests_dir.resolve()
    for name in names:
        if not name or not name.strip():
            continue
        candidate = (tests_dir / name).resolve()
        if not candidate.is_relative_to(root):
            log.warning(f"🛑 Zombie-test disposal rejected (escapes tests dir): {name!r}")
            continue
        if not candidate.name.startswith("test_") or candidate.suffix != ".py":
            log.warning(f"🛑 Zombie-test disposal rejected (not a test_*.py file): {name!r}")
            continue
        candidate.unlink(missing_ok=True)
        log.info(f"🗑️  Zombie test disposed: {candidate.name}")


def _is_main_guard(node: ast.stmt) -> bool:
    """True for an ``if __name__ == "__main__":`` block."""
    if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
        return False
    cmp = node.test
    left_is_name = isinstance(cmp.left, ast.Name) and cmp.left.id == "__name__"
    right_is_main = (
        len(cmp.comparators) == 1
        and isinstance(cmp.comparators[0], ast.Constant)
        and cmp.comparators[0].value == "__main__"
    )
    return left_is_name and right_is_main


def _assemble_suite(existing_source: str, suite: QATestSuite) -> str:
    """Deterministically prune obsolete cases from *existing_source* and append the model's deltas.

    Structured maintenance: the model returns only ``new_imports`` / ``new_test_code`` and the
    ``obsolete_test_names`` to drop. We parse the existing file, remove the named top-level defs,
    dedupe imports, relocate any ``__main__`` guard to the very end, and join with blank-line
    separators so nothing fuses into a SyntaxError. Always rewritten in place by the caller.
    """
    new_imports = _strip_fences(suite.new_imports)
    new_test_code = _strip_fences(suite.new_test_code)
    obsolete = set(suite.obsolete_test_names)

    pruned, main_guard = "", ""
    if existing_source.strip():
        try:
            tree = ast.parse(existing_source)
        except SyntaxError:
            # On-disk file is malformed — don't crash or silently drop prior tests. Append, no prune.
            log.warning("🛡️ QA: existing test file is not parseable; appending new tests without AST pruning.")
            segments = [existing_source.strip(), new_imports, new_test_code]
            return "\n\n\n".join(s for s in segments if s.strip()) + "\n"

        # Relocate the runner guard so newly appended classes are defined BEFORE unittest.main().
        guard_nodes = [n for n in tree.body if _is_main_guard(n)]
        if guard_nodes:
            main_guard = "\n\n\n".join(ast.unparse(n) for n in guard_nodes)
        # Drop obsolete top-level test defs and the guard (re-appended last).
        tree.body = [
            n for n in tree.body
            if not _is_main_guard(n)
            and not (isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in obsolete)
        ]
        pruned = ast.unparse(tree)

    # Strict import dedup: only keep new_imports lines absent from the pruned body.
    existing_lines = {ln.strip() for ln in pruned.splitlines() if ln.strip()}
    deduped_imports = "\n".join(
        ln for ln in new_imports.splitlines() if ln.strip() and ln.strip() not in existing_lines
    )

    # Guard LAST so it sits below every test definition; blank-line separators prevent fusion.
    segments = [deduped_imports, pruned, new_test_code, main_guard]
    return "\n\n\n".join(s for s in segments if s.strip()) + "\n"


async def run_qa_agent_node(ctx: GlobalPipelineContext, error_trace: str = "") -> None:
    model_name = QA_MODEL
    log.info(f"🔶 [ROLE] QA Agent | [MODEL] {model_name}")

    if not ctx.contract or not ctx.contract.files_to_modify:
        log.error("🚨 CRITICAL: Cannot generate tests without a locked TechLead Contract.")
        sys.exit(1)

    # The clone is already a git repo on feat/ticket-<id>; QA only writes test files (no init/commit).
    tests_dir = ctx.workspace_paths.tests_dir

    qa_system_prompt, user_template = get_system_prompt_sections("qa")
    qa_system_prompt += "\n\n" + await build_agent_context("qa", ctx, is_retry=bool(error_trace))

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

    def _build_prompt(module_dot: str) -> str:
        return user_template.format(
            module_dot=module_dot,
            function_signatures=ctx.contract.function_signatures,
            feedback=feedback,
        )

    async def _generate(module_file: str) -> tuple[Path, str, object, object]:
        slug = module_file.removesuffix(".py").replace("/", "_").replace("\\", "_")
        module_dot = module_file.removesuffix(".py").replace("/", ".").replace("\\", ".")
        test_path = tests_dir / f"test_{slug}.py"
        # Surface the current on-disk suite so the agent returns DELTAS (new code + obsolete names)
        # instead of re-emitting the whole file. Read once; reused for prompt and AST assembly.
        user_prompt = _build_prompt(module_dot)
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

    target_modules = [m for m in ctx.contract.files_to_modify if not m.endswith("__init__.py")]

    results = []
    for m in target_modules:
        results.append(await _generate(m))

    written_paths = []
    assembled = []
    for test_path, existing_source, suite, raw_response in results:
        log_token_usage(ctx, "QA Agent", raw_response, QA_MODEL)
        # Structured maintenance: prune obsolete cases from disk + append the model's new deltas.
        final_code = _assemble_suite(existing_source, suite)
        with open(test_path, "w", encoding="utf-8") as f:
            f.write(final_code)
        written_paths.append(str(test_path))
        assembled.append(final_code)

    # Reviewer-routed zombie disposal: delete whole test files whose target module was intentionally
    # removed/renamed (they can never collect). Aggregated across per-module suites, deduped, guarded.
    _dispose_zombie_tests(tests_dir, {f for _, _, suite, _ in results for f in suite.files_to_delete})

    # Snapshot the test delta from the real git root, scoped to the tests subtree.
    repo_root = Path(await get_git_root(str(tests_dir)))
    subdir = tests_dir.resolve().relative_to(repo_root.resolve()).as_posix()
    changed_files = await get_pipeline_snapshot_files(str(repo_root), ctx.base_branch, subdir=subdir)

    parts = []
    for rel_path in changed_files:
        abs_path = repo_root / rel_path
        if abs_path.exists():
            parts.append(f"=== FILE: {rel_path} ===\n{abs_path.read_text(encoding='utf-8')}")
        else:
            parts.append(f"=== FILE: {rel_path} (DELETED) ===")

    fallback = "\n\n".join(assembled)
    ctx.test_code_snapshot = "\n\n".join(parts) if parts else fallback

    generated = written_paths
    log.info("   [THOUGHT] Generated deterministic per-module unittest suites targeting strict type enforcement and contract safety.")
    log.info(f"   [ARTIFACT] Instantiated {len(generated)} test file(s): {generated}\n")
    log.debug(f"QA Agent generated test files: {generated}")
