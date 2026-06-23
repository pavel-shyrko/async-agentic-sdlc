import os
import re
import sys
import json
import uuid
import argparse
import asyncio
# subprocess: only fixed-argument `git` exec with no shell=True, never untrusted input as a command.
import subprocess  # nosec B404
from decimal import Decimal
from pathlib import Path
from typing import NoReturn
from dataclasses import dataclass

from src.shared.core.observability import log, reconfigure_logging
from src.shared.core.observability import log_finops_summary as _render_finops_summary
from src.shared.core.config import (
    check_environment, PIPELINE_APP_BUDGET_USD, PIPELINE_APP_BUDGET_FLOOR_USD,
    EFFECTIVE_BUDGET_USD, effective_budget_usd,
)
from src.shared.core.models import GlobalPipelineContext, WorkspacePaths, RUNS_BASE, BatchState, PipelineTelemetry
from src.shared.core.runs import Projects
from src.shared.core.environments import is_test_file, get_qa_profile
from src.shared.core.prompts import generate_repo_map
from src.shared.utils.git_helpers import get_git_root, get_pipeline_snapshot_files
from src.shared.utils.redaction import redact
from src.shared.utils.subprocess_helpers import sanitize_for_argv
from src.development.agents.techlead import run_techlead_node
from src.development.agents.qa import run_qa_agent_node
from src.development.agents.developer import run_developer_node
from src.development.agents.reviewer import run_reviewer_node
from src.development.agents.arbiter import run_arbiter_node
from src.development.agents.techwriter import run_techwriter_node
from src.development.gates import run_qa_unit_tests, run_security_scan, run_build_gate, run_test_compile_gate, build_failure_is_test_only, build_failure_is_environmental, run_lint_gate, classify_lint_findings, run_format_pass

# ==========================================
# CONTROL-FLOW SIGNALS
# ==========================================
class PipelineHalt(Exception):
    """Raised by ``_abort_with_incident`` when an FSM halt terminates a ticket run.

    Replaces a bare ``sys.exit(1)`` so the halt is *catchable*: the E3 batch loop catches it to record
    which ticket failed and stop cleanly, while every single-ticket path lets it propagate to the
    entrypoint guard in ``main.py`` (``except PipelineHalt: sys.exit(1)``) — preserving today's exit code.
    The incident report + FinOps are already persisted by ``_abort_with_incident`` before it raises.
    """


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
    push: bool = False
    idea: str | None = None  # Nexus Control Plane: raw idea string → starts a new project (planning run).
    file: str | None = None  # ticket file path; used to locate the sibling blueprint.md at runtime
    run_project: str | None = None    # --run <project>: execute a ticket under an existing project
    resume_project: str | None = None  # --resume <project> [N]: resume by project (+ optional run number)
    resume_number: str | None = None   # the optional NNN for --resume <project> <N>
    auto_execute: bool = False  # --idea --auto-execute: after planning, run the Executor for the first ticket
    auto_merge: bool = False  # --auto-merge: on success, open a PR into base_branch and squash-merge it (E2; implies push)
    scaffold_deploy: bool = False  # --scaffold-deploy: after a batch merges all tickets, generate + merge deploy manifests (E4)
    budget_usd: Decimal | None = None  # --budget: app-wide money ceiling override for this invocation (E5); None → PIPELINE_APP_BUDGET_USD


def parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(
        description="Antigravity SDLC Orchestrator — git-anchored, per-run isolated pipeline."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("description", nargs="?", help="Inline task description string.")
    group.add_argument("-f", "--file", help="Path to a file containing the task description.")
    parser.add_argument("--repo", help="Git URL or local path to the target repository (required for a fresh direct run / first --run of a project).")
    parser.add_argument("--ticket", help="Ticket ID or feature name; names the session and feat/ticket-<id> branch (direct run).")
    parser.add_argument("--base-branch", default="main", help="Base branch of the repository.")
    parser.add_argument("--budget", type=Decimal, metavar="USD",
                        help="Application-wide money ceiling (USD) for this invocation; overrides "
                             "PIPELINE_APP_BUDGET_USD. On a --resume, re-pass a larger value to add budget "
                             "and continue a batch that stopped on exhaustion (the ceiling is never "
                             "persisted — only the spend is).")
    parser.add_argument("--run", dest="run_project", metavar="PROJECT",
                        help="Execute a ticket under an existing project: --run <project> -f <ticket> (e.g. -f TASK-01).")
    parser.add_argument("--resume", nargs="+", metavar="TARGET",
                        help="Resume: a checkpoint JSON path, OR a project slug, OR a project slug + run number "
                             "(e.g. --resume my-proj 002). Project slug alone continues the latest Nexus run.")
    parser.add_argument("--reset-attempts", action="store_true", help="Reset circuit breaker counter on resume.")
    parser.add_argument("--push", action="store_true", help="Push the feature branch to origin after the atomic success commit.")
    parser.add_argument("--idea", help="Raw idea → start a NEW project and run the Nexus planning pipeline.")
    parser.add_argument("--auto-execute", action="store_true",
                        help="With --idea: after planning, drive the Executor over ALL planned tickets in "
                             "order (TASK-01→merge→TASK-02→…; E3). Requires --repo to clone, and IMPLIES "
                             "--auto-merge (hence --push) so each ticket lands on main before the next clones it.")
    parser.add_argument("--auto-merge", action="store_true",
                        help="On success, open a PR from feat/ticket-<id> into the base branch and squash-merge "
                             "it (E2). Implies --push; requires the gh CLI + GITHUB_TOKEN.")
    parser.add_argument("--scaffold-deploy", action="store_true",
                        help="After the batch merges ALL tickets, generate + merge a Dockerfile + GitHub "
                             "Actions deploy workflow (GCP Cloud Run via WIF) for the finished app (E4). "
                             "Consumed only by the --auto-execute batch (or its --resume); requires the gh "
                             "CLI + GITHUB_TOKEN.")

    args = parser.parse_args()

    # --auto-merge needs the branch on origin before a PR can reference it, so it implies --push.
    push = args.push or args.auto_merge

    # --scaffold-deploy is consumed ONLY by the post-batch terminal phase (run_batch). On any non-batch
    # invocation it is inert — warn rather than silently ignore it.
    if args.scaffold_deploy and not (args.auto_execute or args.resume):
        log.warning("⚠️  --scaffold-deploy is consumed only by the --auto-execute batch (or its --resume); "
                    "it has no effect on this invocation.")

    # Nexus Control Plane: an idea starts a new project (planning run). --repo (optional) is captured
    # into the project so later `--run` ticket executions reuse it. With --auto-execute the engine drives
    # the Executor over ALL planned tickets once planning completes (E3). A multi-ticket batch is only
    # coherent if each ticket merges to main before the next clones it fresh, so --auto-execute IMPLIES
    # --auto-merge (hence --push) — scoped to this idea path only.
    if args.idea:
        auto_merge = args.auto_merge or args.auto_execute
        return RunConfig(
            description=None, base_branch=args.base_branch, resume=None, reset_attempts=False,
            idea=args.idea, repo=args.repo, push=(push or auto_merge), auto_execute=args.auto_execute,
            auto_merge=auto_merge, scaffold_deploy=args.scaffold_deploy, budget_usd=args.budget,
        )

    # Execute a ticket under an existing project: --run <project> -f <ticket>.
    if args.run_project:
        if not args.file:
            parser.error("--run requires -f <ticket> (the ticket id to execute, e.g. --run my-proj -f TASK-01)")
        return RunConfig(
            description=None, base_branch=args.base_branch, resume=None,
            reset_attempts=args.reset_attempts, push=push, auto_merge=args.auto_merge,
            run_project=args.run_project, ticket=args.file, repo=args.repo, budget_usd=args.budget,
        )

    # Resume: either an explicit checkpoint PATH (legacy, incl. old run_<uuid>), or a project slug
    # (+ optional run number). A token ending in .json or pointing at an existing file is a path.
    if args.resume:
        first = args.resume[0]
        if first.endswith(".json") or Path(first).exists():
            return RunConfig(
                description=None, base_branch=args.base_branch, resume=Path(first),
                reset_attempts=args.reset_attempts, push=push, auto_merge=args.auto_merge,
                budget_usd=args.budget,
            )
        return RunConfig(
            description=None, base_branch=args.base_branch, resume=None,
            reset_attempts=args.reset_attempts, push=push, auto_merge=args.auto_merge,
            resume_project=first, resume_number=(args.resume[1] if len(args.resume) > 1 else None),
            scaffold_deploy=args.scaffold_deploy, budget_usd=args.budget,
        )

    # Fresh DIRECT run: a target repo and ticket are mandatory for git-anchored bootstrapping.
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
        push=push,
        auto_merge=args.auto_merge,
        file=args.file,
        budget_usd=args.budget,
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
    # Strip control chars (notably NUL) from every arg — a corrupted glyph in an agent-authored commit
    # subject would otherwise make execvp raise "embedded null byte".
    safe_cmd = [sanitize_for_argv(c) for c in cmd]
    proc = await asyncio.create_subprocess_exec(
        *safe_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env,
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


async def bootstrap_session(cfg: RunConfig, run_dir: Path, branch: str | None = None) -> WorkspacePaths:
    """Isolates a run: shallow-clone the target repo, cut the feature branch, map the workspace.

    The caller owns ``run_dir`` (and has already re-anchored logging to it), so the run id is
    bound once, up front — no late binding. Produces ``run_dir/repo/`` (shallow clone on ``branch``,
    default ``feat/ticket-<ticket>``) and returns the mapped workspace paths. The E4 deploy-scaffolding
    phase passes ``branch="chore/devops-scaffold"`` to land on a chore branch instead.
    """
    repo_dir = run_dir / "repo"
    run_dir.mkdir(parents=True, exist_ok=True)
    log.info(f"🌱 Bootstrapping session at {run_dir}")

    # Atomic shallow clone (single subprocess, HEAD only) — origin is configured automatically.
    # Network op: bounded by GIT_NETWORK_TIMEOUT so a credential prompt can never hang the run.
    await _run_checked(["git", "clone", "--depth", "1", cfg.repo, str(repo_dir)], "git clone", timeout=GIT_NETWORK_TIMEOUT)

    branch = branch or f"feat/ticket-{cfg.ticket}"
    await _run_checked(["git", "-C", str(repo_dir), "checkout", "-b", branch], "git checkout -b")

    # Force a LOCAL ref for the base branch via an explicit refspec (<base>:<base>) so the snapshot diff
    # `git diff --cached <base_branch>` resolves it — a bare fetch lands only in FETCH_HEAD. Done AFTER
    # the feature-branch checkout: git refuses to fetch into the still-checked-out default branch.
    await _run_checked(
        ["git", "-C", str(repo_dir), "fetch", "--depth", "1", "origin", f"{cfg.base_branch}:{cfg.base_branch}"],
        "git fetch base branch", timeout=GIT_NETWORK_TIMEOUT,
    )
    log.info(f"   [GIT] Shallow-cloned {redact(cfg.repo)} -> {repo_dir} (branch: {branch})")

    return WorkspacePaths.for_run(run_dir, repo_dir)


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


def _commit_subject(ctx: GlobalPipelineContext) -> str:
    """The conventional-commit subject ``feat(<ticket>): <summary>`` — single source of truth reused
    for the atomic commit AND the auto-merge PR title (E2)."""
    desc = (ctx.pr_description or "").strip()
    summary = next((line.strip() for line in desc.splitlines() if line.strip()), "") if desc else ""
    # First line is often a markdown heading (`# Title`) — strip the leading hashes/space so the
    # conventional-commit subject reads cleanly (e.g. "feat(T-01): Repository initialization …").
    summary = summary.lstrip("#").strip()
    summary = (summary or ctx.ticket or "automated change")[:72]
    return f"feat({ctx.ticket or 'ticket'}): {summary}"


async def finalize_transaction(ctx: GlobalPipelineContext, push: bool = False) -> None:
    """Commits the staged delta atomically on full success; optionally pushes the branch.

    Agents only stage into the index across cycles; this is the single transactional commit so the
    ``feat/ticket-<id>`` branch never accrues intermediate self-healing commits.
    """
    repo_root = await get_git_root(str(ctx.workspace_paths.repo_dir))

    if not await _has_staged_changes(repo_root):
        log.warning("🟡 No staged changes in the index — skipping final commit.")
        return

    subject = _commit_subject(ctx)

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


def _pr_body(ctx: GlobalPipelineContext) -> str:
    """PR body: the clean ticket description + a gate/FinOps footer (the engine ran the checks locally)."""
    desc = (ctx.pr_description or "").strip() or (ctx.ticket or "Automated change.")
    return (f"{desc}\n\n---\n🤖 Automated by the SDLC engine — all validation gates passed locally.\n"
            f"FinOps: {_finops_subtotals(ctx)}.")


async def finalize_pr(ctx: GlobalPipelineContext, cfg: RunConfig, head_branch: str | None = None) -> None:
    """E2: open a PR for the just-pushed feature branch and squash-merge it into ``cfg.base_branch``.

    Runs only on the success path, AFTER ``finalize_transaction`` has committed and pushed the branch
    (``--auto-merge`` implies ``--push``). Idempotent on ``--resume`` (reuses an open PR / skips an
    already-merged one). Approval is best-effort; a genuine merge failure exits non-zero so the operator
    sees the loop didn't close. Provider-agnostic via ``src.shared.utils.forge`` (GitHub-first via gh).
    ``head_branch`` defaults to ``feat/ticket-<ticket>``; the E4 deploy-scaffolding phase passes
    ``chore/devops-scaffold`` so it lands the same way through the forge seam (never a raw push to main).
    """
    from src.shared.utils.forge import open_pr, approve_pr, merge_pr
    head_branch = head_branch or f"feat/ticket-{ctx.ticket}"
    repo_dir = ctx.workspace_paths.repo_dir
    pr = await open_pr(repo_dir, head_branch, cfg.base_branch, _commit_subject(ctx), _pr_body(ctx))
    if pr is None:
        return  # already merged — idempotent skip
    await approve_pr(repo_dir, pr)        # best-effort; needs a separate GITHUB_REVIEWER_TOKEN
    await merge_pr(repo_dir, pr)
    log.info(f"✅ Closed the loop: {head_branch} squash-merged into {cfg.base_branch}.")


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
    # The ticket's environment_id drives the language-aware test-file predicate so COLOCATED tests
    # (Go `*_test.go`, Node `*.test.ts`, .NET `*Tests.cs`) are excluded too — not just Python `test_*.py`.
    env_id = ctx.contract.environment_id if ctx.contract else None
    # Separate-layout stacks (python) keep tests under the profile's `test_root` (e.g. `tests/`); that
    # prefix is excluded from the production snapshot. Colocated stacks have no root (test_root=None) —
    # their tests are excluded by the language-aware is_test_file predicate instead.
    test_root = get_qa_profile(env_id).get("test_root") if env_id else None
    test_prefix = f"{test_root}/" if test_root else None

    # 1. Stage every mutation so the index reflects the complete working-tree state across ALL cycles.
    subprocess.run(["git", "add", "-A"], cwd=str(repo_dir), check=True)  # nosec B603 B607 — fixed git argv, no shell

    # 1b. Capture the cumulative unified diff vs base — the Reviewer's authoritative scope-of-change,
    #     so it can separate the Developer's actual edits from pre-existing legacy code in the same file.
    diff_cmd = subprocess.run(  # nosec B603 B607 — fixed git argv, no shell
        ["git", "diff", "--cached", ctx.base_branch],
        cwd=str(repo_dir), capture_output=True, text=True, check=True,
    )
    ctx.production_code_diff = diff_cmd.stdout

    # 2. Read the cumulative index-vs-base delta. -z emits raw NUL-terminated paths (no quoting of
    #    spaces/newlines/unicode) — split on NUL.
    listing = subprocess.run(  # nosec B603 B607 — fixed git argv, no shell
        ["git", "diff", "--name-only", "--cached", "-z", ctx.base_branch],
        cwd=str(repo_dir), capture_output=True, text=True, check=True,
    )

    snapshot: dict[str, str] = {}
    for rel in listing.stdout.split('\0'):
        rel = rel.strip()
        if not rel:
            continue
        # Domain purity: QA-generated tests belong to test_code_snapshot, never the production one.
        # Exclude both a separate tests dir AND colocated test files (language-aware predicate).
        if (test_prefix and rel.startswith(test_prefix)) or (env_id and is_test_file(env_id, rel)):
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
QA_GATE_MAX_REROUTES = 2        # free QA regenerations on a test-compile failure (Reviewer bypassed)
QA_LINT_MAX_REROUTES = 2        # free QA regenerations on a contract-signature lint hit (Reviewer bypassed)
# Free fast-fail reroutes on a STYLE/LINT-gate failure (run_lint_gate) before lint folds into the budgeted
# cycle. prod findings → Developer, test findings → QA; Reviewer bypassed, no functional-retry consumed.
LINT_GATE_MAX_REROUTES = int(os.environ.get("PIPELINE_LINT_MAX_REROUTES", "2"))

# Framing wrapper prepended to lint-gate findings when seeding the Developer/QA channels — those prompts
# are tuned for compiler tracebacks/pytest failures, so raw ruff/gofmt/eslint/dotnet-format output is
# labelled as a style/lint task with an explicit "fix ONLY these, don't change behaviour" instruction.
_LINT_FEEDBACK_PREAMBLE = (
    "[LINT GATE FAILURE] The project's style/lint checker rejected the code. Fix ONLY these specific "
    "style/lint violations — do not change behaviour, signatures, or logic. The exact findings:\n"
)

# ==========================================
# FUNCTIONAL RETRY BUDGET + ARBITER (contract self-healing)
# ==========================================
MAX_FUNCTIONAL_RETRIES = int(os.environ.get("PIPELINE_MAX_RETRIES", "3"))   # outer cycle budget
ARBITER_TRIGGER_ATTEMPT = int(os.environ.get("ARBITER_TRIGGER_ATTEMPT", "2"))  # first cycle the Arbiter may run on failure
MAX_CONTRACT_AMENDMENTS = int(os.environ.get("MAX_CONTRACT_AMENDMENTS", "1"))  # autonomous contract rewrites per run (else halt)
AMENDMENT_RETRY_BONUS = int(os.environ.get("ARBITER_AMENDMENT_RETRY_BONUS", "2"))  # extra cycles granted to an amended contract


def _missing_contract_files(ctx: GlobalPipelineContext) -> list[str]:
    """Contracted production files the Developer was supposed to create but didn't.

    The Developer tends to skip non-code artifacts (`.gitignore`, `LICENSE`) even though they are in
    `files_to_modify`, and nothing else enforces their presence. Checks the working tree directly
    (independent of the snapshot's `.gitignore` filter); test files are QA-owned and excluded.
    """
    if not ctx.contract or not ctx.contract.files_to_modify:
        return []
    repo_dir = ctx.workspace_paths.repo_dir
    env_id = ctx.contract.environment_id
    return [
        f for f in ctx.contract.files_to_modify
        if not is_test_file(env_id, f) and not (repo_dir / f).exists()
    ]


def _misplaced_contract_files(ctx: GlobalPipelineContext, missing: list[str]) -> dict[str, str]:
    """Map each still-missing contracted path → a same-basename file that DOES exist elsewhere.

    The Developer sometimes honors the contract's CONTENT but invents a layout (e.g. nests a
    contracted root file under `src/`), so `_missing_contract_files` flags the contracted path as
    absent while the file actually sits at an alternate path. Surfacing that alternate path turns a
    blind 'create it now' reroute (which loops forever — the Developer thinks it already did) into a
    precise 'MOVE it' instruction. Conservative basename match only; first hit wins.
    """
    repo_dir = ctx.workspace_paths.repo_dir
    found: dict[str, str] = {}
    for f in missing:
        target = Path(f).as_posix()
        for cand in repo_dir.rglob(Path(f).name):
            if not cand.is_file() or ".git" in cand.parts:
                continue
            rel = cand.relative_to(repo_dir).as_posix()
            if rel != target:
                found[f] = rel
                break
    return found


def _format_contract_correction(misplaced: dict[str, str], absent: list[str]) -> str:
    """Build a Developer-targeted correction that distinguishes a wrong PATH from a wrong/absent FILE.

    Shared by the in-loop reroute and the hard-halt incident so both speak with one voice.
    """
    lines: list[str] = []
    if misplaced:
        lines.append(
            "You created the following contracted file(s) at the WRONG path. MOVE each to its exact "
            "contracted path (repo-root-relative) and leave NO copy behind:"
        )
        lines += [f"  - `{found}` → must be `{contracted}`" for contracted, found in misplaced.items()]
    if absent:
        lines.append(
            "You did not create these contracted files — create EACH of them now with the literal "
            f"content required by the ticket: {', '.join(absent)}"
        )
    return "\n".join(lines)


# ``Type.Method(`` (static call) vs ``new Type().Method(`` / ``new Type {…}.Method(`` (instance call).
# Conservative, language-light: catches the exact contradiction observed in the wild (a QA suite that
# invoked the same symbol both ways across files), without trying to parse arbitrary test source.
_STATIC_CALL_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_INSTANCE_CALL_RE = re.compile(r"\bnew\s+([A-Z][A-Za-z0-9_]*)\s*[\(\{][^;]*?\)\s*\.([A-Za-z_][A-Za-z0-9_]*)\s*\(")


def lint_test_suite_consistency(test_snapshot: str, function_signatures: str) -> list[str]:
    """Flag UNAMBIGUOUS self-contradictions in the generated test suite (Reviewer-bypass gate).

    Currently one rule: the same ``Type.Method`` symbol is called both statically AND as an instance
    member within the same snapshot — a contract-signature contradiction that otherwise compiles
    halfway and burns a full QA→Reviewer cycle. Returns one human-readable issue string per offending
    symbol, or [] when the suite is internally consistent. ``function_signatures`` is accepted for
    future signature-aware checks; today only intra-suite consistency is enforced (keeps it low-flake).
    """
    if not test_snapshot:
        return []
    static_calls = {(t, m) for t, m in _STATIC_CALL_RE.findall(test_snapshot)}
    instance_calls = {(t, m) for t, m in _INSTANCE_CALL_RE.findall(test_snapshot)}
    conflicts = sorted(static_calls & instance_calls)
    return [
        f"`{t}.{m}(...)` is called both as a STATIC member and via `new {t}().{m}(...)` — pick the one "
        "matching the contract signature and use it consistently across the whole suite."
        for t, m in conflicts
    ]


# ==========================================
# RUNNER-LOG FORWARDING (Reviewer feed, context pruning)
# ==========================================
FEEDBACK_TAIL_LINES = 50        # budget for runner lines fed forward to the Reviewer (context pruning)
FEEDBACK_MAX_CHARS = 8000       # hard cap on any failure text injected into an agent prompt
# Lead-ins that mark the ORIGIN of a failure. The root ImportError/Traceback can sit far above the
# final summary, so a plain tail slice would drop it — the extractor keeps an error-origin head too.
_TRACEBACK_MARKERS = (
    "Traceback (most recent call",
    "ImportError",
    "ModuleNotFoundError",
    "cannot import name",
    "ERROR:",
    "FAILED",
)


def _extract_failure_context(lines: list[str], max_lines: int = FEEDBACK_TAIL_LINES) -> str:
    """Marker-aware slice that guarantees the root error reaches the Reviewer.

    A bare tail slice can drop the root ``ImportError``/``Traceback`` when it sits above a long stack
    or many ``_FailedTest`` entries. So when the log overflows the budget we keep BOTH an error-origin
    head window (anchored at the first traceback/import marker) AND the final summary tail, separated
    by a snip marker. With no marker present we fall back to a plain tail (failures live at the end).
    """
    if len(lines) <= max_lines:
        return "\n".join(lines)
    half = max_lines // 2
    first = next(
        (i for i, line in enumerate(lines) if any(m in line for m in _TRACEBACK_MARKERS)),
        None,
    )
    if first is None:
        return "\n".join(lines[-max_lines:])
    head = lines[first:first + half]
    tail = lines[-half:]
    return "\n".join([*head, "…[snip]…", *tail])


def _cap_text(text: str, max_chars: int = FEEDBACK_MAX_CHARS) -> str:
    """Hard-cap any failure text injected into an agent prompt (head + tail kept)."""
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return f"{text[:half]}\n…[truncated]…\n{text[-half:]}"


# Language-agnostic comment lead-ins. ''' is added beyond the spec list so a Python single-quote module
# docstring (a valid justification) isn't flagged as undocumented; '<!--' covers XML-family files
# (.csproj / .xml / .html) whose only valid comment syntax the scanner would otherwise miss.
_COMMENT_PREFIXES = ("#", "//", "/*", "*", '"""', "'''", "<!--")
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
    # A misplaced contracted file (e.g. `src/X` for contracted `X`) is owned by the missing-contract
    # reroute, which gives the Developer a precise 'MOVE it' instruction. Excluding its basename here
    # keeps the guardrail from mislabelling it as 'uncontracted glue needing justification' — the two
    # checks must never describe the same file by two contradictory paths.
    missing_basenames = {Path(f).name for f in _missing_contract_files(ctx)}
    # Uncontracted glue the Developer created (e.g. an entry point a build manifest needs) is policed
    # here like on any code ticket: it just needs a top-of-file justification comment, not deletion.
    uncontracted = [
        rel for rel in ctx.production_code_snapshot
        if Path(rel).as_posix() not in contract_files and Path(rel).name not in missing_basenames
    ]
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


def enforce_financial_circuit_breaker(ctx: GlobalPipelineContext, budget_usd: Decimal) -> None:
    """Financial Circuit Breaker: hard-halt the FSM once spend breaches the budget (money-only, E5).

    The sole gate is USD spend (authoritative for Claude, estimated for Gemini) — tokens are reported but
    NOT a ceiling (gating on money keeps the breaker honest even when the agentic CLI's cheap cache reads
    inflate the raw token count). ``budget_usd`` is the EFFECTIVE ceiling for THIS ticket: on a batch it is
    the remaining application budget (``app_budget − spent``) threaded in by ``run_batch``; on a single-ticket
    path it is the full app budget. Checked after every cost-accruing node so a pathological retry loop
    cannot drain the API budget. Reuses the incident machinery — ``incident_report.json`` carries the full
    per-agent telemetry breakdown for audit. The ticket's spend is persisted in the checkpoint, so the
    ceiling is enforced consistently across ``--resume``.
    """
    tel = ctx.telemetry
    if tel.total_cost_usd >= budget_usd:
        _abort_with_incident(
            ctx,
            f"\n🚨 FINANCIAL CIRCUIT BREAKER OPEN: cumulative spend ${tel.total_cost_usd:.4f} "
            f"≥ budget ${budget_usd:.4f}. Halting before further spend.",
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
    """Persist the cumulative FinOps breakdown to ``reports/finops_report.json`` (money-only, E5)."""
    report_file = ctx.workspace_paths.reports_dir / "finops_report.json"
    report_file.parent.mkdir(parents=True, exist_ok=True)
    with open(report_file, "w", encoding="utf-8") as f:
        # default=str serialises Decimal money as exact strings (json can't encode Decimal natively).
        json.dump(
            ctx.telemetry.finops_report(effective_budget_usd()),
            f, indent=2, default=str,
        )
    log.debug(f"FinOps report written to {report_file}")


def log_finops_summary(ctx: GlobalPipelineContext) -> None:
    """Print the end-of-run GRAND TOTAL block against the app budget. Thin wrapper over the
    shared telemetry-first renderer (also used by the Nexus control plane) so the block is identical."""
    _render_finops_summary(ctx.telemetry, effective_budget_usd())


def _abort_with_incident(ctx: GlobalPipelineContext, header: str) -> NoReturn:
    """Logs a terminal header, persists the full context as an incident report, and raises PipelineHalt.

    Raises ``PipelineHalt`` rather than calling ``sys.exit(1)`` directly so the halt is catchable: the
    E3 batch loop records the failed ticket and stops cleanly, while single-ticket paths let it bubble to
    the ``main.py`` entrypoint guard (which converts it to exit 1). The incident report + FinOps are
    persisted here, BEFORE raising, so spend stays auditable on a halt exactly as before.
    """
    log.error(header)
    incident_file = str(ctx.workspace_paths.reports_dir / "incident_report.json")
    with open(incident_file, "w", encoding="utf-8") as f:
        f.write(redact(ctx.model_dump_json(indent=2)))  # never persist secrets into a shared report
    log.error(f"  └── Incident report written to {incident_file}")
    log.debug(f"Final Incident Context Dump: {ctx.model_dump_json(indent=2)}")
    # Always persist + surface the FinOps breakdown, even on a halt, so spend is auditable.
    write_finops_report(ctx)
    log_finops_summary(ctx)
    raise PipelineHalt(header)


# ==========================================
# MAIN ORCHESTRATOR
# ==========================================
def _run_dir_from_checkpoint(checkpoint: Path) -> Path:
    """Map a checkpoint path back to its run dir. Canonical layout is
    runs/run_<uuid>/reports/checkpoint.json, so the run dir is the checkpoint's grandparent; fall back
    to the checkpoint's own dir for a non-canonical path (so logs/ never escape ABOVE the repo)."""
    ckpt = checkpoint.resolve()
    return ckpt.parent.parent if ckpt.parent.name == "reports" else ckpt.parent


def _checkpoint_kind(checkpoint: Path) -> str | None:
    """Peek a checkpoint's ``kind`` discriminator to route --resume to the right plane. Nexus
    checkpoints carry ``kind="nexus"``; the executor's have none → returns None (→ executor path).
    Never raises — a missing/garbage file just routes to the executor."""
    try:
        return json.loads(checkpoint.read_text(encoding="utf-8")).get("kind")
    except Exception:
        return None


def _resolve_ticket_file(projects: Projects, slug: str, ticket: str) -> Path | None:
    """Locate a ticket's markdown in the project's LATEST Nexus run artifacts (accepts ``TASK-01`` or
    ``TASK-01.md``). Returns None if the project has no planning run or the ticket isn't there."""
    nexus_run = projects.latest_run(slug, plane="nexus")
    if nexus_run is None:
        return None
    name = ticket if ticket.endswith(".md") else f"{ticket}.md"
    cand = nexus_run / "artifacts" / name
    return cand if cand.exists() else None


def _batch_state_path(nexus_run_dir: Path) -> Path:
    """The E3 batch sidecar lives beside the Nexus planning checkpoint (reports/batch_state.json)."""
    return nexus_run_dir / "reports" / "batch_state.json"


def _load_or_init_batch(nexus_run_dir: Path, project, tickets: list[str]) -> BatchState:
    """Load the batch checkpoint for this Nexus run (resume) or mint a fresh one (first batch)."""
    path = _batch_state_path(nexus_run_dir)
    if path.exists():
        batch = BatchState.load_checkpoint(path)
        # Re-pin the ticket snapshot in case the plan was re-materialized; keep prior `completed`.
        batch.tickets = tickets
        return batch
    return BatchState(project_slug=project.slug, nexus_run=nexus_run_dir.name, tickets=tickets)


def _telemetry_from_state_dump(path: Path) -> PipelineTelemetry | None:
    """Best-effort load of a ``PipelineTelemetry`` from a run's ``checkpoint.json`` / ``incident_report.json``.

    Both are full state dumps (``GlobalPipelineContext`` / ``NexusState``) carrying a ``telemetry`` sub-object,
    so the E3 batch can recover a finished/halted run's spend to fold into the application-wide total even
    when ``run_executor`` raised instead of returning. Returns ``None`` if the file/field is absent or
    unreadable (the spend is simply not folded — a degraded report beats a crash)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        tel = data.get("telemetry")
        return PipelineTelemetry.model_validate(tel) if tel else None
    except Exception as e:  # pragma: no cover - best-effort recovery path
        log.debug(f"Could not recover telemetry from {path}: {e}")
        return None


def write_app_finops_report(nexus_run_dir: Path, app_telemetry: PipelineTelemetry, budget_usd: Decimal) -> None:
    """Persist the APPLICATION-wide FinOps breakdown (Nexus + every ticket + DevOps) to
    ``reports/app_finops_report.json`` in the Nexus run dir. Best-effort: a reporting hiccup must never
    mask the real batch outcome (mirrors the executor/Nexus per-run reporters)."""
    try:
        report_file = nexus_run_dir / "reports" / "app_finops_report.json"
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(
            json.dumps(app_telemetry.finops_report(budget_usd), indent=2, default=str), encoding="utf-8"
        )
        log.debug(f"App-wide FinOps report written to {report_file}")
    except Exception as e:  # pragma: no cover - best-effort
        log.debug(f"Failed to write app_finops_report.json: {e}")


async def run_batch(projects: Projects, project, cfg: RunConfig, nexus_run_dir: Path,
                    tickets: list[str]) -> None:
    """E3 + E5: drive the Executor over ALL planned tickets in TPM order under ONE application budget.

    Each ticket clones ``main`` FRESH, so correctness hinges on E2 merging it before the next ticket's
    clone — ``--auto-execute`` implies ``--auto-merge``, so every ``run_executor`` here merges on success.
    Progress is checkpointed to ``reports/batch_state.json`` so a mid-batch halt resumes from the failed
    ticket without redoing merged ones (failure policy: stop on the first unrecoverable halt, exit 1).

    E5 — a single money ceiling (``--budget`` or ``PIPELINE_APP_BUDGET_USD``) governs the whole build. The
    Nexus planning spend and every finished ticket's telemetry are merged into ``batch.app_telemetry`` (so the
    running total survives ``--resume``); before each ticket the REMAINING budget is threaded into
    ``run_executor`` as that ticket's breaker ceiling. When the remaining budget falls below the floor the
    batch stops cleanly (records a ``budget_marker``) before spending more. The ceiling is re-resolved every
    call and never persisted, so re-passing a larger ``--budget`` on a ``--resume`` "adds money" and continues.
    The application-wide FinOps report is written in a ``finally`` so it persists on ANY exit — clean finish,
    a ticket/DevOps ``PipelineHalt``, or a budget stop — always reflecting the cumulative spend.
    """
    batch = _load_or_init_batch(nexus_run_dir, project, tickets)
    batch_path = _batch_state_path(nexus_run_dir)
    app_budget = cfg.budget_usd if cfg.budget_usd is not None else PIPELINE_APP_BUDGET_USD

    # Fold the Nexus planning spend into the application total ONCE (guarded so a --resume never double-counts).
    if not batch.nexus_merged:
        nexus_tel = _telemetry_from_state_dump(nexus_run_dir / "reports" / "checkpoint.json")
        if nexus_tel is not None:
            batch.app_telemetry.merge(nexus_tel)
        batch.nexus_merged = True
        batch.save_checkpoint(batch_path)

    log.info(f"🔁 Batch: {len(batch.completed)}/{len(tickets)} already merged; "
             f"spent ${batch.app_telemetry.total_cost_usd:.4f} / ${app_budget:.2f} app budget.")
    try:
        for ticket in tickets:
            if ticket in batch.completed:
                log.info(f"⏭️  Batch: '{ticket}' already merged — skipping.")
                continue

            # E5 — gate the NEXT ticket on the remaining application budget BEFORE spending anything on it.
            remaining = app_budget - batch.app_telemetry.total_cost_usd
            if remaining <= PIPELINE_APP_BUDGET_FLOOR_USD:
                batch.budget_marker = (
                    f"App budget exhausted before '{ticket}': spent "
                    f"${batch.app_telemetry.total_cost_usd:.4f} of ${app_budget:.2f}; "
                    f"${remaining:.4f} remaining ≤ floor ${PIPELINE_APP_BUDGET_FLOOR_USD}."
                )
                batch.save_checkpoint(batch_path)
                log.error(f"🛑 {batch.budget_marker} {len(batch.completed)}/{len(tickets)} merged. "
                          f"Add budget and continue with "
                          f"`--resume {project.slug} --budget <usd>`.")
                sys.exit(1)
            batch.budget_marker = None  # a continuing batch clears any stale exhaustion marker

            run_dir = prepare_ticket_run(projects, project, cfg, ticket)
            if run_dir is None:
                batch.failed = ticket
                batch.save_checkpoint(batch_path)
                log.error(f"🛑 Batch: ticket '{ticket}' not found in the Nexus artifacts — stopping. "
                          f"Resume with `--resume {project.slug}` after fixing the plan.")
                sys.exit(1)
            log.info(f"🤖 Batch: dispatching '{ticket}' ({len(batch.completed) + 1}/{len(tickets)}) "
                     f"| ${remaining:.4f} of the app budget remaining.")
            try:
                ctx = await run_executor(cfg, run_dir, budget_usd_ceiling=remaining)
            except PipelineHalt:
                # Recover the halted ticket's spend (incident dump is freshest; checkpoint is the fallback)
                # so the application total — and the app report below — still reflect the money it burned.
                failed_tel = (_telemetry_from_state_dump(run_dir / "reports" / "incident_report.json")
                              or _telemetry_from_state_dump(run_dir / "reports" / "checkpoint.json"))
                if failed_tel is not None:
                    batch.app_telemetry.merge(failed_tel)
                batch.failed = ticket
                batch.save_checkpoint(batch_path)
                log.error(f"🛑 Batch halted at '{ticket}'; {len(batch.completed)}/{len(tickets)} merged. "
                          f"Incident written in {run_dir.name}. Resume with `--resume {project.slug}`.")
                sys.exit(1)

            batch.app_telemetry.merge(ctx.telemetry)  # fold this ticket's spend into the running total
            batch.completed.append(ticket)
            batch.failed = None
            batch.save_checkpoint(batch_path)
        log.info(f"🏁 Batch complete: all {len(tickets)} ticket(s) merged into {cfg.base_branch}. "
                 f"Spent ${batch.app_telemetry.total_cost_usd:.4f} / ${app_budget:.2f}.")

        # E4 — once every ticket has merged, optionally scaffold deploy config for the finished app. Reached
        # only on a fully-merged batch: a mid-batch halt sys.exit(1)s above, so an incomplete app is never
        # scaffolded. Covers both --idea --auto-execute and the bare --resume re-entry (both call run_batch).
        if cfg.scaffold_deploy:
            # Lazy import: scaffold.py imports the transaction/forge/incident/FinOps SSOTs from THIS module,
            # so importing it at module top would form a deployment→nexus cycle. Deferring to call time (the
            # same pattern main() uses for nexus_runner) lets nexus.runner finish loading first.
            from src.deployment.provision.scaffold import run_devops_scaffold
            devops_remaining = app_budget - batch.app_telemetry.total_cost_usd
            # run_devops_scaffold merges its ctx.telemetry into batch.app_telemetry in its OWN finally, so a
            # budget halt mid-self-heal still records the partial DevOps spend here. A PipelineHalt propagates
            # to the main.py guard; the outer finally below persists the app report either way.
            await run_devops_scaffold(projects, project, cfg, nexus_run_dir,
                                      budget_usd_ceiling=devops_remaining, app_telemetry=batch.app_telemetry)
    finally:
        # Always persist the application-wide spend + report, regardless of how the batch exits.
        batch.save_checkpoint(batch_path)
        write_app_finops_report(nexus_run_dir, batch.app_telemetry, app_budget)
        _render_finops_summary(batch.app_telemetry, app_budget)


def prepare_ticket_run(projects: Projects, project, cfg: RunConfig, ticket_id: str) -> Path | None:
    """Wire ``cfg`` for one project ticket and allocate its executor run dir.

    Sets ``cfg.repo`` (from the project when not overridden), ``base_branch``, ``ticket``, ``file`` and
    ``description`` (the ticket BODY, like a normal ``-f`` run — ``cfg.file`` is kept so the sibling
    ``blueprint.md`` is routed into the TechLead brief). Returns ``None`` WITHOUT allocating when the
    ticket markdown can't be resolved in the project's latest Nexus run. Shared by ``--run`` and
    ``--idea --auto-execute``.
    """
    cfg.repo = cfg.repo or project.repo
    cfg.base_branch = project.base_branch
    cfg.ticket = ticket_id
    ticket_file = _resolve_ticket_file(projects, project.slug, ticket_id)
    if ticket_file is None:
        return None
    cfg.file = str(ticket_file)
    cfg.description = ticket_file.read_text(encoding="utf-8")
    return projects.allocate(project.slug, "exec", ticket_id)


async def main():
    cfg = parse_args()
    # Publish the app-wide ceiling so the FinOps GRAND TOTAL renders against the real --budget (not the
    # module default). None (no --budget) → effective_budget_usd() falls back to PIPELINE_APP_BUDGET_USD.
    # run_executor later overrides this with each ticket's remaining ceiling. Never persisted (ADR 0022).
    EFFECTIVE_BUDGET_USD.set(cfg.budget_usd)
    projects = Projects(RUNS_BASE)

    # ---- Nexus planning: a fresh idea starts a NEW project (its --repo, if any, is captured for the
    # later --run ticket executions). Branch BEFORE check_environment so the docker/claude/bandit
    # requirements never block the lightweight control plane. ----
    if cfg.idea:
        from src.nexus.nexus_runner import run_nexus, get_tasks_for_nexus_run
        # Fail fast: when we WILL auto-execute, the executor's docker/claude/bandit deps must be present
        # before we spend planning tokens. Plain planning skips this (control plane needs only Gemini).
        if cfg.auto_execute:
            check_environment(require_forge=cfg.auto_merge)
        project = projects.create(cfg.idea, idea=cfg.idea, repo=cfg.repo, base_branch=cfg.base_branch)
        nexus_run_dir = projects.allocate(project.slug, "nexus", "plan")
        reconfigure_logging(nexus_run_dir / "logs")
        log.info(f"🗂️  Project '{project.slug}' (new) → {nexus_run_dir.name}")
        out = await run_nexus(cfg.idea, run_dir=nexus_run_dir)
        log.info(f"✅ Nexus complete → {out.resolve()}")

        # E3 — auto-dispatch the Executor over ALL planned tickets in order. Planning has SUCCEEDED, so
        # every skip below is a clean exit (nothing to execute ≠ failure); only a real executor halt exits 1.
        if not cfg.auto_execute:
            return
        if not project.repo:
            log.warning(f"⏭️  --auto-execute skipped: project '{project.slug}' has no --repo to clone. "
                        f"Planning output is ready — run `--run {project.slug} -f <ticket>` with a repo.")
            return
        tickets = get_tasks_for_nexus_run(nexus_run_dir)
        if not tickets:
            log.warning("⏭️  --auto-execute skipped: the Nexus run produced no tickets.")
            return
        log.info(f"🤖 --auto-execute: driving the Executor over all {len(tickets)} planned ticket(s) "
                 f"to {cfg.base_branch}, in order.")
        await run_batch(projects, project, cfg, nexus_run_dir, tickets)
        return

    # ---- Resolve a resume target → (run_dir, checkpoint). Either a project slug (+ optional run
    # number; bare slug continues the latest Nexus run) or an explicit checkpoint path (legacy). ----
    resume_checkpoint: Path | None = None
    run_dir: Path | None = None
    if cfg.resume_project:
        if not projects.exists(cfg.resume_project):
            log.error(f"🚨 Unknown project '{cfg.resume_project}' (no runs/{cfg.resume_project}/project.json).")
            sys.exit(1)
        if cfg.resume_number:
            run_dir = projects.run_by_number(cfg.resume_project, cfg.resume_number)
            if run_dir is None:
                log.error(f"🚨 Project '{cfg.resume_project}' has no run #{cfg.resume_number}.")
                sys.exit(1)
        else:
            run_dir = projects.latest_run(cfg.resume_project, plane="nexus")
            if run_dir is None:
                log.error(f"🚨 Project '{cfg.resume_project}' has no Nexus run to continue.")
                sys.exit(1)
            # E3 — a bare `--resume <project>` re-enters an in-progress multi-ticket batch (if one was
            # started) rather than re-planning. The batch sidecar lives beside the Nexus checkpoint;
            # run_batch skips already-merged tickets and re-runs the failed one against the latest main.
            if _batch_state_path(run_dir).exists():
                from src.nexus.nexus_runner import get_tasks_for_nexus_run
                project = projects.load(cfg.resume_project)
                cfg.repo = cfg.repo or project.repo
                cfg.base_branch = project.base_branch
                cfg.auto_merge = cfg.push = True  # a batch always merges each ticket to base
                check_environment(require_forge=True)
                reconfigure_logging(run_dir / "logs")
                log.info(f"🔁 Resuming the multi-ticket batch for project '{project.slug}'.")
                await run_batch(projects, project, cfg, run_dir, get_tasks_for_nexus_run(run_dir))
                return
        resume_checkpoint = run_dir / "reports" / "checkpoint.json"
    elif cfg.resume:
        resume_checkpoint = cfg.resume
        run_dir = _run_dir_from_checkpoint(resume_checkpoint)

    # ---- A Nexus-kind checkpoint resumes the control plane, not the executor ----
    if resume_checkpoint is not None and _checkpoint_kind(resume_checkpoint) == "nexus":
        from src.nexus.nexus_runner import run_nexus
        reconfigure_logging(run_dir / "logs")
        out = await run_nexus(resume=resume_checkpoint)
        log.info(f"✅ Nexus complete → {out.resolve()}")
        return

    # ---- Executor: a fresh run allocates a numbered dir under its project; resume reuses run_dir. ----
    if resume_checkpoint is None:
        if cfg.run_project:
            if not projects.exists(cfg.run_project):
                log.error(f"🚨 Unknown project '{cfg.run_project}' — run --idea first to create it.")
                sys.exit(1)
            project = projects.load(cfg.run_project)
            if not (cfg.repo or project.repo):
                log.error(f"🚨 Project '{project.slug}' has no repo recorded — pass --repo once on a --run.")
                sys.exit(1)
            run_dir = prepare_ticket_run(projects, project, cfg, cfg.ticket)
            if run_dir is None:
                log.error(f"🚨 Ticket '{cfg.ticket}' not found in project '{project.slug}' Nexus artifacts.")
                sys.exit(1)
        else:
            # Fresh DIRECT run: group it under a project keyed by the ticket slug (reused on re-runs).
            project = projects.get_or_create(cfg.ticket, repo=cfg.repo, base_branch=cfg.base_branch)
            run_dir = projects.allocate(project.slug, "exec", cfg.ticket)

    # Single-ticket paths (--run / legacy direct / --resume <project> <NNN>): the effective ceiling is the
    # full app budget (or --budget if given). run_executor defaults None → PIPELINE_APP_BUDGET_USD.
    await run_executor(cfg, run_dir, resume_checkpoint, budget_usd_ceiling=cfg.budget_usd)


async def run_executor(cfg: RunConfig, run_dir: Path, resume_checkpoint: Path | None = None,
                       budget_usd_ceiling: Decimal | None = None) -> GlobalPipelineContext:
    """Execute ONE ticket end-to-end in a prepared run dir: bootstrap (or resume) → TechLead → the FSM
    self-heal cycle → atomic success commit. Returns the final ``GlobalPipelineContext`` on full success (so
    the E3 batch can fold this ticket's telemetry into the application-wide total); a halt writes an incident
    report and raises ``PipelineHalt`` (via ``_abort_with_incident``) — caught by the E3 batch loop, or
    converted to exit 1 by the ``main.py`` guard on single-ticket paths. Shared by the direct
    ``--run``/resume paths and ``--idea --auto-execute`` (E1/E3).

    ``budget_usd_ceiling`` is the EFFECTIVE money ceiling for this ticket (E5): on a batch it is the
    remaining application budget threaded in by ``run_batch``; ``None`` (single-ticket paths) falls back to
    the full ``PIPELINE_APP_BUDGET_USD``. The breaker gates on money only — tokens are reported, not capped.
    """
    # Re-anchor the audit trail to THIS run's logs/ dir before any other log line is emitted.
    # Append mode keeps a resumed run's timeline linear in the SAME file instead of splitting it.
    reconfigure_logging(run_dir / "logs")
    check_environment(require_forge=cfg.auto_merge)
    budget_usd = budget_usd_ceiling if budget_usd_ceiling is not None else PIPELINE_APP_BUDGET_USD
    # Publish THIS ticket's effective ceiling (the remaining app budget on a batch) so its FinOps GRAND
    # TOTAL + any halt report render against the same number the breaker gates on. Never persisted.
    EFFECTIVE_BUDGET_USD.set(budget_usd)

    if resume_checkpoint is not None:
        log.info(f"▶️ RESUMING FSM EXECUTION FROM CHECKPOINT: {resume_checkpoint}")
        try:
            ctx = GlobalPipelineContext.load_checkpoint(resume_checkpoint)
            log.info(f"Loaded checkpoint from {resume_checkpoint}")
        except Exception as exc:
            log.error(f"🚨 Failed to load checkpoint '{resume_checkpoint}': {exc}")
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

        # Context routing: feed the architectural blueprint (sibling of the ticket file) into the
        # TechLead's input. TechLead is the SOLE router — it reads ticket + blueprint and distributes
        # all specs into the contract; the Developer never sees the blueprint directly. The CURRENT TASK
        # leads (it is the authoritative SCOPE of the contract); the blueprint is demoted to reference
        # so the TechLead does not mistake the whole-project topology for its file list (see techlead.md
        # Rule 0). LLMs anchor on the leading block — scope first, reference second.
        if cfg.file:
            blueprint_path = Path(cfg.file).parent / "blueprint.md"
            if blueprint_path.exists():
                bp_content = blueprint_path.read_text(encoding="utf-8")
                # Build the routing brief in a SEPARATE field — do NOT overwrite pr_description, which
                # stays the clean ticket text used for the commit subject / PR body. Leaking the
                # [CURRENT TASK …] header into pr_description is what produced the placeholder commit.
                ctx.techlead_brief = (
                    f"[CURRENT TASK — the authoritative scope of this contract]\n{ctx.pr_description}\n\n"
                    f"[ARCHITECTURAL BLUEPRINT — reference only; whole-project specs, NOT your file list]\n{bp_content}"
                )
                log.info(f"   [CONTEXT] Blueprint routed into TechLead input ({len(bp_content)} chars).")

        log.debug(f"Initialized global context for run {run_dir} with PR: {cfg.description}")

    checkpoint_file = ctx.workspace_paths.reports_dir / "checkpoint.json"

    # 1. Architecture Phase (executed once per session)
    if ctx.contract:
        log.info("Skipping TechLead node: contract already present in context.")
    else:
        await run_techlead_node(ctx)
        enforce_financial_circuit_breaker(ctx, budget_usd)
        ctx.save_checkpoint(checkpoint_file)
        log.debug(f"Checkpoint saved after TechLead node: {checkpoint_file}")

    regenerate_tests = ctx.needs_test_regeneration()

    # Outer functional-retry loop. The ceiling is dynamic: each autonomous contract amendment grants
    # AMENDMENT_RETRY_BONUS extra cycles so the re-derived contract gets a fair shot. Driven by the
    # persisted current_attempt + contract_amendments, so a --resume recomputes the same ceiling.
    while ctx.current_attempt <= MAX_FUNCTIONAL_RETRIES + ctx.contract_amendments * AMENDMENT_RETRY_BONUS:
        attempt = ctx.current_attempt
        max_cycles = MAX_FUNCTIONAL_RETRIES + ctx.contract_amendments * AMENDMENT_RETRY_BONUS
        log.info(f"🔷 Orchestration cycle {attempt}/{max_cycles}")
        log.debug(f"Starting orchestration cycle {attempt}")

        # Financial Circuit Breaker: halt immediately if a prior cycle (or a resumed run) is
        # already over budget, before spending any more tokens this cycle.
        enforce_financial_circuit_breaker(ctx, budget_usd)

        # Reset BOTH isolated feedback channels before a new cycle. The Developer reads only
        # `error_trace` (production-code fixes); QA reads only `qa_error_trace` (test fixes).
        prev_dev_trace = ctx.error_trace
        prev_qa_trace = ctx.qa_error_trace
        ctx.error_trace = ""
        ctx.qa_error_trace = ""

        # DAG bypass: skip the Developer on a test-only repair cycle — the Reviewer approved
        # production code (empty dev channel) but rejected the tests. Guarded by `review_report is
        # not None` so cycle 1 (no review yet) never skips the Developer that must write the code.
        skip_developer = regenerate_tests and not prev_dev_trace and ctx.review_report is not None

        # 2. Testing Phase (Runs initially, on rejected tests, or whenever no snapshot exists)
        if regenerate_tests:
            # Free-reroute the QA node on a contract-signature contradiction in the freshly generated
            # suite (e.g. the same symbol called both static and instance) BEFORE any Developer/Reviewer
            # spend — mirrors the test-compile gate. No functional-retry budget consumed; at the cap we
            # proceed and let the Reviewer adjudicate so a false positive never deadlocks the run.
            qa_lint_feedback = prev_qa_trace
            for qa_lint_retries in range(QA_LINT_MAX_REROUTES + 1):
                await run_qa_agent_node(ctx, qa_lint_feedback)
                lint_issues = lint_test_suite_consistency(
                    ctx.test_code_snapshot, ctx.contract.function_signatures
                )
                if not lint_issues or qa_lint_retries == QA_LINT_MAX_REROUTES:
                    if lint_issues:
                        log.warning("🔶 QA signature lint still failing after in-loop regenerations — handing to the Reviewer.")
                    break
                log.warning(
                    f"🔶 QA suite has contract-signature contradiction(s) — fast-fail regeneration "
                    f"{qa_lint_retries + 1}/{QA_LINT_MAX_REROUTES} to QA (no budget spent), Reviewer bypassed."
                )
                qa_lint_feedback = (
                    "The generated test suite contradicts the contract signatures. Fix ONLY the test "
                    "files:\n" + "\n".join(lint_issues)
                )
                enforce_financial_circuit_breaker(ctx, budget_usd)
            ctx.save_checkpoint(checkpoint_file)
            log.debug(f"Checkpoint saved after QA node: {checkpoint_file}")
            regenerate_tests = False  # Reset the flag until the next rejection
        elif ctx.test_code_snapshot:
            log.info("Skipping QA generation: validated test snapshot present in context.")

        # 3. Development Phase — Developer writes code, then the fast-fail documentation guardrail
        #    runs BEFORE the Reviewer. A miss free-reroutes to the Developer (NO functional-budget
        #    retry consumed) and bypasses the Reviewer; after GUARDRAIL_MAX_REROUTES fast-fail reroutes
        #    a still-undocumented file triggers a Hard Halt.
        if skip_developer:
            # Production code was approved last cycle; only the test suite is being regenerated.
            # The Developer (the dominant Claude cost) is skipped entirely. The prior cycle's
            # production_code_snapshot / production_code_diff (persisted) stay valid for the Reviewer.
            log.info("⏭️  DAG bypass: production code approved — regenerating tests only, Developer skipped.")
        else:
            dev_feedback = prev_dev_trace
            dev_focus_files: list[str] | None = None
            guardrail_halt = False
            guardrail_msg: str | None = None
            for guardrail_retries in range(GUARDRAIL_MAX_REROUTES + 1):
                await run_developer_node(ctx, dev_feedback, dev_focus_files)
                # Snapshot the real working-tree production delta (git-tracked, full content) for the Reviewer.
                build_production_snapshot(ctx)
                # Refresh the repo map now that the Developer has materialized the contract files. The
                # early map (built at the TechLead node, before any code existed) is stale — without this
                # the checkpoint/Reviewer see only the pre-clone tree (e.g. just LICENSE).
                ctx.repository_map = generate_repo_map(ctx.workspace_paths.repo_dir)

                # Contract completeness: the Developer must create EVERY contracted file (it tends to
                # skip non-code artifacts like .gitignore/LICENSE). Fast-fail reroute on any missing
                # file (no functional budget); soft fall-through at the cap so a stray missing file
                # never hard-halts an otherwise-good run.
                missing = _missing_contract_files(ctx)
                if missing:
                    misplaced = _misplaced_contract_files(ctx, missing)
                    absent = [f for f in missing if f not in misplaced]
                    correction = _format_contract_correction(misplaced, absent)
                    if guardrail_retries == GUARDRAIL_MAX_REROUTES:
                        # A MISPLACED file at the cap is a deterministic refusal to honor the contract
                        # path (not a stray omission) — hard-halt with an ACCURATE path-mismatch incident
                        # instead of silently falling through to the doc guardrail, which would then mis-
                        # report it as 'uncontracted, undocumented'. Genuinely-absent-only files keep the
                        # soft fall-through so a stray missing artifact never aborts an otherwise-good run.
                        if misplaced:
                            ctx.error_trace = correction
                            _abort_with_incident(
                                ctx,
                                f"\n🚨 HARD HALT: contracted file(s) created at the WRONG path after "
                                f"{GUARDRAIL_MAX_REROUTES} fast-fail reroutes — relocate to the contracted "
                                f"path. Misplaced: {misplaced}",
                            )
                        log.warning(f"🔶 Contracted files still missing after in-loop reroutes: {missing} — proceeding to the gates/Reviewer.")
                    else:
                        log.warning(
                            f"🔶 Developer skipped contracted file(s) {missing} "
                            + (f"(misplaced: {misplaced}) " if misplaced else "")
                            + f"— fast-fail reroute {guardrail_retries + 1}/{GUARDRAIL_MAX_REROUTES} "
                            "(no budget spent), Reviewer bypassed."
                        )
                        dev_feedback = correction
                        dev_focus_files = None
                        continue

                guardrail_msg = await enforce_documentation_guardrail(ctx)
                if guardrail_msg:
                    if guardrail_retries == GUARDRAIL_MAX_REROUTES:
                        guardrail_halt = True  # cap reached and still failing → hard halt below
                        break
                    log.warning(
                        f"🔶 Doc guardrail: undocumented new file(s) — fast-fail reroute "
                        f"{guardrail_retries + 1}/{GUARDRAIL_MAX_REROUTES} to Developer (no budget spent), Reviewer bypassed."
                    )
                    dev_feedback = guardrail_msg  # focused reroute: just the comment instruction
                    dev_focus_files = None
                    continue

                # Compile gate: give the Developer REAL build feedback before the expensive QA/Reviewer
                # cycle. Build/run-only (never tests). A clean build → proceed; a failure fast-fail
                # reroutes to the Developer (no functional-budget spent), exactly like the doc guardrail.
                build_ok, build_lines = await run_build_gate(
                    ctx.contract.environment_id, str(ctx.workspace_paths.repo_dir)
                )
                if build_ok:
                    break  # documented + compiles → proceed to gates/Reviewer
                # An ENVIRONMENTAL failure (package feed/DNS/proxy unreachable — e.g. NuGet NU1301) is
                # NOT a code defect: the Developer cannot fix the network, and rerouting it just burns
                # budget AND corrupts the contract (it drops mandated deps to "compile offline", which
                # the Reviewer then rejects → deadlock → circuit breaker). One cheap retry absorbs a
                # transient blip; a persistent outage fails FAST with a precise, retry-later incident.
                if build_failure_is_environmental(ctx.contract.environment_id, build_lines):
                    log.warning("🔶 Compile gate failed on a NETWORK/restore error (not a code defect) — retrying the build once before judging.")
                    build_ok, build_lines = await run_build_gate(
                        ctx.contract.environment_id, str(ctx.workspace_paths.repo_dir)
                    )
                    if build_ok:
                        break
                    if build_failure_is_environmental(ctx.contract.environment_id, build_lines):
                        ctx.error_trace = _cap_text("\n".join(build_lines))
                        _abort_with_incident(
                            ctx,
                            "\n🚨 ENVIRONMENT/NETWORK HALT: dependency restore could not reach the package "
                            "feed (e.g. NuGet NU1301 / connection dropped). This is NOT a code defect — the "
                            "Developer is NOT rerouted and the contract is left intact. Re-run when network "
                            "access to the package source is restored.",
                        )
                    # retry surfaced a REAL compiler error instead → fall through to normal handling
                # A build failure caused SOLELY by test files (e.g. Go's package loader parsing a
                # colocated `*_test.go`) is QA-owned — never reroute the Developer for it. Fall through
                # to the gates/Reviewer, which routes test issues to the QA channel.
                if build_failure_is_test_only(ctx.contract.environment_id, build_lines):
                    log.warning("🔶 Compile gate failed on TEST files only — routing to the QA channel (Developer not rerouted).")
                    break
                if guardrail_retries == GUARDRAIL_MAX_REROUTES:
                    # Persistent compile failure: soft fall-through (NOT a hard halt). The QA gate +
                    # Reviewer diagnose it with the full retry budget rather than aborting the run.
                    log.warning("🔶 Compile gate still failing after in-loop reroutes — handing to the gates/Reviewer.")
                    break
                log.warning(
                    f"🔶 Compile gate failed — fast-fail reroute "
                    f"{guardrail_retries + 1}/{GUARDRAIL_MAX_REROUTES} to Developer (no budget spent), Reviewer bypassed."
                )
                dev_feedback = "The production code failed to compile in the sandbox. Fix it.\n\n" + _cap_text("\n".join(build_lines))
                dev_focus_files = None

            if guardrail_halt:
                ctx.error_trace = guardrail_msg
                _abort_with_incident(
                    ctx,
                    f"\n🚨 HARD HALT: Developer failed the documentation guardrail after {GUARDRAIL_MAX_REROUTES} fast-fail reroutes.",
                )

        # Developer is the dominant token drain — enforce the budget before spending on gates.
        enforce_financial_circuit_breaker(ctx, budget_usd)

        # 3.5 QA test-compile gate: production code now exists (Developer ran, or it was pre-approved on
        #     a DAG-bypass test-only cycle), so the QA tests can be COMPILE-checked. A test-side compile
        #     failure (unused import, undefined symbol — the class that otherwise burns a whole Reviewer
        #     cycle) fast-fail-reroutes to the QA channel and regenerates the suite, with NO Reviewer
        #     spend and NO functional-retry consumed — mirroring the Developer's compile gate. Anything
        #     not clearly test-only (env/network, or a production-referencing failure) falls through to
        #     the Reviewer unchanged, so real production bugs are never misrouted to QA.
        for qa_gate_retries in range(QA_GATE_MAX_REROUTES + 1):
            tc_ok, tc_lines = await run_test_compile_gate(
                ctx.contract.environment_id, str(ctx.workspace_paths.repo_dir)
            )
            if tc_ok:
                break
            if build_failure_is_environmental(ctx.contract.environment_id, tc_lines):
                log.warning("🔶 QA test-compile gate failed on a NETWORK/restore error — handing to the Reviewer (not a QA defect).")
                break
            if not build_failure_is_test_only(ctx.contract.environment_id, tc_lines):
                log.warning("🔶 QA test-compile gate failed but the error references production code — handing to the Reviewer (not auto-routed to QA).")
                break
            if qa_gate_retries == QA_GATE_MAX_REROUTES:
                log.warning("🔶 QA test-compile gate still failing after in-loop regenerations — handing to the Reviewer.")
                break
            log.warning(
                f"🔶 QA test-compile gate failed on TEST files only — fast-fail regeneration "
                f"{qa_gate_retries + 1}/{QA_GATE_MAX_REROUTES} to QA (no budget spent), Reviewer bypassed."
            )
            ctx.qa_error_trace = _cap_text(
                "The generated test suite does not compile. Fix ONLY the test files.\n\n"
                + "\n".join(tc_lines)
            )
            await run_qa_agent_node(ctx, ctx.qa_error_trace)  # its format pass re-runs over the new tests
            enforce_financial_circuit_breaker(ctx, budget_usd)
        ctx.qa_error_trace = ""  # consumed by the rebound loop; don't leak into the Reviewer's channels

        # 3.6 Lint/style gate (HARD): the engine's own quality bar so a STRICT CI stays green — `lint_cmd`
        #     is the SSOT the DevOps-generated workflow also runs (engine-green ⇒ CI-green). Cheap
        #     deterministic autofix (format_cmd) FIRST, then VERIFY (lint_cmd); a residual finding the
        #     autofix could not apply (e.g. F841 unused-local) fast-fail-reroutes to the offending channel
        #     — production → Developer, test → QA — with NO functional-retry consumed. `lint_success` folds
        #     into all_gates_passed below, so anything still red after LINT_GATE_MAX_REROUTES rides the
        #     budgeted cycle (the classified findings are re-applied to the channels AFTER the Reviewer's
        #     routing). Deliberately NOT in the deadlock guard: a lint nit is always agent-fixable in
        #     principle, never an environment misconfiguration.
        lint_success = True
        lint_prod_feedback = ""
        lint_test_feedback = ""
        lint_prod_findings: list[str] = []
        lint_test_findings: list[str] = []
        prev_lint_findings: tuple | None = None
        for lint_retries in range(LINT_GATE_MAX_REROUTES + 1):
            await run_format_pass(ctx.contract.environment_id, str(ctx.workspace_paths.repo_dir))
            lint_ok, lint_lines = await run_lint_gate(
                ctx.contract.environment_id, str(ctx.workspace_paths.repo_dir)
            )
            if lint_ok:
                break
            lint_prod_findings, lint_test_findings = classify_lint_findings(
                ctx.contract.environment_id, lint_lines
            )
            findings_key = (tuple(lint_prod_findings), tuple(lint_test_findings))
            # Stop the fast-fail loop at the cap, on no-progress (agent rewrote but the SAME findings remain
            # — e.g. a format↔lint flip-flop), or when nothing classified to a channel — and hand the
            # residual to the budgeted cycle below.
            if (lint_retries == LINT_GATE_MAX_REROUTES or findings_key == prev_lint_findings
                    or not (lint_prod_findings or lint_test_findings)):
                lint_success = False
                break
            prev_lint_findings = findings_key
            log.warning(
                f"🔶 Lint gate failed — fast-fail reroute {lint_retries + 1}/{LINT_GATE_MAX_REROUTES} "
                f"(prod={len(lint_prod_findings)}, test={len(lint_test_findings)}; no budget spent), Reviewer bypassed."
            )
            if lint_prod_findings:
                ctx.error_trace = _cap_text(_LINT_FEEDBACK_PREAMBLE + "\n".join(lint_prod_findings))
                await run_developer_node(ctx, ctx.error_trace, None)
                build_production_snapshot(ctx)
                ctx.repository_map = generate_repo_map(ctx.workspace_paths.repo_dir)
            if lint_test_findings:
                ctx.qa_error_trace = _cap_text(_LINT_FEEDBACK_PREAMBLE + "\n".join(lint_test_findings))
                await run_qa_agent_node(ctx, ctx.qa_error_trace)  # its format pass re-runs over the new tests
            enforce_financial_circuit_breaker(ctx, budget_usd)
        # Keep the Reviewer's snapshot consistent with the autofixed/rerouted working tree, then clear the
        # live channels so lint feedback never leaks into the Reviewer's own diagnostic routing.
        build_production_snapshot(ctx)
        ctx.repository_map = generate_repo_map(ctx.workspace_paths.repo_dir)
        ctx.error_trace = ""
        ctx.qa_error_trace = ""
        if not lint_success:
            # Stash the residual findings; re-applied to the channels AFTER the Reviewer routes (the
            # Reviewer is lint-blind and may have emptied the channels by approving).
            lint_prod_feedback = (
                _cap_text(_LINT_FEEDBACK_PREAMBLE + "\n".join(lint_prod_findings)) if lint_prod_findings else ""
            )
            lint_test_feedback = (
                _cap_text(_LINT_FEEDBACK_PREAMBLE + "\n".join(lint_test_findings)) if lint_test_findings else ""
            )
            log.warning("🔶 Lint gate still failing after the fast-fail budget — folding into the budgeted cycle.")

        # 4. Automated Validation Phase (Runtime gates).
        #    DUMB PIPE: the orchestrator never inspects the test exit code to alter FSM state — no test
        #    purging, no cycle skipping. All runner logs (stdout+stderr) flow to the Reviewer, the sole
        #    node that semantically judges failures (incl. ImportError) and routes the fix.
        log.debug("Triggering parallel validation gates (QA & Security)")
        qa_result, sec_result = await asyncio.gather(
            run_qa_unit_tests(
                environment_id=ctx.contract.environment_id,
                repo_root=str(ctx.workspace_paths.repo_dir),
            ),
            run_security_scan(
                environment_id=ctx.contract.environment_id,
                repo_root=str(ctx.workspace_paths.repo_dir),
            ),
        )
        qa_success, qa_lines = qa_result
        sec_success, sec_lines = sec_result

        # 5. Comprehensive Audit Phase (Reviewer Agent) — failure log sliced marker-aware so the root
        #    ImportError/Traceback is preserved even when buried above a long stack.
        await run_reviewer_node(ctx, qa_success, _extract_failure_context(qa_lines), sec_success, sec_lines)
        enforce_financial_circuit_breaker(ctx, budget_usd)

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
            and lint_success
            and ctx.review_report.code_quality_approved
            and ctx.review_report.test_integrity_approved
        )

        # Log Approval Checkpoint Status
        log.debug(f"Approval Checkpoint Status: QA={qa_success}, SAST={sec_success}, Code_Approve={ctx.review_report.code_quality_approved}, Test_Approve={ctx.review_report.test_integrity_approved}")

        # Deadlock guard (BACKLOG #16): a hard gate FAILED but the Reviewer approved BOTH code and
        # tests — it found no fixable defect, so the dev/QA diagnostic channels are empty and every
        # remaining cycle would repeat identically until the breaker. This is an environment/runner
        # misconfiguration the agents cannot fix (e.g. a sandbox import-path error). Fail fast with the
        # gate output instead of burning the rest of the retry budget.
        gate_failed = not qa_success or not sec_success
        reviewer_approved_both = (
            ctx.review_report.code_quality_approved and ctx.review_report.test_integrity_approved
        )
        if gate_failed and reviewer_approved_both:
            failed_gates = (
                (["FUNCTIONAL-TESTS"] if not qa_success else [])
                + (["SAST-SECURITY"] if not sec_success else [])
            )
            gate_output = _extract_failure_context(qa_lines) if not qa_success else "\n".join(sec_lines)
            _abort_with_incident(
                ctx,
                f"\n🚨 ENVIRONMENT/RUNNER MISCONFIGURATION: the {', '.join(failed_gates)} gate FAILED, "
                "but the Reviewer approved BOTH code and tests — there is no agent-fixable defect, so "
                "retrying cannot make progress. Halting now instead of looping to the circuit breaker."
                f"\n\n--- gate output ---\n{_cap_text(gate_output)}",
            )

        # If the Reviewer rejected the tests specifically, raise the test regeneration flag
        if not all_gates_passed and not ctx.review_report.test_integrity_approved:
            log.warning("🔶 Reviewer Agent flagged test suite anomalies. Scheduling test regeneration.")
            regenerate_tests = True

        if not all_gates_passed:
            # Arbiter (contract self-healing): once a cycle is demonstrably stuck (a prior fix already
            # failed), classify the root cause. Beyond the Developer/QA channels it can route to the
            # CONTRACT — re-deriving the TechLead spec — for failures no downstream agent can fix
            # (contradictory contract, missing error precedence, a fix that would break an NFR).
            if attempt >= ARBITER_TRIGGER_ATTEMPT:
                gate_output = _extract_failure_context(qa_lines) if not qa_success else "\n".join(sec_lines)
                await run_arbiter_node(
                    ctx, gate_output=_cap_text(gate_output),
                    prev_dev_trace=prev_dev_trace, prev_qa_trace=prev_qa_trace,
                )
                enforce_financial_circuit_breaker(ctx, budget_usd)
                verdict = ctx.arbiter_verdict
                amend_allowed = ctx.contract_amendments < MAX_CONTRACT_AMENDMENTS
                if verdict.route == "contract" and amend_allowed:
                    pinned_env = ctx.contract.environment_id
                    await run_techlead_node(ctx, amendment_feedback=verdict.contract_amendment_directive)
                    ctx.contract.environment_id = pinned_env   # PIN: amendment never thrashes the platform
                    ctx.contract_amendments += 1
                    regenerate_tests = True                    # QA re-derives tests vs the amended contract
                    ctx.error_trace = ""                       # stale: referenced the pre-amendment contract
                    ctx.qa_error_trace = ""
                    ctx.review_report = None
                    enforce_financial_circuit_breaker(ctx, budget_usd)
                    ctx.current_attempt = attempt + 1
                    ctx.save_checkpoint(checkpoint_file)
                    log.warning(
                        f"🔶 Cycle {attempt}: Arbiter amended the contract "
                        f"({ctx.contract_amendments}/{MAX_CONTRACT_AMENDMENTS}). Re-deriving on a fresh cycle."
                    )
                    continue
                if verdict.route == "halt" or (verdict.route == "contract" and not amend_allowed):
                    _abort_with_incident(
                        ctx,
                        f"\n🚨 ARBITER: unrecoverable spec conflict (amendments "
                        f"{ctx.contract_amendments}/{MAX_CONTRACT_AMENDMENTS}) — {verdict.reasoning}",
                    )
                # route in {developer, qa}: fall through to the normal isolated channel routing below.

            # Isolated routing: production-code fixes → Developer channel; test fixes → QA channel.
            ctx.error_trace = _cap_text(ctx.review_report.dev_diagnostic_payload)
            ctx.qa_error_trace = _cap_text(ctx.review_report.qa_diagnostic_payload)
            log.warning(f"🔶 Cycle {attempt} failed. Routing reviewer diagnostics to isolated channels.")

            # Lint stayed red after its fast-fail budget: those classified findings are the authoritative
            # feedback for the next budgeted cycle. The Reviewer is lint-blind and may have approved both
            # sides (emptying the payloads above), so re-apply the lint feedback over whatever it routed.
            if not lint_success:
                if lint_prod_feedback:
                    ctx.error_trace = lint_prod_feedback
                if lint_test_feedback:
                    ctx.qa_error_trace = lint_test_feedback
                    regenerate_tests = True   # ensure QA actually re-runs next cycle to fix the test lint

        # Advance the persisted attempt counter so a resumed run cannot exceed the
        # original retry budget. The counter is bumped before saving so the next
        # process picks up exactly where this one left off.
        ctx.current_attempt = attempt + 1
        ctx.save_checkpoint(checkpoint_file)
        log.debug(f"Checkpoint saved at end of cycle {attempt}: {checkpoint_file}")
        log.info(
            f"   [FINOPS] {_finops_subtotals(ctx)} / ${budget_usd:.2f} budget "
            f"| {ctx.telemetry.total_tokens}t (cache-excluded, reported only)"
        )

        if all_gates_passed:
            log.info("🟩 PIPELINE SUCCESS: All validation gates passed.")
            # Living-ADR maintenance: update + stage docs/architecture_state.md BEFORE the atomic
            # commit so the verified delta and its documentation land in the same transaction.
            await run_techwriter_node(ctx)
            await finalize_transaction(ctx, push=cfg.push)
            # E2: close the loop to base_branch. Wrapped so a hard merge failure (sys.exit raises
            # SystemExit) still persists + surfaces the FinOps report — spend stays auditable.
            try:
                if cfg.auto_merge:
                    await finalize_pr(ctx, cfg)
            finally:
                write_finops_report(ctx)
                log_finops_summary(ctx)
            return ctx

    # Escalation on Circuit Breaker open
    _abort_with_incident(ctx, "\n🚨 CIRCUIT BREAKER OPEN: Retries exhausted.")

if __name__ == "__main__":
    asyncio.run(main())
