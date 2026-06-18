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

* **New project (Nexus planning)**: `python3 main.py --idea "<idea>" [--repo <url|path>]`
* **Execute a ticket**: `python3 main.py --run <project> -f TASK-01`
* **Resume a run**: `python3 main.py --resume <project> [NNN]`  (slug alone → latest Nexus run)
* **Legacy direct run**: `python3 main.py --repo <url|path> --ticket <ID> -f <ticket_path>`
* **Run Tests**: `wsl -e bash -lc "cd /mnt/c/code/async-agentic-sdlc && source venv/bin/activate && python3 -m unittest discover -s tests"`
* **Check Lint/Security**: `wsl -e bash -lc "cd /mnt/c/code/async-agentic-sdlc && venv/bin/bandit -r src/"`

## Project Knowledge & Procedures
* Project knowledge lives in `.claude/rules/*.md` — auto-loaded by Claude Code (path-scoped rules load only when you touch matching files; cross-cutting ones load every session). No manual step needed.
* Metadata-synchronization procedures are native skills in `.claude/skills/`: `/adr-generation`, `/docs-sync`, `/practicum-update`, and `/iteration-release` (orchestrates the first three).

## Project Architecture Guardrails
* Never modify runtime prompts inside `prompts/system/` unless explicitly ordered by the Human.
* Never hand-edit generated code inside a run clone (`runs/<project>/<NNN>_exec_…/repo/`). If a generated app is wrong, fix the **engine** (`src/`) or **prompts** (`prompts/`) that caused the agent to fail.
* Engineering/style/testing/security rules for the agents go in `prompts/skills/engineering_guide.md`, never in this file.
