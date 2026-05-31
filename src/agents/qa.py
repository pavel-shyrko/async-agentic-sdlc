import os
import sys
import asyncio
from pathlib import Path

from src.core.observability import log, log_token_usage
from src.core.config import instructor_client, QA_MODEL
from src.core.models import QATestSuite, GlobalPipelineContext
from src.core.prompts import get_system_prompt, get_skill
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

    qa_raw = get_system_prompt("qa")
    qa_system_prompt, user_template = qa_raw.split("\n---\n", 1)
    qa_system_prompt += "\n\n" + get_skill("engineering_guide")

    shared_rules = get_skill("strict_validation").format(
        strict_type_validation_rules=ctx.contract.strict_type_validation_rules
    )
    feedback = f"\n\nPrevious failure feedback to address:\n{error_trace}" if error_trace else ""

    def _build_prompt(module_dot: str) -> str:
        return user_template.format(
            module_dot=module_dot,
            function_signatures=ctx.contract.function_signatures,
            shared_rules=shared_rules,
            feedback=feedback,
        )

    @with_api_retry(max_retries=3, agent_name="QA Agent")
    async def _invoke_llm(prompt: str) -> tuple:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: instructor_client.chat.completions.create_with_completion(
                model=model_name,
                response_model=QATestSuite,
                messages=[
                    {"role": "system", "content": qa_system_prompt},
                    {"role": "user", "content": prompt}
                ]
            )
        )

    async def _generate(module_file: str) -> tuple[str, str, object]:
        slug = module_file.removesuffix(".py").replace("/", "_").replace("\\", "_")
        module_dot = module_file.removesuffix(".py").replace("/", ".").replace("\\", ".")
        test_path = tests_dir / f"test_{slug}.py"
        suite, raw_response = await _invoke_llm(_build_prompt(module_dot))
        return str(test_path), suite.test_code, raw_response

    target_modules = [m for m in ctx.contract.files_to_modify if not m.endswith("__init__.py")]

    results = await asyncio.gather(*[_generate(m) for m in target_modules])

    for test_path, code, raw_response in results:
        log_token_usage("QA Agent", raw_response)
        with open(test_path, "w", encoding="utf-8") as f:
            f.write(code)

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
