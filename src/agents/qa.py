import os
import sys
from pathlib import Path

from src.core.observability import log, log_token_usage
from src.core.config import QA_MODEL
from src.core.models import QATestSuite, GlobalPipelineContext
from src.core.prompts import get_system_prompt_sections, build_agent_context
from src.utils.llm import run_structured_llm
from src.utils.git_helpers import get_git_root, get_pipeline_snapshot_files

async def run_qa_agent_node(ctx: GlobalPipelineContext, error_trace: str = "") -> None:
    model_name = QA_MODEL
    log.info(f"🔶 [ROLE] QA Agent | [MODEL] {model_name}")

    if not ctx.contract or not ctx.contract.files_to_modify:
        log.error("🚨 CRITICAL: Cannot generate tests without a locked Architecture Contract.")
        sys.exit(1)

    # The clone is already a git repo on feat/ticket-<id>; QA only writes test files (no init/commit).
    tests_dir = ctx.workspace_paths.tests_dir

    qa_system_prompt, user_template = get_system_prompt_sections("qa")
    qa_system_prompt += "\n\n" + await build_agent_context("qa", ctx, is_retry=bool(error_trace))

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
        suite, raw_response = await run_structured_llm(
            "qa",
            QATestSuite,
            [
                {"role": "system", "content": qa_system_prompt},
                {"role": "user", "content": _build_prompt(module_dot)},
            ],
        )
        return str(test_path), suite.test_code, raw_response

    target_modules = [m for m in ctx.contract.files_to_modify if not m.endswith("__init__.py")]

    results = []
    for m in target_modules:
        results.append(await _generate(m))

    for test_path, code, raw_response in results:
        log_token_usage("QA Agent", raw_response)
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
