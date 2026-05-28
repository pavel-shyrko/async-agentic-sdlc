import os
import sys
import asyncio
from pathlib import Path

from src.core.observability import log, log_token_usage
from src.core.config import instructor_client, QA_MODEL
from src.core.models import QATestSuite, GlobalPipelineContext
from src.utils.api_retry import with_api_retry
from src.utils.git_helpers import init_sandbox_git, get_pipeline_snapshot_files

async def run_qa_agent_node(ctx: GlobalPipelineContext, error_trace: str = "") -> None:
    model_name = QA_MODEL
    log.info(f"🔶 [ROLE] QA Agent | [MODEL] {model_name}")

    if not ctx.contract or not ctx.contract.files_to_modify:
        log.error("🚨 CRITICAL: Cannot generate tests without a locked Architecture Contract.")
        sys.exit(1)

    await init_sandbox_git(str(ctx.workspace_paths.tests_dir), ctx.base_branch)
    tests_dir = ctx.workspace_paths.tests_dir

    shared_rules = (
        f"Strict validation rules to enforce: {ctx.contract.strict_type_validation_rules}\n"
        f"CRITICAL RULE: The generated test suite must be completely deterministic. You are STRICTLY FORBIDDEN from wrapping boundary tests or type validation checks in try-except blocks, pass statements, or conditional if-else assertions. If a type or value is invalid according to the contract, use self.assertRaises() exclusively."
    )
    feedback = f"\n\nPrevious failure feedback to address:\n{error_trace}" if error_trace else ""

    def _build_prompt(module_dot: str) -> str:
        return (
            f"You are a QA Agent. Write a comprehensive, robust Python unittest suite that covers ONLY the module '{module_dot}'.\n"
            f"Import the module under test exactly via its dotted path (e.g. `import {module_dot}` or `from {module_dot} import ...`).\n"
            f"Relevant contract function signatures (test only what belongs to '{module_dot}'): {ctx.contract.function_signatures}\n"
            f"{shared_rules}{feedback}"
        )

    @with_api_retry(max_retries=3, agent_name="QA Agent")
    async def _invoke_llm(prompt: str) -> tuple:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: instructor_client.chat.completions.create_with_completion(
                model=model_name,
                response_model=QATestSuite,
                messages=[
                    {"role": "system", "content": "You are an automated QA engineer producing pure Python unittest files. No markdown, no commentary. CRITICAL: Do not use exact string matching or assertRaisesRegex for exception testing unless explicitly demanded by the contract. Use assertRaises(<ExceptionType>) to verify exception types without binding to brittle error messages."},
                    {"role": "user", "content": prompt}
                ]
            )
        )

    async def _generate(module_file: str) -> tuple[str, str, object]:
        # Unique flat test name derived from the full module path — no collisions across packages.
        slug = module_file.removesuffix(".py").replace("/", "_").replace("\\", "_")
        module_dot = module_file.removesuffix(".py").replace("/", ".").replace("\\", ".")
        test_path = tests_dir / f"test_{slug}.py"
        suite, raw_response = await _invoke_llm(_build_prompt(module_dot))
        return str(test_path), suite.test_code, raw_response

    # Facade modules (__init__.py) only re-export package members and carry no own logic —
    # testing them in isolation explodes into duplicate suites. Drop them from fan-out.
    target_modules = [m for m in ctx.contract.files_to_modify if not m.endswith("__init__.py")]

    # Independent modules have no generation ordering — fan out concurrently.
    results = await asyncio.gather(*[_generate(m) for m in target_modules])

    for test_path, code, raw_response in results:
        log_token_usage("QA Agent", raw_response)
        with open(test_path, "w", encoding="utf-8") as f:
            f.write(code)

    # Cumulative Git Anchor delta against the base branch.
    tests_dir_str = str(tests_dir)
    changed_files = await get_pipeline_snapshot_files(tests_dir_str, ctx.base_branch)

    parts = []
    for rel_path in changed_files:
        abs_path = Path(tests_dir_str) / rel_path
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
