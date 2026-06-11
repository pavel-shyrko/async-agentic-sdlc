from src.core.observability import log, log_token_usage
from src.core.config import REVIEWER_MODEL
from src.core.models import ReviewReport, GlobalPipelineContext
from src.core.prompts import get_system_prompt, build_agent_context
from src.utils.llm import run_structured_llm

async def run_reviewer_node(ctx: GlobalPipelineContext, qa_success: bool, qa_log: list[str], sec_success: bool, sec_log: list[str]) -> None:
    model_name = REVIEWER_MODEL
    log.info(f"🔍 [ROLE] Reviewer Agent | [MODEL] {model_name}")

    qa_report = "\n".join(qa_log) if qa_log else "No logs produced."
    sec_report = "\n".join(sec_log) if sec_log else "No logs produced."

    # production_code_snapshot is a {repo-relative path: full content} dict; render it as labelled
    # file blocks so the Reviewer sees the same format as the test suite (not a raw dict repr).
    production_code = "\n\n".join(
        f"=== FILE: {path} ===\n{content}" for path, content in ctx.production_code_snapshot.items()
    ) or "No production code changes detected."

    user_content = (
        f"=== ORIGINAL USER REQUIREMENT ===\n{ctx.pr_description}\n\n"
        f"=== ARCHITECT CONTRACT ===\n{ctx.contract.model_dump_json(indent=2)}\n\n"
        f"=== GIT DIFF (SCOPE OF CHANGES) ===\n{ctx.production_code_diff}\n\n"
        f"=== GENERATED PRODUCTION CODE ===\n{production_code}\n\n"
        f"=== GENERATED TEST SUITE ===\n{ctx.test_code_snapshot}\n\n"
        f"=== FUNCTIONAL TESTS RUN ({'PASSED' if qa_success else 'FAILED'}) ===\n{qa_report}\n\n"
        f"=== SAST SECURITY SCAN ({'PASSED' if sec_success else 'FAILED'}) ===\n{sec_report}"
    )

    sys_prompt = get_system_prompt("reviewer") + "\n\n" + await build_agent_context("reviewer", ctx)

    report, raw_response = await run_structured_llm(
        "reviewer",
        ReviewReport,
        [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_content},
        ],
    )
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
