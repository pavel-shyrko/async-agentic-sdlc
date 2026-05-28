import sys
import argparse
import asyncio
from pathlib import Path

from src.core.observability import log
from src.core.config import check_environment
from src.core.models import GlobalPipelineContext
from src.agents.architect import run_architect_node
from src.agents.qa import run_qa_agent_node
from src.agents.developer import run_developer_node
from src.agents.reviewer import run_reviewer_node
from src.nodes.gates import run_qa_unit_tests, run_security_scan

# ==========================================
# CLI ARGUMENT PARSER
# ==========================================
def parse_args() -> tuple[str, str]:
    parser = argparse.ArgumentParser(
        description="Antigravity SDLC Orchestrator — pass a task description inline or from a file."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("description", nargs="?", help="Inline task description string.")
    group.add_argument("-f", "--file", help="Path to a file containing the task description.")
    parser.add_argument("--base-branch", default="main", help="Base branch of the repository.")

    args = parser.parse_args()

    description = ""
    if args.file:
        path = Path(args.file)
        if not path.exists():
            log.error(f"🚨 File not found: {args.file}")
            sys.exit(1)
        description = path.read_text(encoding="utf-8")
    elif args.description:
        description = args.description
    else:
        parser.print_help()
        sys.exit(0)

    return description, args.base_branch


# ==========================================
# MAIN ORCHESTRATOR
# ==========================================
async def main():
    check_environment()
    pr_description, base_branch = parse_args()

    # Initialize unified context state
    ctx = GlobalPipelineContext(pr_description=pr_description, base_branch=base_branch)
    log.debug(f"Initialized global context with PR: {pr_description}")

    # 1. Architecture Phase (executed once per session)
    await run_architect_node(ctx)

    max_retries = 3
    regenerate_tests = True  # Raise the test regeneration flag for initial QA Agent run

    for attempt in range(1, max_retries + 1):
        log.info(f"🔷 Orchestration cycle {attempt}/{max_retries}")
        log.debug(f"Starting orchestration cycle {attempt}")

        # Reset accumulated errors before starting a new cycle. Developer/QA will see only clean feedback.
        current_error_trace = ctx.error_trace
        ctx.error_trace = ""

        # 2. Testing Phase (Runs initially or if the Reviewer rejects the tests)
        if regenerate_tests:
            await run_qa_agent_node(ctx, current_error_trace)
            regenerate_tests = False  # Reset the flag until the next rejection

        # 3. Development Phase (Developer fixes production code)
        await run_developer_node(ctx, current_error_trace)

        # 4. Automated Validation Phase (Runtime gates)
        log.debug("Triggering parallel validation gates (QA & Security)")
        qa_result, sec_result = await asyncio.gather(
            run_qa_unit_tests(
                artifacts_base_abs=str(ctx.workspace_paths.code_dir.parent.resolve()),
            ),
            run_security_scan([str(ctx.workspace_paths.code_dir)]),
        )
        qa_success, qa_lines = qa_result
        sec_success, sec_lines = sec_result

        # 5. Comprehensive Audit Phase (Reviewer Agent)
        await run_reviewer_node(ctx, qa_success, qa_lines, sec_success, sec_lines)

        # Print execution logs of utilities ONLY in case of an actual failure to CLI, but log everything to file
        if not qa_success:
            log.info("  [GATE][FUNCTIONAL-TESTS] Failure raw output:")
            for line in qa_lines:
                log.info(f"    {line}")
        if not sec_success:
            log.info("  [GATE][SAST-SECURITY] Failure raw output:")
            for line in sec_lines:
                log.info(f"    {line}")

        all_gates_passed = (
            qa_success
            and sec_success
            and ctx.review_report.code_quality_approved
            and ctx.review_report.test_integrity_approved
        )

        # Log Approval Checkpoint Status
        log.debug(f"Approval Checkpoint Status: QA={qa_success}, SAST={sec_success}, Code_Approve={ctx.review_report.code_quality_approved}, Test_Approve={ctx.review_report.test_integrity_approved}")

        if all_gates_passed:
            log.info("🟩 PIPELINE SUCCESS: All validation gates passed.")
            return

        # If the Reviewer rejected the tests specifically, raise the test regeneration flag
        if not ctx.review_report.test_integrity_approved:
            log.warning("🔶 Reviewer Agent flagged test suite anomalies. Scheduling test regeneration.")
            regenerate_tests = True

        ctx.error_trace = ctx.review_report.diagnostic_payload
        log.warning(f"🔶 Cycle {attempt} failed. Routing reviewer diagnostic to target agent.")

    # Escalation on Circuit Breaker open
    log.error("\n🚨 CIRCUIT BREAKER OPEN: Retries exhausted.")

    incident_file = str(ctx.workspace_paths.reports_dir / "incident_report.json")
    with open(incident_file, "w", encoding="utf-8") as f:
        f.write(ctx.model_dump_json(indent=2))
    log.error(f"  └── Incident report written to {incident_file}")

    # Final dump to audit log before exit
    log.debug(f"Final Incident Context Dump: {ctx.model_dump_json(indent=2)}")
    sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
