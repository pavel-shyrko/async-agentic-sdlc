import os
import sys
import json
import uuid
import argparse
import asyncio
import subprocess
from pathlib import Path
from typing import NoReturn
from dataclasses import dataclass

from src.core.observability import log, reconfigure_logging
from src.core.config import check_environment, PIPELINE_BUDGET_TOKENS
from src.core.models import GlobalPipelineContext, WorkspacePaths, RUNS_BASE
from src.utils.git_helpers import get_git_root, get_pipeline_snapshot_files
from src.agents.techlead import run_techlead_node
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
    push: bool = False


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
    parser.add_argument("--push", action="store_true", help="Push the feature branch to origin after the atomic success commit.")

    args = parser.parse_args()

    if args.resume:
        return RunConfig(
            description=None,
            base_branch=args.base_branch,
            resume=args.resume,
            reset_attempts=args.reset_attempts,
            src_dir=args.src_dir,
            tests_dir=args.tests_dir,
            push=args.push,
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
        push=args.push,
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


async def bootstrap_session(cfg: RunConfig, run_dir: Path) -> WorkspacePaths:
    """Isolates a run: shallow-clone the target repo, cut the feature branch, map the workspace.

    The caller owns ``run_dir`` (and has already re-anchored logging to it), so the run id is
    bound once, up front — no late binding. Produces ``run_dir/repo/`` (shallow clone on
    ``feat/ticket-<ticket>``) and returns the mapped workspace paths.
    """
    repo_dir = run_dir / "repo"
    run_dir.mkdir(parents=True, exist_ok=True)
    log.info(f"🌱 Bootstrapping session at {run_dir}")

    # Atomic shallow clone (single subprocess, HEAD only) — origin is configured automatically.
    # Network op: bounded by GIT_NETWORK_TIMEOUT so a credential prompt can never hang the run.
    await _run_checked(["git", "clone", "--depth", "1", cfg.repo, str(repo_dir)], "git clone", timeout=GIT_NETWORK_TIMEOUT)

    branch = f"feat/ticket-{cfg.ticket}"
    await _run_checked(["git", "-C", str(repo_dir), "checkout", "-b", branch], "git checkout -b")

    # Force a LOCAL ref for the base branch via an explicit refspec (<base>:<base>) so the snapshot diff
    # `git diff --cached <base_branch>` resolves it — a bare fetch lands only in FETCH_HEAD. Done AFTER
    # the feature-branch checkout: git refuses to fetch into the still-checked-out default branch.
    await _run_checked(
        ["git", "-C", str(repo_dir), "fetch", "--depth", "1", "origin", f"{cfg.base_branch}:{cfg.base_branch}"],
        "git fetch base branch", timeout=GIT_NETWORK_TIMEOUT,
    )
    log.info(f"   [GIT] Shallow-cloned {cfg.repo} -> {repo_dir} (branch: {branch})")

    try:
        paths = WorkspacePaths.for_run(run_dir, repo_dir, cfg.src_dir, cfg.tests_dir)
    except ValueError as exc:
        log.error(f"🚨 {exc}")
        sys.exit(1)

    return paths


# ==========================================
# ATOMIC SUCCESS TRANSACTION
# ==========================================
async def _has_staged_changes(repo_root: str) -> bool:
    """True when the index holds staged changes vs HEAD — the empty-commit guard.

    ``git diff --cached --quiet`` exits 0 when nothing is staged and 1 when there ARE staged
    changes, so this can't go through ``_run_checked`` (exit 1 is the normal signal, not an error).
    """
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", repo_root, "diff", "--cached", "--quiet",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env,
    )
    _stdout, stderr = await proc.communicate()
    if proc.returncode == 0:
        return False
    if proc.returncode == 1:
        return True
    log.error(f"🚨 staged-change check failed (exit {proc.returncode}): {stderr.decode(errors='replace').strip()}")
    sys.exit(1)


