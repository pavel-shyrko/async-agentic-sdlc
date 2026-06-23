# Iteration 18 — Close the Loop to `main` via an Auto-Merged PR (`--auto-merge`, E2)

> ADR: [0018-auto-merge-pr-loop-closure](../../decisions/0018-auto-merge-pr-loop-closure.md) ·
> CHANGELOG: [v0.18.0](../../../CHANGELOG.md) · Practicum:
> [PRACTICUM.md](../../../PRACTICUM.md)

## Problem Statement

The autonomy loop stopped one step short of `main`. On full success the executor made the atomic
`feat(<ticket>): …` commit on `feat/ticket-<id>` and, with `--push`, pushed the branch — and **stopped**.
Verified, gate-passing work sat on a feature branch; landing it in `base_branch` still required a human.
`base_branch` was only a **diff anchor + fetch ref**, never a merge target, and the engine had **no PR /
merge / `gh` / GitHub API** at all (greenfield). E1 (ADR 0017) had just made the per-ticket flow a reusable
`run_executor` callable; E2 is the step that lets its output actually reach `main`.

Three constraints had to be resolved rather than assumed: **(1)** GitHub forbids a PR author approving
their *own* PR, so a real approval needs a **second identity**; **(2)** a protected repo can refuse an
immediate merge until *remote* required checks pass; **(3)** the interface must stay provider-agnostic to
avoid GitHub lock-in.

## Implemented Solutions

### Headline — `--auto-merge`: PR → approve → squash-merge into `main` (ADR 0018)
- **Provider-agnostic forge seam — `src/shared/utils/forge.py`** (`open_pr` / `approve_pr` / `merge_pr`),
  GitHub-first via the `gh` CLI. Subprocess-first like `git_helpers.py` and the `runner._run_checked` auth
  idiom: copied env with prompts disabled (`GH_PROMPT_DISABLED=1`), a wall-clock ceiling on every network
  call (`GH_NETWORK_TIMEOUT`, 300 s), `GITHUB_TOKEN` from the inherited env (never on disk), and `gh`
  inferring owner/repo from the clone's `origin` remote (`cwd=repo_dir`, no URL parsing). It lives in the
  **shared** plane so a GitLab (`glab`) / Bitbucket backend can follow behind the same three names.
- **`--auto-merge` flag** (`RunConfig.auto_merge`) — **implies `--push`** (`push = args.push or
  args.auto_merge`). A new `finalize_pr(ctx, cfg)` runs **after** `finalize_transaction` in the success
  block, wrapped in `try/finally` so the FinOps report/summary still print even on a hard merge failure.
