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

2. **The Agent Sandbox (Ephemeral Artifacts)**
   - `artifacts/code/` - Code written by the AI Developer Agent.
   - `artifacts/tests/` - Tests written by the AI QA Agent.
   - `artifacts/reports/checkpoint.json` - Serialized FSM state.
   - *Mutation Rules*: YOU ARE STRICTLY FORBIDDEN from manually fixing code in `artifacts/code/` or `artifacts/tests/`. If a generated application has a bug, you must fix the **Engine (`src/`)** or **Prompts (`prompts/`)** that caused the agent to fail.