async def finalize_transaction(ctx: GlobalPipelineContext, push: bool = False) -> None:
    """Commits the staged delta atomically on full success; optionally pushes the branch.

    Agents only stage into the index across cycles; this is the single transactional commit so the
    ``feat/ticket-<id>`` branch never accrues intermediate self-healing commits.
    """
    repo_root = await get_git_root(str(ctx.workspace_paths.code_dir))

    if not await _has_staged_changes(repo_root):
        log.warning("🟡 No staged changes in the index — skipping final commit.")
        return

    desc = (ctx.pr_description or "").strip()
    summary = next((line.strip() for line in desc.splitlines() if line.strip()), "") if desc else ""
    summary = (summary or ctx.ticket or "automated change")[:72]
    subject = f"feat({ctx.ticket or 'ticket'}): {summary}"

    # Pin a per-ticket agent identity so each session's commit is uniquely attributable
    # (and so the commit succeeds even when the clone inherits no global git config).
    agent_name = f"AI Agent ({ctx.ticket if ctx.ticket else 'Anonymous'})"
    agent_email = f"agent-{ctx.ticket.lower() if ctx.ticket else 'session'}@sdlc-factory.local"
    commit_args = [
        "git", "-C", repo_root,
        "-c", f"user.name={agent_name}", "-c", f"user.email={agent_email}",
        "commit", "-m", subject,
    ]
    await _run_checked(commit_args, "git commit")
    log.info(f"✅ Atomic commit on feat/ticket-{ctx.ticket}: {subject}")

    if push:
        await _run_checked(
            ["git", "-C", repo_root, "push", "-u", "origin", "HEAD"],
            "git push", timeout=GIT_NETWORK_TIMEOUT,
        )
        log.info("⬆️  Pushed feature branch to origin.")


# ==========================================
# PRODUCTION SNAPSHOT BUILDER
# ==========================================
MAX_FILE_SIZE_BYTES = 100 * 1024  # 100 KB; larger files are marked, not inlined, to avoid LLM token exhaustion


