---
paths:
  - "src/executor/runner.py"
  - "src/shared/core/config.py"
  - "src/shared/utils/forge.py"
---

# Tunable limits are named module constants

Every cap, budget, and limit in the engine is declared as an UPPER_CASE module-level constant, and the
runtime-tunable ones read an env override: `PIPELINE_BUDGET_TOKENS`, `MAX_FUNCTIONAL_RETRIES`
(env `PIPELINE_MAX_RETRIES`), `GUARDRAIL_MAX_REROUTES`, `QA_GATE_MAX_REROUTES`, `QA_LINT_MAX_REROUTES`,
`LINT_GATE_MAX_REROUTES` (env `PIPELINE_LINT_MAX_REROUTES`, default 2 — the step-3.6 style/lint-gate
fast-fail budget), `DEVOPS_MAX_RETRIES` (E4 deploy-manifest static-lint self-heal budget, default 1),
`MAX_FILE_SIZE_BYTES`, `FEEDBACK_TAIL_LINES`, `FEEDBACK_MAX_CHARS`, `GIT_NETWORK_TIMEOUT`,
`GEMINI_REQUEST_TIMEOUT` (per-request wall-clock ceiling on every structured Gemini call, wired into the
shared genai client as `http_options.timeout`), `RUNS_BASE`.
The Arbiter self-healing knobs follow the same convention: `ARBITER_TRIGGER_ATTEMPT`,
`MAX_CONTRACT_AMENDMENTS`, `AMENDMENT_RETRY_BONUS` (ADR 0016). The E2 auto-merge knobs live in
`src/shared/utils/forge.py`: `GH_NETWORK_TIMEOUT` (gh call ceiling) and `GITHUB_MERGE_STRATEGY`
(`admin`|`auto`); the credentials `GITHUB_TOKEN` / `GITHUB_REVIEWER_TOKEN` are read at call time, not cached.

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
