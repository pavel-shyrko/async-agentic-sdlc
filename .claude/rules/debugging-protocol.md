---
paths:
  - "runs/**"
---

# Diagnostic procedure: pipeline crashes

When the Human asks you to debug a failed pipeline run or an agent looping in a Catch-22, you MUST
follow this strict data-gathering sequence before proposing code changes:

1. **State Inspection**: Read the failing run's `runs/<project>/<NNN>_<plane>_<label>_<ts>_<uid>/reports/checkpoint.json` to extract `current_attempt`, `review_report`, and the Architect's `contract`.
2. **Telemetry Check**: Read the tail of that run's `logs/sdlc_audit.log` (last 50-100 lines) to trace the exact FSM transition and identify which agent failed.
3. **Execution Logs**: If tests failed, inspect the raw Docker runner output inside the state context.
4. **Root Cause Analysis**: Never assume the agent LLM is "just failing". Look for systemic engine flaws:
   - Path routing conflicts (e.g. Ghost Files).
   - Strict validation contradictions in `prompts/system/`.
   - Broken text parsing or glob scanning in `src/shared/utils/`.

Runtime control-flow reference: [pipeline-fsm-loops](pipeline-fsm-loops.md). Run layout:
[run-layout-and-cli](run-layout-and-cli.md).
