import os
import asyncio
from pathlib import Path

from src.core.observability import log

_PROJECT_ROOT = Path(__file__).parents[2]
_GITIGNORE_TEMPLATE = _PROJECT_ROOT / ".gitignore"
_GITIGNORE_FALLBACK = "__pycache__/\n"


async def _run_git(args: list[str], cwd: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return proc.returncode, stdout.decode().strip()


def _deploy_gitignore(repo_path: str) -> None:
    dest = Path(repo_path) / ".gitignore"
    if _GITIGNORE_TEMPLATE.exists():
        content = _GITIGNORE_TEMPLATE.read_text(encoding="utf-8")
        dest.write_text(content, encoding="utf-8")
        log.debug(f"   [GIT] Deployed .gitignore template to {repo_path}")
    else:
        log.warning(f"   [GIT] .gitignore template not found at {_GITIGNORE_TEMPLATE} — writing minimal fallback")
        dest.write_text(_GITIGNORE_FALLBACK, encoding="utf-8")


async def init_sandbox_git(repo_path: str, base_branch: str) -> None:
    if not os.path.isdir(os.path.join(repo_path, ".git")):
        await _run_git(["init"], cwd=repo_path)
        await _run_git(["config", "user.email", "pipeline@sdlc.local"], cwd=repo_path)
        await _run_git(["config", "user.name", "Pipeline"], cwd=repo_path)
        _deploy_gitignore(repo_path)
        await _run_git(["add", ".gitignore"], cwd=repo_path)
        await _run_git(["commit", "-m", "Initial commit with gitignore"], cwd=repo_path)

        # Pin the base branch name as the immutable anchor.
        await _run_git(["branch", "-m", base_branch], cwd=repo_path)

        # Isolate the agent on a working branch — the base branch never moves.
        await _run_git(["checkout", "-b", "agent-workspace"], cwd=repo_path)
        log.info(f"   [GIT] Initialized sandbox at {repo_path} on branch agent-workspace (base: {base_branch})")


async def get_pipeline_snapshot_files(repo_path: str, base_branch: str) -> list[str]:
    await _run_git(["add", "."], cwd=repo_path)

    # Strict cumulative delta against the anchor branch.
    returncode, output = await _run_git(["diff", base_branch, "--name-only"], cwd=repo_path)

    if returncode != 0:
        log.error(f"🚨 CRITICAL: Base branch '{base_branch}' not found for diff.")
        return []

    files = [p for p in output.splitlines() if p]
    if ".gitignore" in files:
        files.remove(".gitignore")
    return files


async def commit_sandbox(repo_path: str, message: str) -> None:
    await _run_git(["commit", "-m", message], cwd=repo_path)
