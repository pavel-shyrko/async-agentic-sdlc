---
paths:
  - "src/executor/runner.py"
  - "src/shared/core/config.py"
---

# Tunable limits are named module constants

Every cap, budget, and limit in the engine is declared as an UPPER_CASE module-level constant, and the
runtime-tunable ones read an env override: `PIPELINE_BUDGET_TOKENS`, `GUARDRAIL_MAX_REROUTES`,
`QA_GATE_MAX_REROUTES`, `QA_LINT_MAX_REROUTES`, `MAX_FILE_SIZE_BYTES`, `FEEDBACK_TAIL_LINES`,
`FEEDBACK_MAX_CHARS`, `GIT_NETWORK_TIMEOUT`, `RUNS_BASE`.

**Outlier (tech debt):** the functional circuit-breaker budget is a bare literal `max_retries = 3`
local inside `main()` in `src/executor/runner.py` (the cycle loop), so it cannot be tuned without
editing code and breaks the convention every other cap follows.

**Why:** Magic numbers in core control flow are invisible to operators and untestable per-environment;
the retry budget is exactly the kind of FinOps/resilience knob that belongs in config.

**How to apply:** Hoist it to a module constant, e.g.
`MAX_FUNCTIONAL_RETRIES = int(os.environ.get("PIPELINE_MAX_RETRIES", "3"))`, and reference that in the
loop. When adding any new cap/limit, define it the same way — never inline a literal in business logic.
