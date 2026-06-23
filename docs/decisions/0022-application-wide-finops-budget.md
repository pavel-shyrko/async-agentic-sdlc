# 0022 — Application-wide FinOps Budget (money-only) + per-role/per-plane/time Reporting

## Status

Accepted (extends [0011](0011-secure-sandbox-and-finops-telemetry.md) FinOps telemetry + financial circuit
breaker, [0019](0019-cyclical-multi-ticket-orchestration.md) `run_batch` multi-ticket orchestration,
[0021](0021-physical-three-plane-split.md) the three-plane split; implements **E5** in `docs/BACKLOG.md`)

## Context

The Financial Circuit Breaker (ADR 0011) gated **each ticket** against fixed module constants
(`PIPELINE_BUDGET_USD` / `PIPELINE_BUDGET_TOKENS`). After E3 (ADR 0019) a single `--idea --auto-execute`
invocation drives N tickets, each through a fresh `run_executor` whose `PipelineTelemetry` starts at zero —
so a batch could spend up to **N × the intended ceiling** before any single ticket tripped. The E3 4-ticket
validation run (`cli-python-json-csv`) spent $0.42 + $0.41 + $0.65 + $0.39 = **$1.86**, yet each ticket was
measured only against its own $10 budget; the batch never saw a cumulative figure. The operator pays for the
**application**, but nothing bounded the application.

Two secondary observations shaped the design:
- **The token ceiling was noise.** The agentic Claude CLI re-sends its transcript every turn, so the
  cache-excluded token total still tracked poorly against real spend; USD (authoritative for Claude,
  estimated for Gemini) was already the honest gate. A second, weaker ceiling only added a confusing
  failure mode.
- **The FinOps report was plane-blind and time-blind.** `finops_report` / `log_finops_summary` broke spend
  down per agent and per provider, but not per control plane (nexus / development / deployment) and tracked
  no wall-clock — so "what did this build cost, and where did the time go?" had no single answer.

## Decision

### A — One money ceiling, threaded as the remaining budget
- **`PIPELINE_APP_BUDGET_USD`** (env-overridable, default `$25.00`) is the single application-wide ceiling
  governing a whole build. **`--budget <usd>`** overrides it per-invocation.
- `enforce_financial_circuit_breaker(ctx, budget_usd)` takes the **effective ceiling as a parameter** and
  gates on **USD only** — the token branch is removed. `run_executor(..., budget_usd_ceiling=...)` threads
  it: on a batch the *remaining* budget (`app_budget − spent`), on a single-ticket path the full app budget.
- **`run_batch`** folds the Nexus planning spend (once, guarded by `BatchState.nexus_merged`) and every
  finished ticket's telemetry into **`BatchState.app_telemetry`**, computes `remaining = app_budget − spent`
  before each ticket, and **stops cleanly** (records a `budget_marker`, exits 1) once `remaining` drops to
  **`PIPELINE_APP_BUDGET_FLOOR_USD`** (default `$0.01`) — before spending more. The E4 DevOps phase is
  threaded the same remaining budget and enforces it inside its self-heal loop.

### B — Money-only budget (tokens reported, not capped)
`PIPELINE_BUDGET_TOKENS` survives only as a reporting figure; the breaker no longer reads it.
`finops_report` drops the token-budget keys and keeps `total_tokens` as a raw count. Cache read/write stays
excluded and surfaced separately (ADR 0011 invariant preserved).

### C — Per-role + per-plane + time reporting
- `AgentUsage` gains `plane` and `duration_seconds`; `PipelineTelemetry` gains `total_duration_seconds`,
  `by_plane()`, and `merge()` (the cross-run aggregator).
- **Plane** is attributed at record time from a single `AGENT_PLANE` SSOT (display-label → plane) in
  `config.py` — **zero per-agent-call churn**.
- **Time** is collected via a `ContextVar` (`LAST_LLM_ELAPSED_S`) set in `run_structured_llm` and read in
  `log_token_usage` — **without changing `run_structured_llm`'s 2-tuple return**, so the existing agent test
  mocks are untouched. The Developer (Claude CLI, not structured) times its own `run_claude_cli` call.
- `run_batch` writes **`app_finops_report.json`** (merged Nexus + tickets + DevOps: per-role, per-plane,
  per-time) and renders the per-plane GRAND TOTAL — always, in a `finally`.

### D — Resume correctness + re-budgeting
`BatchState.app_telemetry` persists, so `--resume` reloads the exact running total (no re-spend of merged
tickets, no double-merge of the Nexus spend). The **ceiling is never persisted** — it is re-resolved every
invocation from `--budget`/env — so re-passing a larger `--budget` on a `--resume` "adds money" and
continues a batch that stopped on exhaustion (the `budget_marker` is cleared as it continues).

### E — Halt-safe accounting
The app report and `BatchState` are persisted in `run_batch`'s `finally`, mirroring `_abort_with_incident`.
On a ticket `PipelineHalt` the failed run's spend is recovered from its incident/checkpoint dump and folded
in; a budget halt inside the DevOps self-heal loop still merges the partial DevOps spend (via an
`app_telemetry` reference passed into `run_devops_scaffold`, merged in *its* `finally`) — so the cumulative
figure is never lost.

## Consequences

- A batch can no longer overspend `N ×` the intended ceiling; one `PIPELINE_APP_BUDGET_USD` (or `--budget`)
  bounds the entire `--idea --auto-execute` build, and the operator can top it up on resume.
- The token circuit breaker is gone; the only spend gate is money. Per-environment cost accuracy now rests
  entirely on `MODEL_PRICING_MATRIX` (Gemini estimate) + the Claude CLI's authoritative figure.
- Starvation is by design: an expensive early ticket can consume the shared pool and strand the tail — the
  budget halt makes this legible (a `budget_marker` + the app report) rather than silent.
- Every run now answers "what did this cost and where did the time go?" via `app_finops_report.json`
  (per-role, per-plane, per-time) and the GRAND TOTAL block.

## Touch points

`src/shared/core/models.py` (`AgentUsage`, `PipelineTelemetry.record`/`by_plane`/`merge`/`finops_report`,
`BatchState.app_telemetry`/`nexus_merged`/`budget_marker`), `src/shared/core/config.py`
(`PIPELINE_APP_BUDGET_USD`, `PIPELINE_APP_BUDGET_FLOOR_USD`, `AGENT_PLANE`),
`src/shared/utils/llm.py` (`LAST_LLM_ELAPSED_S`), `src/shared/core/observability.py`
(`log_token_usage`, `log_finops_summary`), `src/nexus/runner.py`
(`enforce_financial_circuit_breaker`, `run_executor`, `run_batch`, `write_app_finops_report`, `--budget`),
`src/deployment/provision/scaffold.py` (`run_devops_scaffold`). Rules: `token-budget-excludes-cache`,
`config-constant-convention`, `pipeline-fsm-loops`, `run-layout-and-cli`.
