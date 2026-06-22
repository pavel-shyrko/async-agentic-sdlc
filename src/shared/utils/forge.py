"""Provider-agnostic code-forge operations (open / approve / merge a pull request).

A thin seam so a non-GitHub forge (GitLab ``glab``, Bitbucket, …) can supply its own implementation
later; today it is GitHub-first via the ``gh`` CLI. This mirrors ``git_helpers.py``'s subprocess-first
style and the ``runner._run_checked`` auth idiom: a copied environment with interactive prompts disabled,
a wall-clock ceiling on every network call, and ``GITHUB_TOKEN`` read from the inherited env (never on
disk). ``gh`` infers the owner/repo from the clone's ``origin`` remote, so every call runs with
``cwd=repo_dir`` — no URL/owner parsing.

Failure policy: ``merge_pr`` is the loop-closing step, so a genuine merge failure exits non-zero
(consistent with ``_run_checked``); ``approve_pr`` is strictly best-effort and never aborts; ``open_pr``
is idempotent (reuses an existing PR into the same base, or skips a merged one).
"""
import os
import sys
import json
import asyncio

from src.shared.core.observability import log
from src.shared.utils.subprocess_helpers import sanitize_for_argv

# Network ceiling for `gh` calls — same default as GIT_NETWORK_TIMEOUT, independently tunable.
GH_NETWORK_TIMEOUT = int(os.environ.get("GH_NETWORK_TIMEOUT", "300"))
# Default squash-merge strategy: `admin` merges immediately (works on repos without required checks);
# `auto` queues the merge to land once required checks pass (the protected-repo path).
GITHUB_MERGE_STRATEGY = os.environ.get("GITHUB_MERGE_STRATEGY", "admin")

# Substrings in `gh pr merge --admin` stderr that mean "can't merge NOW because required checks are
# still pending" — the signal to fall back from an immediate merge to a queued (`--auto`) one.
_PENDING_CHECKS_HINTS = (
    "required status check",
    "required check",
    "checks are pending",
    "not mergeable",
    "is in an unstable",
    "expected status",
)