def build_production_snapshot(ctx: GlobalPipelineContext) -> None:
    """Rebuilds ``ctx.production_code_snapshot`` from the FULL transaction delta vs ``base_branch``.

    Replaces the Developer agent's self-reported, subtree-scoped output. We first stage the whole
    tree (``git add -A``) so every mutation lands in the index, then read the CUMULATIVE set of
    changed files with ``git diff --cached --name-only <base_branch>`` and capture each one's FULL
    content from disk (any text file — .py, json, yaml, Dockerfile, …, not just Python).

    Diffing the INDEX against ``base_branch`` — rather than the working tree against the index — is
    what keeps the snapshot cohesive across retry cycles. Once cycle 1's files are staged, a
    ``git ls-files --others --modified`` would surface ONLY the single file cycle 2 re-touched
    (the rest match the index), blinding the Reviewer to every previously-staged file. The cached
    diff against the merge base always reports the complete production delta regardless of cycle.

    Tests are excluded (they live in ``test_code_snapshot``); deleted paths and binary/non-UTF-8
    files are recorded with explicit markers instead of crashing the read or flooding the Reviewer.
    Staging up front also leaves the tree staged for ``finalize_transaction``'s atomic success commit.

    Also captures the raw unified diff (``git diff --cached <base_branch>``) into
    ``ctx.production_code_diff`` so the Reviewer can scope its audit to the actual delta instead of
    treating untouched legacy lines in modified files as new code.
    """
    repo_dir = ctx.workspace_paths.repo_dir
    # Derive the test-dir prefix dynamically (honours --tests-dir, e.g. spec/) — never hardcode "tests/".
    # .as_posix() is required: git emits forward-slash paths, so the prefix must match on Windows too.
    # A tests_dir outside the repo can't collide with repo-relative paths, so no prefix is needed.
    try:
        test_prefix = f"{ctx.workspace_paths.tests_dir.relative_to(repo_dir).as_posix()}/"
    except ValueError:
        test_prefix = None  # tests_dir lives outside the repo root → no prefix collision possible

    # 1. Stage every mutation so the index reflects the complete working-tree state across ALL cycles.
    subprocess.run(["git", "add", "-A"], cwd=str(repo_dir), check=True)

    # 1b. Capture the cumulative unified diff vs base — the Reviewer's authoritative scope-of-change,
    #     so it can separate the Developer's actual edits from pre-existing legacy code in the same file.
    diff_cmd = subprocess.run(
        ["git", "diff", "--cached", ctx.base_branch],
        cwd=str(repo_dir), capture_output=True, text=True, check=True,
    )
    ctx.production_code_diff = diff_cmd.stdout

    # 2. Read the cumulative index-vs-base delta. -z emits raw NUL-terminated paths (no quoting of
    #    spaces/newlines/unicode) — split on NUL.
    listing = subprocess.run(
        ["git", "diff", "--name-only", "--cached", "-z", ctx.base_branch],
        cwd=str(repo_dir), capture_output=True, text=True, check=True,
    )

    snapshot: dict[str, str] = {}
    for rel in listing.stdout.split('\0'):
        rel = rel.strip()
        if not rel:
            continue
        # Domain purity: QA-generated tests belong to test_code_snapshot, never the production one.
        if (test_prefix and rel.startswith(test_prefix)) or Path(rel).name.startswith("test_"):
            continue
        file_path = repo_dir / rel
        if not file_path.exists():
            # The diff also reports deletions (e.g. Developer ghost-file GC) — record, don't crash.
            snapshot[rel] = "<FILE DELETED BY DEVELOPER>"
            continue
        # Payload guard: never inline a massive file into the Reviewer context — mark and skip.
        size = file_path.stat().st_size
        if size > MAX_FILE_SIZE_BYTES:
            snapshot[rel] = f"<FILE TOO LARGE: {size} bytes exceeds {MAX_FILE_SIZE_BYTES} byte limit. EXCLUDED TO PREVENT TOKEN EXHAUSTION.>"
            continue
        try:
            snapshot[rel] = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Never inject binary garbage into the Reviewer context (token explosion) — mark instead.
            snapshot[rel] = "<BINARY OR NON-UTF8 FILE EXCLUDED>"

    ctx.production_code_snapshot = snapshot

    log.info(f"   [SNAPSHOT] Captured {len(snapshot)} production file(s): {sorted(snapshot)}")


# ==========================================
# FAST-FAIL DOCUMENTATION GUARDRAIL
# ==========================================
GUARDRAIL_TOP_LINES = 15        # top-of-file window scanned for a justification
GUARDRAIL_MAX_REROUTES = 2      # local guardrail_retries cap: free reroutes before a Hard Halt

# ==========================================
# TEST-COLLECTION-FAILURE TRIAGE (QA loop break)
# ==========================================
TEST_TRIAGE_MAX_REROUTES = 2    # free QA regenerations on import/collection failure before a Hard Halt
FEEDBACK_TAIL_LINES = 50        # only the last N runner lines are fed forward (context pruning)
FEEDBACK_MAX_CHARS = 8000       # hard cap on any failure text injected into an agent prompt
# Markers that mean the suite failed to IMPORT (broken QA artifact), not a production-logic failure.
_COLLECTION_FAILURE_MARKERS = (
    "ImportError",
    "ModuleNotFoundError",
    "cannot import name",
    "unittest.loader._FailedTest",
)


def _is_test_collection_failure(qa_log: list[str]) -> bool:
    """True when the test runner failed at collection/import time (a broken test suite)."""
    joined = "\n".join(qa_log)
    return any(marker in joined for marker in _COLLECTION_FAILURE_MARKERS)


def _truncate_tail(lines: list[str], max_lines: int = FEEDBACK_TAIL_LINES) -> str:
    """Keep only the last ``max_lines`` runner lines — failures are always at the tail."""
    return "\n".join(lines[-max_lines:])


