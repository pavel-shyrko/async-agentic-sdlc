---
paths:
  - "src/executor/runner.py"
  - "src/shared/core/config.py"
---

# Tunable limits are named module constants

Every cap, budget, and limit in the engine is declared as an UPPER_CASE module-level constant, and the
runtime-tunable ones read an env override: `PIPELINE_BUDGET_TOKENS`, `MAX_FUNCTIONAL_RETRIES`
(env `PIPELINE_MAX_RETRIES`), `GUARDRAIL_MAX_REROUTES`, `QA_GATE_MAX_REROUTES`, `QA_LINT_MAX_REROUTES`,
`MAX_FILE_SIZE_BYTES`, `FEEDBACK_TAIL_LINES`, `FEEDBACK_MAX_CHARS`, `GIT_NETWORK_TIMEOUT`, `RUNS_BASE`.
The Arbiter self-healing knobs follow the same convention: `ARBITER_TRIGGER_ATTEMPT`,
`MAX_CONTRACT_AMENDMENTS`, `AMENDMENT_RETRY_BONUS` (ADR 0016).

**Resolved (was the long-standing outlier):** the functional circuit-breaker budget used to be a bare
literal `max_retries = 3` local inside the cycle loop. ADR 0016 hoisted it to
`MAX_FUNCTIONAL_RETRIES = int(os.environ.get("PIPELINE_MAX_RETRIES", "3"))`, and the outer loop is now a
`while` over the dynamic ceiling `MAX_FUNCTIONAL_RETRIES + contract_amendments * AMENDMENT_RETRY_BONUS`
(see [pipeline-fsm-loops](pipeline-fsm-loops.md)). No bare-literal caps remain in core control flow.

**Why:** Magic numbers in core control flow are invisible to operators and untestable per-environment;
a retry budget is exactly the kind of FinOps/resilience knob that belongs in config.

**How to apply:** When adding any new cap/limit, define it as an env-overridable UPPER_CASE module
constant, e.g. `MAX_FUNCTIONAL_RETRIES = int(os.environ.get("PIPELINE_MAX_RETRIES", "3"))`, and reference
that in the loop — never inline a literal in business logic.
