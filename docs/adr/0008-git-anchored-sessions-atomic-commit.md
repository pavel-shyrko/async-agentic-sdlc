# 0008 — Git-Anchored Sessions & Atomic Transactional Commit

## Status

Accepted

## Context

Through Iteration 007 the orchestrator was welded to a static `artifacts/` sandbox: `WorkspacePaths`
defaulted to `artifacts/{code,tests,logs,reports}`, and the Developer/QA nodes each `git init`-ed a
**separate, nested** sandbox repository inside their working directory (`init_sandbox_git`). This made the
engine a closed REPL toy — it could not operate on a real target repository, the nested `.git` dirs clobbered
the target's own `.gitignore`, and a successful run produced **no commit**: the verified code never landed on
a branch a human could review or merge.

Three concrete failure modes blocked promotion to a CI agent:
1. **No external repo support** — the workspace was a fixed local directory, not a clone of the caller's repo.
2. **Nested-repo fragmentation** — code and tests lived in isolated `.git` repos, so there was no single
   diffable unit and no PR-shaped branch.
3. **No durable output** — agent edits were snapshotted for the Reviewer but never committed.

## Decision

The pipeline was re-architected around a **per-run, git-anchored session** (Iteration 008, delivered in four
reviewed steps):

- **Session isolation & bootstrap** — each run generates a UUID and a base directory `runs/run_<uuid>/`. The
  target repo (`--repo`, URL or local path) is **shallow-cloned** (`git clone --depth 1`) into
  `runs/run_<uuid>/repo/`, a `feat/ticket-<ticket>` branch is checked out, and the base branch is force-fetched
  into a local ref (`origin <base>:<base>`) so the snapshot diff resolves it. All network git runs with
  `GIT_TERMINAL_PROMPT=0` under a wall-clock timeout (killed **and reaped** on expiry) so a missing-credential
  prompt can never hang the run.
- **Dynamic workspace mapping** — `WorkspacePaths.for_run` resolves `code_dir`/`tests_dir` inside the clone
  (from `--src-dir`/`--tests-dir`) and `logs/`/`reports/` *outside* it, with a path-traversal guard rejecting
  any `..`/absolute escape. The audit logger is re-pointed per session via `reconfigure_logging`.
- **The clone is the Unit-of-Work** — `init_sandbox_git` and the nested-sandbox helpers are retired. The git
  root is resolved with `get_git_root` (`git rev-parse --show-toplevel`, never a guessed `.parent`). Agents only
  mutate the working tree; snapshots are taken with `git add -A` then `git diff --cached <base> -- <subdir>`
  (index diff catches untracked files; the pathspec keeps Developer/QA scoped to their subtrees). Any git I/O
  error raises `RuntimeError` — fail-fast over a silent empty snapshot.
- **QA gate** — `run_qa_unit_tests` mounts the **whole clone root** at `/workspace/repo` (rw) with
  `PYTHONPATH=/workspace/repo`, so absolute imports resolve, and discovers the test tree at its dynamic path.
- **Atomic commit-on-success** — when every gate passes, `finalize_transaction` makes a single
  identity-pinned (`-c user.email/name`) commit `feat(<ticket>): <summary>` on the feature branch, guarded by
  `git diff --cached --quiet` against empty commits, with an opt-in `--push`. The index thus acts as the
  transaction buffer: self-heal cycles re-stage freely and the branch never accrues intermediate commits.

## Consequences

- **Pros**: operates on arbitrary git repositories; produces a real, reviewable PR-shaped branch + commit;
  parallel runs are isolated (per-UUID sessions and audit logs); a single transactional commit (Unit-of-Work)
  keeps history clean across retries; fail-fast git I/O and prompt/timeout hardening remove silent-data and
  hang classes of failure.
- **Cons / constraints**: a working `git` binary and network access are required for clone/fetch; `base_branch`
  must exist on the remote (now explicitly fetched into a local ref); the `--push` path is network/credential
  dependent and remains opt-in and mock-tested; the Dockerized QA gate is still mocked in CI (docker is not
  portable there), with its command shape locked by unit tests.
