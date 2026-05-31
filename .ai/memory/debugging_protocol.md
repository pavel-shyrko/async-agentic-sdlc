---
name: debugging-protocol
description: Mandatory steps for diagnosing FSM pipeline failures.
metadata:
  type: procedure
---

# DIAGNOSTIC PROCEDURE: PIPELINE CRASHES

When the Human asks you to debug a failed pipeline run or an agent looping in a Catch-22, you MUST follow this strict data-gathering sequence before proposing code changes:

1. **State Inspection**: Read `artifacts/reports/checkpoint.json` to extract `current_attempt`, `review_report`, and the Architect's `contract`.
2. **Telemetry Check**: Read the tail of `artifacts/logs/sdlc_audit.log` (last 50-100 lines) to trace the exact FSM transition and identify which agent failed.
3. **Execution Logs**: If tests failed, inspect the raw Docker runner output inside the state context.
4. **Root Cause Analysis**: Never assume the agent LLM is "just failing". Look for systemic engine flaws:
   - Path routing conflicts (e.g., Ghost Files).
   - Strict validation contradictions in `prompts/system/`.
   - Broken text parsing or glob scanning in `src/utils/`.