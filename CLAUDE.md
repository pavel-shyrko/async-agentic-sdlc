# Claude Code Project Governance

> Scope: this file is reserved for CLI token economy, terminal commands, and workspace/governance
> boundaries. Engineering, code-style, testing-framework, and security RULES for the pipeline agents do
> NOT belong here — they live in `prompts/skills/engineering_guide.md` (injected by the orchestrator).

## Token Economy Rules
* **Brevity Mandate**: Answer with raw code modifications or tight technical bullets. Never output conversational prose, greetings, summaries, or explanatory filler.
* **Output Limit**: Keep responses below 400 tokens unless generating a full file.
* **Plan Mode**: For multi-file changes or ambiguous errors, ALWAYS outline a 3-line plan before mutating code.

## Development Commands
Entrypoint is `main.py` (→ `src/nexus/runner.py` `main()`). There is no `orchestrator.py`. The
toolchain (orchestrator, tests, bandit) runs through **WSL + the project `venv/`** — the Windows
interpreter lacks the dependencies and the venv is WSL-only.

* **New project (Nexus planning)**: `python3 main.py --idea "<idea>" [--repo <url|path>] [--auto-execute] [--scaffold-deploy] [--release] [--budget <usd>]`  (`--auto-execute` plans then drives the Executor over **all** planned tickets to `main` in TPM order via `run_batch` (E3) — **implies `--auto-merge`**; requires `--repo`. `--budget <usd>` sets the application-wide money ceiling for the whole build (E5; overrides `PIPELINE_APP_BUDGET_USD`); the breaker is money-only — re-pass a larger `--budget` on `--resume` to add budget and continue a halted batch)
* **Execute a ticket**: `python3 main.py --run <project> -f TASK-01 [--auto-merge]`
* **Close the loop to `main` (E2)**: add `--auto-merge` to any run path → on success open + (best-effort) approve + squash-merge a PR `feat/ticket-<id>` → base. **Implies `--push`**; needs the `gh` CLI + `GITHUB_TOKEN` (and a separate `GITHUB_REVIEWER_TOKEN` for a real approval). Seam: `src/shared/utils/forge.py`.
* **Scaffold deploy config (E4)**: add `--scaffold-deploy` to an `--auto-execute` run → after the batch merges every ticket, the `devops` agent generates + merges the app's CI/CD config (archetype-aware Dockerfile + GitHub Actions deploy workflow, GCP Cloud Run via WIF; web services deployed **publicly-invocable** by default) on `chore/devops-scaffold` (`run_devops_scaffold`). The deploy *target* is registry-driven (`SUPPORTED_DEPLOY_TARGETS`); deploy mechanics live in the platform skills `prompts/skills/deploy_{gcp,github_release}.md` (separate from the app-shape `devops_*` archetype skills). Needs the forge env (`gh` + `GITHUB_TOKEN`); one-time org setup in `docs/guides/devops_setup.md`.
* **Cut a release (E6)**: add `--release` to an `--auto-execute` run → as the build's final step (after all tickets merge + optional `--scaffold-deploy`), `run_batch` calls `finalize_release` to push a `v*` tag (repo-derived latest bumped by `RELEASE_VERSION_BUMP`, default minor; `v0.1.0` greenfield) that trips the tag-gated deploy/release workflow. Decoupled from `--scaffold-deploy`; off by default; reuses the batch's git push creds. Seam: `forge.push_tag`/`list_remote_tags`.
* **Resume a run**: `python3 main.py --resume <project> [NNN]`  (slug alone → latest Nexus run; re-pass `--scaffold-deploy` and/or `--release` to run the deploy / release phase)
* **Legacy direct run**: `python3 main.py --repo <url|path> --ticket <ID> -f <ticket_path>`
* **Run Tests** (from the repo root — `wsl` inherits the cwd, no absolute `cd`): `wsl -e bash -lc "source venv/bin/activate && python3 -m unittest discover -s tests"`
* **Check Lint/Security** (from the repo root): `wsl -e bash -lc "venv/bin/bandit -r src/"`

## Project Knowledge & Procedures
* Project knowledge lives in `.claude/rules/*.md` — auto-loaded by Claude Code (path-scoped rules load only when you touch matching files; cross-cutting ones load every session). No manual step needed.
* Metadata-synchronization procedures are native skills in `.claude/skills/`: `/tbf-adr-generation`, `/tbf-docs-sync`, `/tbf-claude-context-sync` (reconciles `.claude/rules/*` + `.claude/skills/*` content to the code), `/tbf-practicum-update`, and `/tbf-iteration-release` (orchestrates all four). Adding a new structured agent role is `/tbf-agent-role-scaffold` (operationalizes the `agent-role-registration` rule).
* Run diagnostics are a native skill in `.claude/skills/`: `/tbf-analyze-run` — evidence-first root-cause analysis of a failed/looping/halted pipeline run (reads `reports/checkpoint.json` + `logs/sdlc_audit.log` + incident/finops), classifies the cause, and points the fix at `src/`/`prompts/` (never the clone). Invoke it whenever asked to diagnose a run, a circuit-breaker halt, a stuck cycle, a Gemini RECITATION block, a PR/merge (forge) failure, a lint-gate reroute loop or an E4 deploy-scaffolding (`--scaffold-deploy`) static-lint halt (incl. a missing public-invoker grant, or a *live* Cloud Run service returning HTTP 403 / "not authenticated"), a Developer Claude-CLI provider-quota / session-limit halt (a `🚨 PROVIDER QUOTA HALT` / "hit your session limit" stop where the Developer billed 0 tokens), or a non-halt crash/hang (an `embedded null byte` traceback, a Jinja-in-system-message `ValueError`, or a stalled agent call that printed no incident).
* Code quality auditing is a native skill in `.claude/skills/`: `/tbf-code-quality` — audits the generated application code and tests in a completed executor run's clone (reads `repo/`, `reports/checkpoint.json`, gate outputs) to assess contract compliance, code quality, test coverage, and efficiency.

## Project Architecture Guardrails
* Never modify runtime prompts inside `prompts/system/` unless explicitly ordered by the Human.
* Never hand-edit generated code inside a run clone (`runs/<project>/<NNN>_exec_…/repo/`). If a generated app is wrong, fix the **engine** (`src/`) or **prompts** (`prompts/`) that caused the agent to fail.
* Engineering/style/testing/security rules for the agents go in `prompts/skills/engineering_guide.md`, never in this file.