- **Idempotent, resume-safe `open_pr`** — `gh pr view` first: reuse an **OPEN** PR into the **same** base,
  return `None` (skip merge) if it is already **MERGED**, create a fresh one if an open PR targets a
  *different* base. Safe `--resume` after a partial merge (relates to BACKLOG #23).
- **Identity model — `--admin` squash-merge, approve best-effort.** `merge_pr` does `gh pr merge --squash
  --admin --delete-branch` (closes the loop on unprotected repos). `approve_pr` runs **only** when a
  separate `GITHUB_REVIEWER_TOKEN` is set (passed as `GH_TOKEN` — a *different* identity), and any `gh`
  failure is **logged and swallowed**; without the token, approval is skipped and the `--admin` merge still
  lands the work.
- **Protected-repo path** — if the `--admin` merge is refused for *pending required checks*
  (`_PENDING_CHECKS_HINTS`), `merge_pr` falls back to `gh pr merge --auto` (queued merge once remote CI is
  green). `GITHUB_MERGE_STRATEGY=auto` forces the queued path up front.
- **Fail-fast preflight** — `check_environment(require_forge=cfg.auto_merge)` also requires `gh` on PATH and
  a non-empty `GITHUB_TOKEN` when `--auto-merge`, aborting before any tokens are spent. Failure policy: a
  genuine `merge_pr` failure `sys.exit(1)`s; `approve_pr` never aborts; the bridge stays in the entry/worker
  layer — the control plane never learns about PRs (ADR 0012 held).

### Boundary hardening (found in live E2 validation)
- **Embedded-NUL argv crash → `sanitize_for_argv`.** A corrupted glyph in a Nexus-authored ticket (`©` →
  `\x00`) reached `gh pr create --body`; POSIX `execvp` rejects a NUL in any argv element →
  `ValueError: embedded null byte`. Fixed with one SSOT helper in `subprocess_helpers.py` (strips C0
  controls + DEL, keeps `\t`/`\n`/`\r`) applied at **both** subprocess boundaries — `forge._run_gh` **and**
  `runner._run_checked` (the commit path had the same latent exposure).
- **Unbounded Gemini call hang → `GEMINI_REQUEST_TIMEOUT`.** A stalled structured Gemini request (seen while
  *building* the Reviewer context via `fallback_semantic_search`) hung the executor forever:
  `run_in_executor` had no timeout, `with_api_retry` only fires on exceptions, the client had no ceiling.
  Fixed at the SSOT — the shared genai client is built with `http_options=HttpOptions(timeout=
  GEMINI_REQUEST_TIMEOUT * 1000)` (300 s, env-overridable), so a stall *raises* → retries → fails fast.
  Covers **every** structured role, not just the Reviewer.

### Meta-tooling & docs synced to the release
- `docs/ARCHITECTURE.md` — the GitHub external node (L1/L2) and end-to-end sequence now show PR + approve +
  squash-merge; `forge.py` added to the component reference + shared-utils list.
- `docs/guides/setup.md` — a `gh` install + auth section, the `GITHUB_REVIEWER_TOKEN` / `GITHUB_MERGE_STRATEGY`
  / `GH_NETWORK_TIMEOUT` / `GEMINI_REQUEST_TIMEOUT` env knobs, pre-flight `gh` check, and troubleshooting rows.
- `.claude/rules/{config-constant-convention,repo-module-map,run-layout-and-cli}.md` — record `forge.py`,
  the new knobs, and `--auto-merge`.

## Metrics / Logs Analysis

- **Diff footprint** (`main` → HEAD, 3 commits): **13 files, 682 insertions / 26 deletions**. New engine:
  `src/shared/utils/forge.py` (+155, the seam). Engine edits: `src/executor/runner.py` (+85, `finalize_pr` +
  `--auto-merge` wiring + `_run_checked` sanitize), `src/shared/core/config.py` (+25, `GEMINI_REQUEST_TIMEOUT`
  + `check_environment(require_forge=…)` + client `http_options`), `src/shared/utils/subprocess_helpers.py`
  (+19, `sanitize_for_argv`). Tests: `test_orchestrator.py` (+167), `test_forge.py` (+120), `test_config.py`
  (+21), `test_subprocess_helpers.py` (+22). Docs: `docs/guides/setup.md` (+75), `README.md` (+6),
  `.claude/rules/*` (+13).
- **Test suite:** 359 tests green via WSL (357 + the 2 new client-timeout tests; forge + sanitize suites
  included). Bandit clean on the touched engine files.
- **Validation run (real API + Docker + GitHub), demo project `cli-python-json-csv`** (`001_nexus_plan_…210902`
  → `002_exec_TASK-01_…211011`): planned 3 tickets, auto-dispatched `TASK-01`. **Cycle 1** — both gates
  passed (pytest 3/3, Semgrep 0 findings) but the Reviewer correctly rejected a non-verbatim `README.md`
  (`code_quality_approved: false`) and routed a `dev_diagnostic_payload`; **cycle 2** — Developer fixed it →
  approved. Then: atomic commit → push → **PR #1 opened** → **approved via `GITHUB_REVIEWER_TOKEN`** (separate
  identity) → **squash-merged into `main`** → branch deleted. Cost **$0.4434 / $10.00** (Claude $0.3609
  actual, Gemini $0.0825 est.), 40,215 tokens (cache-excluded). This run also re-exercised the exact
  `build_agent_context → fallback_semantic_search` path that previously hung, confirming the timeout fix.

> Validate locally via WSL:
> `wsl -e bash -lc "cd /mnt/c/code/token-burners-factory && source venv/bin/activate && GEMINI_API_KEY=test-key python3 -m unittest discover -s tests"`
