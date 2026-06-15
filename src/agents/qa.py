import os
import sys
from pathlib import Path

from src.core.observability import log, log_token_usage
from src.core.config import QA_MODEL
from src.core.models import QATestSuite, GlobalPipelineContext
from src.core.prompts import get_system_prompt_sections, build_agent_context, generate_repo_map
from src.utils.llm import run_structured_llm
from src.utils.git_helpers import get_git_root, get_pipeline_snapshot_files

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

    async def _generate(module_file: str) -> tuple[str, str, object]:
        slug = module_file.removesuffix(".py").replace("/", "_").replace("\\", "_")
        module_dot = module_file.removesuffix(".py").replace("/", ".").replace("\\", ".")
        test_path = tests_dir / f"test_{slug}.py"
        # Read-Modify-Write: surface the current on-disk suite so the agent merges
        # instead of regenerating from scratch (appended post-format; test code
        # contains literal braces that would break str.format).
        user_prompt = _build_prompt(module_dot)
        if test_path.exists():
            existing_test_code = test_path.read_text(encoding="utf-8")
            user_prompt += f"\n\n=== EXISTING TEST SUITE ===\n{existing_test_code}"
        suite, raw_response = await run_structured_llm(
            "qa",
            QATestSuite,
            [
                {"role": "system", "content": qa_system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return str(test_path), suite.test_code, raw_response

    target_modules = [m for m in ctx.contract.files_to_modify if not m.endswith("__init__.py")]

    results = []
    for m in target_modules:
        results.append(await _generate(m))

    for test_path, code, raw_response in results:
        log_token_usage(ctx, "QA Agent", raw_response, QA_MODEL)
        with open(test_path, "w", encoding="utf-8") as f:
            f.write(code)

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

    fallback = "\n\n".join(code for _, code, _ in results)
    ctx.test_code_snapshot = "\n\n".join(parts) if parts else fallback

    generated = [path for path, _, _ in results]
    log.info("   [THOUGHT] Generated deterministic per-module unittest suites targeting strict type enforcement and contract safety.")
    log.info(f"   [ARTIFACT] Instantiated {len(generated)} test file(s): {generated}\n")
    log.debug(f"QA Agent generated test files: {generated}")
