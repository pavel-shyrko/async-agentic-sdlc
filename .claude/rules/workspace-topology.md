# Boundary constraint: Engine vs Sandbox

The project contains two entirely isolated domains:

1. **The Orchestrator Engine (Meta-Code)**
   - `src/` — Python orchestrator, Pydantic models, agent logic.
   - `tests/framework/` — Unit tests for the engine itself.
   - `prompts/` — AI configurations (prompts and skills).
   - *Mutation Rules*: You CAN mutate these files to improve or fix the workflow engine.

2. **The Agent Session (Ephemeral, Git-Anchored)**
   - Runs are grouped per project (idea/ticket) under `runs/<project>/`, which holds a `project.json`
     umbrella (idea, target repo, base branch) and numbered run dirs named
     `<NNN>_<plane>_<label>_<YYYYMMDD-HHMMSS>_<uid6>/` (SSOT: `src/shared/core/runs.py`).
   - An **executor** run (`<NNN>_exec_<ticket>_…/`) shallow-clones the target repo into its `repo/` on a
     `feat/ticket-<ticket>` branch:
     - `…/repo/<src-dir>/` — Code written by the AI Developer Agent (default `src/`).
     - `…/repo/<tests-dir>/` — Tests written by the AI QA Agent (default `tests/`).
   - A **nexus** run (`<NNN>_nexus_plan_…/`) writes generated control-plane output to its `artifacts/`
     (epic.md, blueprint.md, TASK-*.md) — no clone.
   - Per run dir, OUTSIDE the clone: `reports/checkpoint.json` (serialized FSM state) and
     `logs/sdlc_audit.log` (per-run audit trail); on a halt, `reports/incident_report.json`.
   - *Mutation Rules*: YOU ARE STRICTLY FORBIDDEN from manually fixing generated code inside a session
     clone (`runs/<project>/<NNN>_exec_…/repo/`). If a generated application has a bug, you must fix the
     **Engine (`src/`)** or **Prompts (`prompts/`)** that caused the agent to fail.

Related: [run-layout-and-cli](run-layout-and-cli.md), [repo-module-map](repo-module-map.md).
