# Claude Code Project Governance

> Scope: this file is reserved for CLI token economy, terminal commands, and workspace/governance
> boundaries. Engineering, code-style, testing-framework, and security RULES for the pipeline agents do
> NOT belong here — they live in `prompts/skills/engineering_guide.md` (injected by the orchestrator).

## Token Economy Rules
* **Brevity Mandate**: Answer with raw code modifications or tight technical bullets. Never output conversational prose, greetings, summaries, or explanatory filler.
* **Output Limit**: Keep responses below 400 tokens unless generating a full file.
* **Plan Mode**: For multi-file changes or ambiguous errors, ALWAYS outline a 3-line plan before mutating code.

## Development Commands
Entrypoint is `main.py` (→ `src/executor/runner.py` `main()`). There is no `orchestrator.py`. The
toolchain (orchestrator, tests, bandit) runs through **WSL + the project `venv/`** — the Windows
interpreter lacks the dependencies and the venv is WSL-only.

* **New project (Nexus planning)**: `python3 main.py --idea "<idea>" [--repo <url|path>] [--auto-execute] [--auto-merge]`  (`--auto-execute` also runs the Executor for the first ticket; requires `--repo`)
* **Execute a ticket**: `python3 main.py --run <project> -f TASK-01 [--auto-merge]`
* **Close the loop to `main` (E2)**: add `--auto-merge` to any run path → on success open + (best-effort) approve + squash-merge a PR `feat/ticket-<id>` → base. **Implies `--push`**; needs the `gh` CLI + `GITHUB_TOKEN` (and a separate `GITHUB_REVIEWER_TOKEN` for a real approval). Seam: `src/shared/utils/forge.py`.
* **Scaffold deploy config (E4)**: add `--scaffold-deploy` to an `--auto-execute` run → after the batch merges every ticket, the `devops` agent generates + merges the app's CI/CD config (archetype-aware Dockerfile + GitHub Actions deploy workflow, GCP Cloud Run via WIF) on `chore/devops-scaffold` (`run_devops_scaffold`). Needs the forge env (`gh` + `GITHUB_TOKEN`); one-time org setup in `docs/guides/devops_setup.md`.
* **Resume a run**: `python3 main.py --resume <project> [NNN]`  (slug alone → latest Nexus run; re-pass `--scaffold-deploy` to run the deploy phase)
* **Legacy direct run**: `python3 main.py --repo <url|path> --ticket <ID> -f <ticket_path>`
* **Run Tests**: `wsl -e bash -lc "cd /mnt/c/code/async-agentic-sdlc && source venv/bin/activate && python3 -m unittest discover -s tests"`
* **Check Lint/Security**: `wsl -e bash -lc "cd /mnt/c/code/async-agentic-sdlc && venv/bin/bandit -r src/"`

## Project Knowledge & Procedures
* Project knowledge lives in `.claude/rules/*.md` — auto-loaded by Claude Code (path-scoped rules load only when you touch matching files; cross-cutting ones load every session). No manual step needed.
* Metadata-synchronization procedures are native skills in `.claude/skills/`: `/adr-generation`, `/docs-sync`, `/claude-context-sync` (reconciles `.claude/rules/*` + `.claude/skills/*` content to the code), `/practicum-update`, and `/iteration-release` (orchestrates all four). Adding a new structured agent role is `/agent-role-scaffold` (operationalizes the `agent-role-registration` rule).
* Run diagnostics are a native skill in `.claude/skills/`: `/analyze-run` — evidence-first root-cause analysis of a failed/looping/halted pipeline run (reads `reports/checkpoint.json` + `logs/sdlc_audit.log` + incident/finops), classifies the cause, and points the fix at `src/`/`prompts/` (never the clone). Invoke it whenever asked to diagnose a run, a circuit-breaker halt, a stuck cycle, a Gemini RECITATION block, a PR/merge (forge) failure, a lint-gate reroute loop or an E4 deploy-scaffolding (`--scaffold-deploy`) static-lint halt, or a non-halt crash/hang (an `embedded null byte` traceback, a Jinja-in-system-message `ValueError`, or a stalled agent call that printed no incident).

## Project Architecture Guardrails
* Never modify runtime prompts inside `prompts/system/` unless explicitly ordered by the Human.
* Never hand-edit generated code inside a run clone (`runs/<project>/<NNN>_exec_…/repo/`). If a generated app is wrong, fix the **engine** (`src/`) or **prompts** (`prompts/`) that caused the agent to fail.
* Engineering/style/testing/security rules for the agents go in `prompts/skills/engineering_guide.md`, never in this file.
