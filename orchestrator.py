import os
import sys
import uuid
import argparse
import asyncio
from pathlib import Path
from dataclasses import dataclass

from src.core.observability import log, reconfigure_logging
from src.core.config import check_environment
from src.core.models import GlobalPipelineContext, WorkspacePaths, RUNS_BASE
from src.agents.architect import run_architect_node
from src.agents.qa import run_qa_agent_node
from src.agents.developer import run_developer_node
from src.agents.reviewer import run_reviewer_node
from src.nodes.gates import run_qa_unit_tests, run_security_scan

# ==========================================
# CLI ARGUMENT PARSER
# ==========================================
@dataclass
class RunConfig:
    """Normalized invocation parameters for a single orchestrator run."""
    description: str | None
    base_branch: str
    resume: Path | None
    reset_attempts: bool
    repo: str | None = None
    ticket: str | None = None
    src_dir: str = "src/"
    tests_dir: str = "tests/"


def parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(
        description="Antigravity SDLC Orchestrator — git-anchored, per-run isolated pipeline."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("description", nargs="?", help="Inline task description string.")
    group.add_argument("-f", "--file", help="Path to a file containing the task description.")
    parser.add_argument("--repo", help="Git URL or local path to the target repository (required unless --resume).")
    parser.add_argument("--ticket", help="Ticket ID or feature name; names the session and feat/ticket-<id> branch (required unless --resume).")
    parser.add_argument("--src-dir", default="src/", help="Source code path inside the repo (default: src/).")
    parser.add_argument("--tests-dir", default="tests/", help="Tests path inside the repo (default: tests/).")
    parser.add_argument("--base-branch", default="main", help="Base branch of the repository.")
    parser.add_argument("--resume", type=Path, help="Path to a checkpoint JSON file.")
    parser.add_argument("--reset-attempts", action="store_true", help="Reset circuit breaker counter on resume.")

    args = parser.parse_args()

    if args.resume:
        return RunConfig(
            description=None,
            base_branch=args.base_branch,
            resume=args.resume,
            reset_attempts=args.reset_attempts,
            src_dir=args.src_dir,
            tests_dir=args.tests_dir,
        )

    # Fresh run: a target repo and ticket are mandatory for git-anchored bootstrapping.
    missing = [name for name, val in (("--repo", args.repo), ("--ticket", args.ticket)) if not val]
    if missing:
        parser.error(f"the following arguments are required for a fresh run: {', '.join(missing)}")

    # Task description: explicit file → inline → fall back to the ticket text.
    if args.file:
        path = Path(args.file)
        if not path.exists():
            log.error(f"🚨 File not found: {args.file}")
            sys.exit(1)
        description = path.read_text(encoding="utf-8")
    elif args.description:
        description = args.description
    else:
        description = args.ticket

    return RunConfig(
        description=description,
        base_branch=args.base_branch,
        resume=None,
        reset_attempts=args.reset_attempts,
        repo=args.repo,
        ticket=args.ticket,
        src_dir=args.src_dir,
        tests_dir=args.tests_dir,
    )


# ==========================================
# GIT-ANCHORED SESSION BOOTSTRAP
# ==========================================
GIT_NETWORK_TIMEOUT = 300  # seconds; hard ceiling for network git ops (clone/fetch)


async def _run_checked(cmd: list[str], action: str, timeout: float | None = None) -> None:
    """Runs a fixed-argument git subprocess (shell=False) and aborts the run on failure.

    Disables interactive credential prompts (GIT_TERMINAL_PROMPT=0) so a private/HTTPS repo
    without creds fails fast instead of blocking forever on a dead tty, and enforces a wall-clock
    timeout on network ops — killing AND reaping the child on expiry so no <defunct> zombie is
    left behind. The child's stderr is always surfaced to the operator on a non-zero exit.
    """
    env = os.environ.copy()            # copy, never a bare dict — preserves PATH/SystemRoot
    env["GIT_TERMINAL_PROMPT"] = "0"   # no interactive credential prompt -> fail fast, never hang
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env,
    )
    try:
        _stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()              # reap immediately after kill — no <defunct> zombie
        log.error(f"🚨 {action} timed out after {timeout}s (possible credential prompt / network hang) — aborting.")
        sys.exit(1)
    if proc.returncode != 0:
        log.error(f"🚨 {action} failed (exit {proc.returncode}): {stderr.decode(errors='replace').strip()}")
        sys.exit(1)


