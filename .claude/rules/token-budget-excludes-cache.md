---
paths:
  - "src/shared/core/observability.py"
  - "src/shared/utils/subprocess_helpers.py"
  - "src/shared/core/config.py"
---

# Cache is NOT in the token budget; the budget is money-only

The Financial Circuit Breaker gates on **USD alone** (ADR 0022 / E5). `PipelineTelemetry.total_tokens`
counts **fresh input + output ONLY**, for **all providers**, but is now **reported, never a ceiling** —
there is no token budget. Cache tokens are tracked separately (`total_cache_read_tokens` /
`total_cache_write_tokens`, per-agent `cache_read_tokens` / `cache_write_tokens`) and are **excluded** from
that reported total:
- **Claude** (`parse_claude_usage`, `src/shared/utils/subprocess_helpers.py`): `cache_read_input_tokens` /
  `cache_creation_input_tokens` are kept separate, never folded into `input_tokens`.
- **Gemini** (`log_token_usage`, `src/shared/core/observability.py`): `prompt_token_count` INCLUDES
  `cached_content_token_count`, so the cached part is split out (`fresh = prompt − cached`) and
  recorded as `cache_read_tokens`.

The SOLE breaker gate is USD: `enforce_financial_circuit_breaker(ctx, budget_usd)` compares
`total_cost_usd` against the **threaded** ceiling — the *remaining application budget* on a batch
(`PIPELINE_APP_BUDGET_USD` − spent), the full app budget on a single-ticket run. `PIPELINE_BUDGET_TOKENS`
survives only as a reporting figure (no longer read by the breaker). USD accuracy depends on
`MODEL_PRICING_MATRIX` being correct — keep it reconciled to official rates (it drifted 2× for
`gemini-3.1-flash-lite` once). Tokens + per-call wall-clock are rolled up per agent and per plane in
`finops_report` / `log_finops_summary` (`by_plane`, `total_duration_seconds`).

**Why:** The Developer is the agentic **Claude Code CLI** — it re-sends its system prompt + tool
schemas + transcript every internal turn, so `cache_read_input_tokens` dominates the raw count while
costing ~10% of fresh input. When `parse_claude_usage` folded cache into `input_tokens`, one ~$0.14
Developer call ate ~22% of a 1M-token budget — the "anomalous" 219k input on a trivial Fibonacci task
was ~90% cheap cache reads, not a leak or prompt bloat. Gemini has the same trap via `prompt_token_count`.

**How to apply:** Never fold cache tokens back into `input_tokens` or `total_tokens`, for any provider.
When adding cost-accruing agents or new telemetry, keep cache columns separate and gate the breaker on
`total_cost_usd` only (never re-introduce a token ceiling — E5 removed it deliberately). The per-hour
context-cache STORAGE price is N/A (engine uses implicit caching only, never explicit `CachedContent`).
Documented in ADR 0011 (cache split) + ADR 0022 (money-only app budget). Related:
[config-constant-convention](config-constant-convention.md) (budgets/rates are env-overridable constants),
[finops-app-budget](finops-app-budget.md) (the application-wide money-budget invariants this feeds).
