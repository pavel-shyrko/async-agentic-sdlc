---
paths:
  - "src/shared/core/runs.py"
  - "src/executor/runner.py"
---

# Run layout & CLI

**Layout** (SSOT: `src/shared/core/runs.py` `Projects` + `allocate_run_dir`):
```
runs/<project>/                               # project = idea slug (Nexus) or ticket slug (direct exec)
  project.json                                # umbrella manifest: {slug, idea, repo, base_branch, created_at}
  <NNN>_nexus_plan_<YYYYMMDD-HHMMSS>_<uid6>/   # planning run → artifacts/{epic,blueprint,TASK-*}.md
  <NNN>_exec_<ticket>_<ts>_<uid6>/            # executor run → repo/ (clone on feat/ticket-<ticket>)
  <NNN>_devops_scaffold_<ts>_<uid6>/          # E4 deploy-scaffolding run → repo/ (clone on chore/devops-scaffold)
```
Every run dir also has `logs/sdlc_audit.log` + `reports/` (`checkpoint.json`, `finops_report.json`,
`incident_report.json` on halt). `NNN` = max existing + 1 within the project; `uid6` guarantees no
overwrite. `RUNS_BASE` (`PIPELINE_RUNS_BASE`, default `runs`) is the root. An `--auto-execute` batch (E3)
also writes `reports/batch_state.json` **in the nexus_plan run dir** (`BatchState`: which tickets have
merged) — the resume anchor for the whole batch.

**CLI verbs** (`parse_args` / `main` in `src/executor/runner.py`):
- `--idea "..." [--repo R] [--auto-execute]` → NEW project, runs Nexus planning (`001_nexus_plan`); `--repo` captured into project.json. With `--auto-execute` (E3) the engine then drives the Executor over **ALL** planned tickets in TPM order in the same invocation — `TASK-01 → merge → TASK-02 → …` — via `run_batch` in `main()` (`get_tasks_for_nexus_run` for order, `prepare_ticket_run` + `run_executor` per ticket; Nexus never imports the executor plane). Requires `--repo`; **`--auto-execute` IMPLIES `--auto-merge`** (each ticket must land on `main` before the next clones it fresh), so `check_environment(require_forge=True)` runs up-front to fail fast. Progress is checkpointed to `batch_state.json`; a halt stops the batch on the first failure (writes the per-ticket incident, records `failed`, exits 1). A repo-less project / no tickets is a clean exit-0 skip, not a failure.
- `--run <project> -f <ticket>` → executor for that ticket; repo + base branch from project.json; ticket body resolved from the latest nexus run's `artifacts/<ticket>.md`.
- `--auto-merge` (E2) → on PIPELINE SUCCESS, open a PR from `feat/ticket-<id>` into the base branch and **squash-merge** it (closes the loop to `main`). **Implies `--push`**; composes with any path (`--run … --auto-merge`, or `--idea … --auto-execute --auto-merge`). Provider-agnostic seam `src/shared/utils/forge.py` (`open_pr`/`approve_pr`/`merge_pr`), GitHub-first via the **`gh` CLI** — so `check_environment(require_forge=True)` also requires `gh` + `GITHUB_TOKEN`. `merge_pr` defaults to `--admin` (immediate) and falls back to `--auto` (queued behind required checks); `GITHUB_MERGE_STRATEGY=auto` forces the queued path. Approval is best-effort via a *separate* `GITHUB_REVIEWER_TOKEN`. Idempotent on `--resume` (reuses an open PR into the same base / skips an already-merged one). A hard merge failure exits 1; a halted ticket never reaches the PR step (no PR on failure).
- `--scaffold-deploy` (E4) → opt-in: after a full `--auto-execute` batch merges every ticket, run **`run_devops_scaffold`** once (post-batch terminal phase). Allocates a `NNN_devops_scaffold_…` run dir, clones `main` onto `chore/devops-scaffold`, has the `devops` agent generate `DevOpsManifests` (archetype-aware Dockerfile + GHA deploy workflow, Cloud Run via WIF), static-lints them (`run_devops_gate`, `DEVOPS_MAX_RETRIES` self-heal), and lands them via the same `finalize_pr` forge flow. Composes with `--auto-execute` (and is re-passed on a `--resume` batch); inert/warns on a non-batch path. Needs the forge env (`gh` + `GITHUB_TOKEN`). Empty-state guard skips a sourceless clone.
- `--resume <project> <NNN>` → resume run #NNN; `--resume <project>` (no number) → if the latest Nexus run has a `batch_state.json` sidecar, **re-enter the E3 batch** (skip already-merged tickets, re-run the failed one fresh against the now-updated `main`; forces `--auto-merge`/`--push` + the forge preflight; re-pass `--scaffold-deploy` to run the deploy phase) — otherwise continue the latest Nexus *planning* run; `--resume <path.json>` → legacy explicit checkpoint.
- Legacy direct: `--repo --ticket [-f file] [desc]` → grouped under a ticket-slug project.

**Resume routing** (no dir-name parsing): `_run_dir_from_checkpoint` = checkpoint's grandparent;
`_checkpoint_kind` peeks `kind` in the JSON — `"nexus"` → control plane (`NexusState`), else executor
(`GlobalPipelineContext`). Old `runs/run_<uuid>/` checkpoints still resume via the path form.

**Git auth for `--run`** (`bootstrap_session` shallow-clones with `GIT_TERMINAL_PROMPT=0`, so a private
repo that needs credentials can't prompt — it fails fast with `could not read Password … terminal
prompts disabled`, never hangs). Pass non-interactive credentials:
- **HTTPS+PAT**: the token is the PASSWORD, so it needs a username — `https://<user>:<token>@github.com/<owner>/<repo>.git` (or `https://x-access-token:<token>@…`). `https://<token>@…` alone FAILS: git reads the token as the username and then prompts for a password.
- **SSH**: `git@github.com:<owner>/<repo>.git` with a key in WSL.
- **Recommended — token in an env var, never on disk**: set an env-backed helper once — `git config --global credential.helper '!f(){ echo username=x-access-token; echo "password=$GITHUB_TOKEN"; };f'` — then `export GITHUB_TOKEN=…` in `~/.bashrc` and always pass a CLEAN URL (`https://github.com/<owner>/<repo>.git`). The token is read from the inherited env (`os.environ.copy()` in `bootstrap_session`/`_run_checked`) at clone time only, so it never lands in `project.json` or the clone's `.git/config`. `GIT_TERMINAL_PROMPT=0` is fine — the helper supplies creds without a prompt. (`credential.helper store` + `~/.git-credentials` also works but writes the token to a plaintext file.)
- `--repo` is captured into `project.json` ONLY on the first `--idea`/`--run` (when `repo` is null); later tickets reuse it. ⚠ A token embedded in the URL is persisted verbatim into `project.json` and the clone's `.git/config` under `runs/` — prefer the env-var helper above for non-throwaway tokens (and scrub `repo` in an existing `project.json` if one already captured a token).

Related: [workspace-topology](workspace-topology.md), [debugging-protocol](debugging-protocol.md).
