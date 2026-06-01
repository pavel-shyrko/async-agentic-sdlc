---
name: workspace-topology
description: Strict boundaries between Orchestrator Engine and Agent Sandbox.
metadata:
  type: constraint
---

# BOUNDARY CONSTRAINT: ENGINE VS SANDBOX

The project contains two entirely isolated domains:

1. **The Orchestrator Engine (Meta-Code)**
   - `src/` - Python orchestrator, Pydantic models, agent logic.
   - `tests/framework/` - Unit tests for the engine itself.
   - `prompts/` - AI configurations (prompts and skills).
   - *Mutation Rules*: You CAN mutate these files to improve or fix the workflow engine.

2. **The Agent Session (Ephemeral, Git-Anchored)**
   - Each run lives under `runs/run_<uuid>/`. The target repo is shallow-cloned into
     `runs/run_<uuid>/repo/` on a `feat/ticket-<ticket>` branch.
   - `runs/run_<uuid>/repo/<src-dir>/` - Code written by the AI Developer Agent (default `src/`).
   - `runs/run_<uuid>/repo/<tests-dir>/` - Tests written by the AI QA Agent (default `tests/`).
   - `runs/run_<uuid>/reports/checkpoint.json` - Serialized FSM state (kept OUTSIDE the clone).
   - `runs/run_<uuid>/logs/sdlc_audit.log` - Per-session audit trail (outside the clone).
   - *Mutation Rules*: YOU ARE STRICTLY FORBIDDEN from manually fixing generated code inside the session
     clone (`runs/run_<uuid>/repo/`). If a generated application has a bug, you must fix the
     **Engine (`src/`)** or **Prompts (`prompts/`)** that caused the agent to fail.