async def bootstrap_session(cfg: RunConfig) -> tuple[Path, WorkspacePaths]:
    """Isolates a run: shallow-clone the target repo, cut the feature branch, map the workspace.

    Produces ``runs/run_<uuid>/repo/`` (shallow clone on ``feat/ticket-<ticket>``) and points the
    audit log at the run-local ``logs/`` dir so parallel orchestrators never share a trail.
    """
    run_dir = (RUNS_BASE / f"run_{uuid.uuid4().hex}").resolve()
    repo_dir = run_dir / "repo"
    run_dir.mkdir(parents=True, exist_ok=True)
    log.info(f"🌱 Bootstrapping session at {run_dir}")

    # Atomic shallow clone (single subprocess, HEAD only) — origin is configured automatically.
    # Network op: bounded by GIT_NETWORK_TIMEOUT so a credential prompt can never hang the run.
    await _run_checked(["git", "clone", "--depth", "1", cfg.repo, str(repo_dir)], "git clone", timeout=GIT_NETWORK_TIMEOUT)
    branch = f"feat/ticket-{cfg.ticket}"
    await _run_checked(["git", "-C", str(repo_dir), "checkout", "-b", branch], "git checkout -b")
    log.info(f"   [GIT] Shallow-cloned {cfg.repo} -> {repo_dir} (branch: {branch})")

    try:
        paths = WorkspacePaths.for_run(run_dir, repo_dir, cfg.src_dir, cfg.tests_dir)
    except ValueError as exc:
        log.error(f"🚨 {exc}")
        sys.exit(1)

    # Redirect the audit trail into this session's logs/ before any pipeline node runs.
    reconfigure_logging(paths.logs_dir)
    return run_dir, paths


# ==========================================
# MAIN ORCHESTRATOR
# ==========================================
async def main():
    check_environment()
    cfg = parse_args()

    if cfg.resume:
        try:
            ctx = GlobalPipelineContext.load_checkpoint(cfg.resume)
            log.info(f"Loaded checkpoint from {cfg.resume}")
        except Exception as exc:
            log.error(f"🚨 Failed to load checkpoint '{cfg.resume}': {exc}")
            sys.exit(1)
        if cfg.reset_attempts:
            ctx.current_attempt = 1
            log.info("🔄 Circuit Breaker budget reset via CLI flag.")
    else:
        # Bootstrap an isolated git-anchored session, then bind the context to its workspace.
        run_dir, paths = await bootstrap_session(cfg)
        ctx = GlobalPipelineContext(
            pr_description=cfg.description or "",
            base_branch=cfg.base_branch,
            workspace_paths=paths,
        )
        log.debug(f"Initialized global context for run {run_dir} with PR: {cfg.description}")

    checkpoint_file = ctx.workspace_paths.reports_dir / "checkpoint.json"

    # 1. Architecture Phase (executed once per session)
    if ctx.contract:
        log.info("Skipping Architect node: contract already present in context.")
    else:
        await run_architect_node(ctx)
        ctx.save_checkpoint(checkpoint_file)
        log.debug(f"Checkpoint saved after Architect node: {checkpoint_file}")

    max_retries = 3

    regenerate_tests = ctx.needs_test_regeneration()

    for attempt in range(ctx.current_attempt, max_retries + 1):
        ctx.current_attempt = attempt
        log.info(f"🔷 Orchestration cycle {attempt}/{max_retries}")
        log.debug(f"Starting orchestration cycle {attempt}")

        # Reset accumulated errors before starting a new cycle. Developer/QA will see only clean feedback.
        current_error_trace = ctx.error_trace
        ctx.error_trace = ""

        # 2. Testing Phase (Runs initially, on rejected tests, or whenever no snapshot exists)
        if regenerate_tests:
            await run_qa_agent_node(ctx, current_error_trace)
            ctx.save_checkpoint(checkpoint_file)
            log.debug(f"Checkpoint saved after QA node: {checkpoint_file}")
            regenerate_tests = False  # Reset the flag until the next rejection
        elif ctx.test_code_snapshot:
            log.info("Skipping QA generation: validated test snapshot present in context.")

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

        # If the Reviewer rejected the tests specifically, raise the test regeneration flag
        if not all_gates_passed and not ctx.review_report.test_integrity_approved:
            log.warning("🔶 Reviewer Agent flagged test suite anomalies. Scheduling test regeneration.")
            regenerate_tests = True

        if not all_gates_passed:
            ctx.error_trace = ctx.review_report.diagnostic_payload
            log.warning(f"🔶 Cycle {attempt} failed. Routing reviewer diagnostic to target agent.")

        # Advance the persisted attempt counter so a resumed run cannot exceed the
        # original retry budget. The counter is bumped before saving so the next
        # process picks up exactly where this one left off.
        ctx.current_attempt = attempt + 1
        ctx.save_checkpoint(checkpoint_file)
        log.debug(f"Checkpoint saved at end of cycle {attempt}: {checkpoint_file}")

        if all_gates_passed:
            log.info("🟩 PIPELINE SUCCESS: All validation gates passed.")
            return

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
