---
paths:
  - "src/nexus/runner.py"
  - "src/deployment/provision/scaffold.py"
  - "src/shared/core/models.py"
  - "src/shared/core/config.py"
  - "src/shared/core/observability.py"
  - "src/shared/utils/llm.py"
---

# Application-wide FinOps budget invariants (money-only)

E5 (ADR [0022](../../docs/decisions/0022-application-wide-finops-budget.md)) made a SINGLE money ceiling
govern a whole `--idea --auto-execute` build, replaced the per-ticket token/USD breaker, and added per-role/
per-plane/time reporting. The mechanics are easy to half-break in a way tests may not catch, so uphold these
invariants whenever you touch the breaker, `run_batch`/`BatchState`, `run_devops_scaffold`, `PipelineTelemetry`,
or the budget constants. Cache-exclusion is the sibling rule [[token-budget-excludes-cache]].

## Invariants

1. **Money-only gate.** `enforce_financial_circuit_breaker(ctx, budget_usd)` compares `total_cost_usd` ONLY.
   Never re-introduce a token ceiling — `PIPELINE_BUDGET_TOKENS` is report-only. The breaker takes the
   effective ceiling as a **parameter**; it must not read a module constant directly.

2. **One ceiling, threaded as the remaining budget.** The ceiling is resolved in `run_batch` as
   `cfg.budget_usd if cfg.budget_usd is not None else (batch.initial_budget_usd or PIPELINE_APP_BUDGET_USD)`
   and passed to each `run_executor(budget_usd_ceiling=remaining)` where
   `remaining = app_budget − batch.app_telemetry.total_cost_usd`. Single-ticket paths default `None →
   PIPELINE_APP_BUDGET_USD`. A new spend phase (e.g. another post-batch agent) MUST be threaded the same way.

3. **The initial ceiling IS persisted as a fallback; explicit `--budget` always wins.**
   `BatchState.initial_budget_usd` stores the ceiling from the first invocation (set once, never overwritten)
   so `--resume` without `--budget` preserves the original budget. An explicit `--budget` on `--resume`
   overrides it, so re-budgeting (`--resume --budget <larger>`) still works. `BatchState` also stores the
   *spend* (`app_telemetry`), the `nexus_merged` guard, and the `budget_marker`.

4. **Halt-safe app report.** `run_batch` writes `app_finops_report.json` + saves `BatchState` in a
   **`finally`**, so the cumulative figure survives ANY exit — clean finish, a ticket/DevOps `PipelineHalt`,
   or a budget stop. On a ticket halt the failed run's spend is recovered from its incident/checkpoint dump
   and merged before exit; `run_devops_scaffold` merges its (even partial) spend into the passed
   `app_telemetry` in its OWN `finally`. Do not move these writes/merges out of the `finally`.

5. **Floor-stop is a clean exit, not a halt.** Below `PIPELINE_APP_BUDGET_FLOOR_USD` the batch records a
   `budget_marker` and `sys.exit(1)` BEFORE dispatching the next ticket — it writes **no**
   `incident_report.json` (nothing was spent on that ticket). Keep this distinct from the breaker halt
   (which does write an incident). The marker is cleared when a resume continues.

6. **No double-count on resume.** Fold the Nexus planning spend in exactly once, guarded by
   `BatchState.nexus_merged`; never re-merge a `completed` ticket. A halted-then-retried ticket legitimately
   counts both its failed-attempt and successful-retry spend (you paid for both) — that is correct, not a bug.

7. **Telemetry attribution, zero call-site churn.** Plane is derived at record time from the `AGENT_PLANE`
   SSOT (display-label → plane); a new agent label MUST be added there ([[agent-role-registration]]) or its
   spend mis-buckets into `development`. Per-call time is published by `run_structured_llm` into the
   `LAST_LLM_ELAPSED_S` `ContextVar` and read in `log_token_usage` — **do NOT change `run_structured_llm`'s
   2-tuple return** to thread time (that was rejected precisely because it would break the agent test mocks).
   The Developer (Claude, not structured) times its own `run_claude_cli` call and passes `plane="development"`.

## How to apply
- Adding a cost-accruing phase → thread `budget_usd_ceiling` + enforce the breaker after each call, and merge
  its telemetry into `app_telemetry` (in a `finally` if it can halt).
- Changing what's reported → keep `finops_report` money-only (no token-budget keys) and update BOTH the
  per-run and app-wide reporters + the per-plane summary; sync the docs surfaces ([[run-layout-and-cli]],
  the `/tbf-docs-sync` skill's FinOps peer-set).
- Adding a budget knob → env-overridable `UPPER_CASE` constant ([[config-constant-convention]]).

Related: [[token-budget-excludes-cache]], [[pipeline-fsm-loops]] (breaker placement),
[[deploy-scaffolding-and-ci-parity]] (E4 budget threading), [[plane-import-direction]] (scaffold imports the
breaker), [[repo-module-map]] (symbol locations).
