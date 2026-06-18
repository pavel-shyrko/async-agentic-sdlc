import asyncio


async def _run_git(args: list[str], cwd: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return proc.returncode, stdout.decode().strip()


async def get_git_root(path: str) -> str:
    """Resolves the root of the git working tree containing ``path``.

    Built on ``git rev-parse --show-toplevel`` so callers never guess the root via ``.parent`` —
    this stays correct for nested source layouts (e.g. a ``backend/app/src`` tree).
    """
    returncode, output = await _run_git(["rev-parse", "--show-toplevel"], cwd=path)
    if returncode != 0:
        raise RuntimeError(f"Not a git repository: {path}")
    return output


async def get_pipeline_snapshot_files(
    repo_path: str, base_branch: str, subdir: str | None = None, diff_filter: str | None = None
) -> list[str]:
    """Returns the paths changed against ``base_branch``, scoped to ``subdir`` when given.

    Stages with ``git add -A`` first so brand-new (untracked) files are included, then takes the
    INDEX diff (``git diff --cached``) — a plain ``git diff`` would silently omit untracked files and
    starve the Reviewer of context. Paths are repo-root-relative; the ``subdir`` pathspec isolates an
    agent to its own subtree within the shared index. ``diff_filter`` maps to ``--diff-filter`` (e.g.
    ``"A"`` → added/newly-created files only). Agents never commit — changes remain staged.

    Any non-zero git exit (e.g. an orphaned ``.git/index.lock``) raises ``RuntimeError`` so the FSM
    fails fast instead of silently feeding the Reviewer an empty snapshot.
    """
    add_rc, add_out = await _run_git(["add", "-A"], cwd=repo_path)
    if add_rc != 0:
        raise RuntimeError(f"Git snapshot failed (exit {add_rc}): {add_out}")

    diff_args = ["diff", "--cached", base_branch, "--name-only"]
    if diff_filter:
        diff_args.append(f"--diff-filter={diff_filter}")
    if subdir:
        diff_args += ["--", subdir]

    returncode, output = await _run_git(diff_args, cwd=repo_path)
    if returncode != 0:
        raise RuntimeError(f"Git snapshot failed (exit {returncode}): {output}")

    files = [p for p in output.splitlines() if p]
    if ".gitignore" in files:
        files.remove(".gitignore")
    return files
