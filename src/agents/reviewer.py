import asyncio

from src.core.observability import log, log_token_usage
from src.core.config import instructor_client, REVIEWER_MODEL
from src.core.models import ReviewReport, GlobalPipelineContext
from src.core.prompts import get_system_prompt, get_skill
from src.utils.api_retry import with_api_retry

async def run_reviewer_node(ctx: GlobalPipelineContext, qa_success: bool, qa_log: list[str], sec_success: bool, sec_log: list[str]) -> None:
    model_name = REVIEWER_MODEL
    log.info(f"🔍 [ROLE] Reviewer Agent | [MODEL] {model_name}")

    qa_report = "\n".join(qa_log) if qa_log else "No logs produced."
    sec_report = "\n".join(sec_log) if sec_log else "No logs produced."

    user_content = (
        f"=== ORIGINAL USER REQUIREMENT ===\n{ctx.pr_description}\n\n"
        f"=== ARCHITECT CONTRACT ===\n{ctx.contract.model_dump_json(indent=2)}\n\n"
        f"=== GENERATED PRODUCTION CODE ===\n{ctx.production_code_snapshot}\n\n"
        f"=== GENERATED TEST SUITE ===\n{ctx.test_code_snapshot}\n\n"
        f"=== FUNCTIONAL TESTS RUN ({'PASSED' if qa_success else 'FAILED'}) ===\n{qa_report}\n\n"
        f"=== SAST SECURITY SCAN ({'PASSED' if sec_success else 'FAILED'}) ===\n{sec_report}"
    )

    sys_prompt = get_system_prompt("reviewer") + "\n\n" + get_skill("engineering_guide")

    @with_api_retry(max_retries=3, agent_name="Reviewer Agent")
    async def _invoke_llm() -> tuple:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: instructor_client.chat.completions.create_with_completion(
                model=model_name,
                response_model=ReviewReport,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_content}
                ]
            )
        )

    report, raw_response = await _invoke_llm()
    ctx.review_report = report
    log_token_usage("Reviewer Agent", raw_response)

    log.info(f"   [THOUGHT] Multi-angle review processed:")
    log.info(f"     ├─ [CODE AUDIT] {ctx.review_report.code_quality_analysis}")
    log.info(f"     ├─ [TEST AUDIT] {ctx.review_report.test_integrity_analysis}")
    log.info(f"     └─ [LOG INTERPRETATION] {ctx.review_report.log_verification_analysis}")
    log.info(f"   ├── [GATE][FUNCTIONAL-TESTS] {'PASSED' if qa_success else 'FAILED'}")
    log.info(f"   ├── [GATE][SAST-SECURITY] {'PASSED' if sec_success else 'FAILED'}")
    log.info(f"   └── [AUDIT] Code Approved: {ctx.review_report.code_quality_approved} | Tests Approved: {ctx.review_report.test_integrity_approved}\n")

    log.debug(f"Reviewer Node Output: {ctx.review_report.model_dump_json(indent=2)}")