async def _run_gh(args: list[str], repo_dir, *, env_extra: dict | None = None,
                  timeout: float | None = GH_NETWORK_TIMEOUT) -> tuple[int, str, str]:
    """Run a fixed-argument ``gh`` subprocess (shell=False) and return ``(rc, stdout, stderr)``.

    Unlike ``runner._run_checked`` this NEVER calls ``sys.exit`` on a non-zero exit — the caller
    decides, because forge semantics differ per command (a missing PR on ``pr view`` is normal, a
    failed ``pr merge`` is fatal). A timeout (a hung credential prompt despite the disabled flag) is
    still treated as fatal here, mirroring the git network ops.
    """
    env = os.environ.copy()              # copy, never a bare dict — preserves PATH/SystemRoot
    env["GH_PROMPT_DISABLED"] = "1"      # no interactive prompt -> fail fast, never hang
    if env_extra:
        env.update(env_extra)
    # Strip control chars (notably NUL) from every arg — a corrupted glyph in agent-authored PR
    # title/body would otherwise make execvp raise "embedded null byte".
    safe_args = [sanitize_for_argv(a) for a in args]
    proc = await asyncio.create_subprocess_exec(
        "gh", *safe_args, cwd=str(repo_dir),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()                # reap immediately after kill — no <defunct> zombie
        log.error(f"🚨 gh {' '.join(args[:2])} timed out after {timeout}s — aborting.")
        sys.exit(1)
    return proc.returncode, stdout.decode(errors="replace").strip(), stderr.decode(errors="replace").strip()


async def open_pr(repo_dir, head_branch: str, base_branch: str, title: str, body: str) -> str | None:
    """Open (or reuse) a PR from ``head_branch`` into ``base_branch``; return its ref (url/number).

    Idempotent on ``--resume``: an existing OPEN PR from this head into the SAME base is reused; one
    that is already ``MERGED`` returns ``None`` (the caller skips the merge). An existing PR that
    targets a DIFFERENT base is not ours — fall through and create a fresh one.
    """
    rc, out, _err = await _run_gh(
        ["pr", "view", head_branch, "--json", "number,state,baseRefName,url"], repo_dir,
    )
    if rc == 0 and out:
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            data = {}
        if data.get("baseRefName") == base_branch:
            if data.get("state") == "MERGED":
                log.info(f"🔁 PR #{data.get('number')} for {head_branch} is already MERGED — skipping.")
                return None
            log.info(f"🔁 Reusing open PR {data.get('url')} ({head_branch} → {base_branch}).")
            return str(data.get("number"))
        # An open PR from this head into a different base is not the one we mean to merge.

    rc, out, err = await _run_gh(
        ["pr", "create", "--base", base_branch, "--head", head_branch,
         "--title", title, "--body", body], repo_dir,
    )
    if rc != 0:
        log.error(f"🚨 gh pr create failed (exit {rc}): {err}")
        sys.exit(1)
    log.info(f"🔀 Opened PR {out} ({head_branch} → {base_branch}).")
    return out.strip()


async def approve_pr(repo_dir, pr_ref: str) -> bool:
    """Best-effort PR approval via a SEPARATE reviewer identity. Never aborts the run.

    GitHub forbids a PR author approving their own PR, so a real approval needs a second credential:
    ``GITHUB_REVIEWER_TOKEN``. Without it, approval is skipped (the ``--admin`` merge still closes the
    loop on unprotected repos). If the ``gh`` call itself fails (token lacks repo permission,
    self-approval rejected, …) the error is logged and swallowed — control returns to the merge step.
    """
    token = os.environ.get("GITHUB_REVIEWER_TOKEN")
    if not token:
        log.info("ℹ️  No GITHUB_REVIEWER_TOKEN set — skipping PR approval (relying on the --admin merge).")
        return False
    rc, _out, err = await _run_gh(
        ["pr", "review", str(pr_ref), "--approve"], repo_dir, env_extra={"GH_TOKEN": token},
    )
    if rc != 0:
        log.warning(f"⚠️  PR approval failed (exit {rc}) — continuing to merge anyway: {err}")
        return False
    log.info("✅ PR approved via GITHUB_REVIEWER_TOKEN.")
    return True


async def merge_pr(repo_dir, pr_ref: str) -> None:
    """Squash-merge the PR, protected-repo-aware. A genuine merge failure exits non-zero.

    Default strategy ``admin`` merges immediately (any repo without required status checks). If the
    immediate merge is blocked by pending required checks, fall back to ``--auto`` — queuing the merge
    to complete once CI goes green (the loop closes asynchronously). ``GITHUB_MERGE_STRATEGY=auto``
    forces the queued path up front for operators who always want it on protected repos.
    """
    flag = "--auto" if GITHUB_MERGE_STRATEGY.lower() == "auto" else "--admin"
    rc, _out, err = await _run_gh(
        ["pr", "merge", str(pr_ref), "--squash", flag, "--delete-branch"], repo_dir,
    )
    if rc == 0:
        log.info("🕓 Merge queued (auto) — completes after required checks pass."
                 if flag == "--auto" else "✅ Squash-merge complete.")
        return

    # An immediate (--admin) merge can be refused while required checks are still pending; queue it.
    if flag == "--admin" and any(h in err.lower() for h in _PENDING_CHECKS_HINTS):
        log.warning("⚠️  Immediate merge blocked by pending required checks — queuing with --auto.")
        rc2, _out2, err2 = await _run_gh(
            ["pr", "merge", str(pr_ref), "--squash", "--auto", "--delete-branch"], repo_dir,
        )
        if rc2 == 0:
            log.info("🕓 Merge queued (auto) — completes after required checks pass.")
            return
        err = err2

    log.error(f"🚨 gh pr merge failed: {err}")
    sys.exit(1)