def _cap_text(text: str, max_chars: int = FEEDBACK_MAX_CHARS) -> str:
    """Hard-cap any failure text injected into an agent prompt (head + tail kept)."""
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return f"{text[:half]}\n…[truncated]…\n{text[-half:]}"


def _clear_test_files(tests_dir) -> None:
    """Delete stale ``test_*.py`` so QA regenerates from a clean slate (no snapshot bloat)."""
    for p in Path(tests_dir).glob("test_*.py"):
        p.unlink()
# Language-agnostic comment lead-ins. ''' is added beyond the spec list so a Python single-quote module
# docstring (a valid justification) isn't flagged as undocumented.
_COMMENT_PREFIXES = ("#", "//", "/*", "*", '"""', "'''")
_GUARDRAIL_MESSAGE = (
    "SYSTEM GUARDRAIL: File `{file_name}` was created without an architectural justification. "
    "You must add a comment block at the top of the file explaining its purpose before the system "
    "will route your code to the Reviewer."
)


def _top_block_has_comment(file_path: Path) -> bool | None:
    """True/False if the file's first GUARDRAIL_TOP_LINES carry a comment lead-in; None = ignore safely.

    Returns None for binary/non-UTF-8, empty/whitespace-only, or unreadable (vanished) files so the
    scanner never raises and never emits a false 'undocumented' violation — mirroring
    build_production_snapshot's binary handling (UnicodeDecodeError → skip).
    """
    try:
        lines: list[str] = []
        with file_path.open("r", encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if i >= GUARDRAIL_TOP_LINES:
                    break
                lines.append(line)
    except (UnicodeDecodeError, OSError):
        return None  # binary / non-UTF-8 / unreadable → ignore safely
    if not any(line.strip() for line in lines):
        return None  # empty or whitespace-only → ignore safely
    return any(line.strip().startswith(_COMMENT_PREFIXES) for line in lines)


async def enforce_documentation_guardrail(ctx: GlobalPipelineContext) -> str | None:
    """Blocks the Developer→Reviewer transition on undocumented NEWLY-CREATED files.

    Reuses the production delta build_production_snapshot() just computed (QA tests already excluded) as
    the candidate set, intersects it with the git-ADDED set so only genuinely new files count — never
    edits to pre-existing files — and scans each uncontracted new file's top block for any comment.
    Returns a Developer-targeted diagnostic naming every offender, or None when all new files are
    documented (or there are none) so the pipeline may proceed to the Reviewer.
    """
    # Fast no-op when there is no production delta (also keeps snapshot-mocked unit tests git-free).
    if not ctx.production_code_snapshot:
        return None

    contract_files = {Path(f).as_posix() for f in (ctx.contract.files_to_modify if ctx.contract else [])}
    uncontracted = [rel for rel in ctx.production_code_snapshot if Path(rel).as_posix() not in contract_files]
    if not uncontracted:
        return None

    # Only NEWLY-CREATED files need a justification — intersect the candidates with the git-added set.
    repo_dir = ctx.workspace_paths.repo_dir
    added = set(await get_pipeline_snapshot_files(str(repo_dir), ctx.base_branch, diff_filter="A"))
    violations = [
        rel for rel in uncontracted
        if rel in added and _top_block_has_comment(repo_dir / rel) is False
    ]
    if not violations:
        return None

    log.warning(f"   [GUARDRAIL] {len(violations)} undocumented new file(s): {sorted(violations)}")
    return "\n".join(_GUARDRAIL_MESSAGE.format(file_name=v) for v in violations)


def enforce_financial_circuit_breaker(ctx: GlobalPipelineContext) -> None:
    """Financial Circuit Breaker: hard-halt the FSM once cumulative token spend breaches budget.

    Checked after every cost-accruing node so a pathological retry loop cannot drain the API
    budget. Reuses the incident machinery — ``incident_report.json`` now carries the full
    per-agent telemetry breakdown for audit. Token totals are persisted in the checkpoint, so
    the budget is enforced consistently across ``--resume``.
    """
    if ctx.telemetry.total_tokens >= PIPELINE_BUDGET_TOKENS:
        _abort_with_incident(
            ctx,
            f"\n🚨 FINANCIAL CIRCUIT BREAKER OPEN: cumulative {ctx.telemetry.total_tokens} tokens "
            f"≥ budget {PIPELINE_BUDGET_TOKENS}. Halting before further spend.",
        )


def _finops_subtotals(ctx: GlobalPipelineContext) -> str:
    """Per-provider cost split, e.g. 'Gemini est. $0.0010 | Claude $0.1328 | Σ $0.1338'.

    Gemini cost is estimated from the price table (flagged ``est.``); Claude cost is authoritative.
    """
    bp = ctx.telemetry.by_provider()
    parts: list[str] = []
    for prov in ("gemini", "claude"):
        if prov in bp:
            label = "Gemini est." if prov == "gemini" else "Claude"
            parts.append(f"{label} ${bp[prov]['cost_usd']:.4f}")
    parts.append(f"Σ ${ctx.telemetry.total_cost_usd:.4f}")
    return " | ".join(parts)


def write_finops_report(ctx: GlobalPipelineContext) -> None:
    """Persist the cumulative FinOps breakdown to ``reports/finops_report.json``."""
    report_file = ctx.workspace_paths.reports_dir / "finops_report.json"
    report_file.parent.mkdir(parents=True, exist_ok=True)
    with open(report_file, "w", encoding="utf-8") as f:
        # default=str serialises Decimal money as exact strings (json can't encode Decimal natively).
        json.dump(ctx.telemetry.finops_report(PIPELINE_BUDGET_TOKENS), f, indent=2, default=str)
    log.debug(f"FinOps report written to {report_file}")


def log_finops_summary(ctx: GlobalPipelineContext) -> None:
    """Print the end-of-run GRAND TOTAL block: per-agent, per-provider, and budget utilisation."""
    tel = ctx.telemetry
    log.info("📊 [FINOPS] GRAND TOTAL")
    for name, u in tel.by_agent.items():
        log.info(f"   ├─ {name} ({u.provider}) | {u.total_tokens}t | ${u.cost_usd:.4f} | calls: {u.calls}")
    for prov, agg in tel.by_provider().items():
        label = "Gemini (est.)" if prov == "gemini" else "Claude (actual)"
        log.info(f"   ├─ Σ {label} | {int(agg['tokens'])}t | ${agg['cost_usd']:.4f}")
    used_pct = (100.0 * tel.total_tokens / PIPELINE_BUDGET_TOKENS) if PIPELINE_BUDGET_TOKENS else 0.0
    log.info(
        f"   └─ TOTAL | {tel.total_tokens}t | ${tel.total_cost_usd:.4f} "
        f"| {used_pct:.1f}% of {PIPELINE_BUDGET_TOKENS}t budget"
    )


def _abort_with_incident(ctx: GlobalPipelineContext, header: str) -> NoReturn:
    """Logs a terminal header, persists the full context as an incident report, and exits non-zero."""
    log.error(header)
    incident_file = str(ctx.workspace_paths.reports_dir / "incident_report.json")
    with open(incident_file, "w", encoding="utf-8") as f:
        f.write(ctx.model_dump_json(indent=2))
    log.error(f"  └── Incident report written to {incident_file}")
    log.debug(f"Final Incident Context Dump: {ctx.model_dump_json(indent=2)}")
    # Always persist + surface the FinOps breakdown, even on a halt, so spend is auditable.
    write_finops_report(ctx)
    log_finops_summary(ctx)
    sys.exit(1)


# ==========================================
# MAIN ORCHESTRATOR
# ==========================================
async def main():
    check_environment()
    cfg = parse_args()

    # Bind the run id ONCE, up front (before any logging), so the audit trail is anchored to the
    # correct run dir from the very first line — fixing the late-binding bug. On resume we reuse
    # the original run dir derived from the checkpoint path; a fresh run mints a new one.
    if cfg.resume:
        run_dir = cfg.resume.resolve().parent.parent  # runs/run_<uuid>/reports/checkpoint.json -> runs/run_<uuid>
    else:
        run_id = uuid.uuid4().hex
        run_dir = RUNS_BASE / f"run_{run_id}"

    # Re-anchor the audit trail to THIS run's logs/ dir before any other log line is emitted.
    # Append mode keeps a resumed run's timeline linear in the SAME file instead of splitting it.
    reconfigure_logging(run_dir / "logs")

    if cfg.resume:
        log.info(f"▶️ RESUMING FSM EXECUTION FROM CHECKPOINT: {cfg.resume}")
        try:
            ctx = GlobalPipelineContext.load_checkpoint(cfg.resume)
            log.info(f"Loaded checkpoint from {cfg.resume}")
        except Exception as exc:
            log.error(f"🚨 Failed to load checkpoint '{cfg.resume}': {exc}")
            sys.exit(1)
        if cfg.reset_attempts:
            ctx.current_attempt = 1
            log.info("🔄 State mutated: attempt counter reset to 1.")
    else:
        # Bootstrap an isolated git-anchored session into the pre-bound run dir.
        paths = await bootstrap_session(cfg, run_dir)
        ctx = GlobalPipelineContext(
            pr_description=cfg.description or "",
            base_branch=cfg.base_branch,
            ticket=cfg.ticket or "",
            workspace_paths=paths,
        )
        log.debug(f"Initialized global context for run {run_dir} with PR: {cfg.description}")

    checkpoint_file = ctx.workspace_paths.reports_dir / "checkpoint.json"

    # 1. Architecture Phase (executed once per session)
    if ctx.contract:
        log.info("Skipping TechLead node: contract already present in context.")
    else:
        await run_techlead_node(ctx)
        enforce_financial_circuit_breaker(ctx)
        ctx.save_checkpoint(checkpoint_file)
        log.debug(f"Checkpoint saved after TechLead node: {checkpoint_file}")

    max_retries = 3

    regenerate_tests = ctx.needs_test_regeneration()

    for attempt in range(ctx.current_attempt, max_retries + 1):
        ctx.current_attempt = attempt
        log.info(f"🔷 Orchestration cycle {attempt}/{max_retries}")
        log.debug(f"Starting orchestration cycle {attempt}")

        # Financial Circuit Breaker: halt immediately if a prior cycle (or a resumed run) is
        # already over budget, before spending any more tokens this cycle.
        enforce_financial_circuit_breaker(ctx)

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

        # 3. Development Phase — Developer writes code, then the fast-fail documentation guardrail
        #    runs BEFORE the Reviewer. A miss free-reroutes to the Developer (NO functional-budget
        #    retry consumed) and bypasses the Reviewer; after GUARDRAIL_MAX_REROUTES fast-fail reroutes
        #    a still-undocumented file triggers a Hard Halt.
        dev_feedback = current_error_trace
        guardrail_halt = False
        guardrail_msg: str | None = None
        for guardrail_retries in range(GUARDRAIL_MAX_REROUTES + 1):
            await run_developer_node(ctx, dev_feedback)
            # Snapshot the real working-tree production delta (git-tracked, full content) for the Reviewer.
            build_production_snapshot(ctx)
            guardrail_msg = await enforce_documentation_guardrail(ctx)
            if not guardrail_msg:
                break  # documented (or no new files) → proceed to gates/Reviewer
            if guardrail_retries == GUARDRAIL_MAX_REROUTES:
                guardrail_halt = True  # cap reached and still failing → hard halt below
                break
            log.warning(
                f"🔶 Doc guardrail: undocumented new file(s) — fast-fail reroute "
                f"{guardrail_retries + 1}/{GUARDRAIL_MAX_REROUTES} to Developer (no budget spent), Reviewer bypassed."
            )
            dev_feedback = guardrail_msg  # focused reroute: just the comment instruction

        if guardrail_halt:
            ctx.error_trace = guardrail_msg
            _abort_with_incident(
                ctx,
                f"\n🚨 HARD HALT: Developer failed the documentation guardrail after {GUARDRAIL_MAX_REROUTES} fast-fail reroutes.",
            )

        # Developer is the dominant token drain — enforce the budget before spending on gates.
        enforce_financial_circuit_breaker(ctx)

        # 4. Automated Validation Phase (Runtime gates) — with deterministic test-collection triage.
        #    A suite that fails to IMPORT is a broken QA artifact, not a production-code defect, so we
        #    regenerate the tests against the real production snapshot (Developer & Reviewer bypassed,
        #    no functional retry consumed) and re-run the gates. Bounded so it can never loop forever.
        for triage_try in range(TEST_TRIAGE_MAX_REROUTES + 1):
            log.debug("Triggering parallel validation gates (QA & Security)")
            qa_result, sec_result = await asyncio.gather(
                run_qa_unit_tests(
                    code_dir=str(ctx.workspace_paths.code_dir),
                    tests_dir=str(ctx.workspace_paths.tests_dir),
                ),
                run_security_scan([str(ctx.workspace_paths.code_dir)]),
            )
            qa_success, qa_lines = qa_result
            sec_success, sec_lines = sec_result

            if qa_success or not _is_test_collection_failure(qa_lines):
                break
            if triage_try == TEST_TRIAGE_MAX_REROUTES:
                ctx.error_trace = _cap_text(_truncate_tail(qa_lines))
                _abort_with_incident(
                    ctx,
                    f"\n🚨 HARD HALT: test suite still fails to import after "
                    f"{TEST_TRIAGE_MAX_REROUTES} QA regenerations.",
                )
            log.warning(
                f"🔶 Test-collection failure — free QA regen "
                f"{triage_try + 1}/{TEST_TRIAGE_MAX_REROUTES} (Developer & Reviewer bypassed, stale tests cleared)."
            )
            _clear_test_files(ctx.workspace_paths.tests_dir)
            ctx.error_trace = _cap_text(
                "Test suite failed to import (collection error). Regenerate the tests against the real "
                "production code: import every symbol from the module the contract assigns it to, and "
                "never invent or cross-import modules. Failure tail:\n" + _truncate_tail(qa_lines)
            )
            await run_qa_agent_node(ctx, ctx.error_trace)
            enforce_financial_circuit_breaker(ctx)
            ctx.save_checkpoint(checkpoint_file)

        # 5. Comprehensive Audit Phase (Reviewer Agent) — failure log pruned to the tail.
        await run_reviewer_node(ctx, qa_success, qa_lines[-FEEDBACK_TAIL_LINES:], sec_success, sec_lines)
        enforce_financial_circuit_breaker(ctx)

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
            ctx.error_trace = _cap_text(ctx.review_report.diagnostic_payload)
            log.warning(f"🔶 Cycle {attempt} failed. Routing reviewer diagnostic to target agent.")

        # Advance the persisted attempt counter so a resumed run cannot exceed the
        # original retry budget. The counter is bumped before saving so the next
        # process picks up exactly where this one left off.
        ctx.current_attempt = attempt + 1
        ctx.save_checkpoint(checkpoint_file)
        log.debug(f"Checkpoint saved at end of cycle {attempt}: {checkpoint_file}")
        log.info(
            f"   [FINOPS] {_finops_subtotals(ctx)} "
            f"| {ctx.telemetry.total_tokens}t / budget {PIPELINE_BUDGET_TOKENS}t"
        )

        if all_gates_passed:
            log.info("🟩 PIPELINE SUCCESS: All validation gates passed.")
            await finalize_transaction(ctx, push=cfg.push)
            write_finops_report(ctx)
            log_finops_summary(ctx)
            return

    # Escalation on Circuit Breaker open
    _abort_with_incident(ctx, "\n🚨 CIRCUIT BREAKER OPEN: Retries exhausted.")

if __name__ == "__main__":
    asyncio.run(main())
