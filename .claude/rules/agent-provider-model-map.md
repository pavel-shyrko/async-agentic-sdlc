---
paths:
  - "src/nexus/*.py"
  - "src/nexus/agents/*.py"
  - "src/development/agents/*.py"
  - "src/deployment/agents/*.py"
  - "src/shared/utils/llm.py"
---

# Agent → provider / model map

**Gemini, via `run_structured_llm`** (`src/shared/utils/llm.py` → instructor + `instructor_client`,
forced structured Pydantic output): the **development** plane's **TechLead, QA, Reviewer, Technical Writer,
Arbiter (failure triage / contract self-healing)** and the **deployment** plane's **DevOps (post-batch
deploy-scaffolding, E4)**, plus the Nexus control plane's **PO, SA, TPM**. Each role's model + display label is in `ROLE_MODELS`
(`src/shared/core/config.py`; `DEVOPS_MODEL` registers `devops`). On a structured failure the cause (e.g.
Gemini `RECITATION`) is surfaced by `describe_finish_reason` (`observability.py`) via `with_api_retry`.
`run_structured_llm` also relocates any Jinja-marker (`{{ }}`/`{% %}`) **system** message to a user turn
(`_relocate_jinja_system_messages`) — instructor's GenAI path rejects Jinja in system messages, which a
config-teaching prompt (the DevOps `${{ secrets.* }}`) would otherwise trip; a fast-path no-op for every
marker-free role. Every structured call is
wall-clock-bounded: `instructor_client` is built with a `GEMINI_REQUEST_TIMEOUT` (default 300 s, env-overridable)
`http_options` ceiling, so a stalled request *raises* (then `with_api_retry` backs off and fails fast)
instead of hanging the run forever — `with_api_retry` only catches exceptions, never a silent stall.

**Claude Code CLI, via `run_claude_cli`** (agentic, NOT structured): the **Developer** only. It edits
files directly in the run's `repo/`, re-sending its prompt/transcript each turn (hence cache-heavy). A
subscription **session/usage-limit block** is recognized by `detect_claude_quota_block` (the CLI emits one
"hit your session limit" line, edits nothing, bills 0 tokens) and fails fast with a `🚨 PROVIDER QUOTA HALT`
(`ClaudeCliQuotaExhausted`) — an infrastructure condition, NOT a wrong-work agent defect; see the
`tbf-analyze-run` provider-quota class.

**FinOps** (see [token-budget-excludes-cache](token-budget-excludes-cache.md) + [finops-app-budget](finops-app-budget.md)):
Gemini cost is **estimated** from `MODEL_PRICING_MATRIX`; Claude cost is **authoritative** (reported by the
CLI). The breaker is **money-only** (ADR 0022): it gates on `total_cost_usd` against the threaded application
budget — tokens (fresh input + output; cache read/write tracked separately, excluded) are reported, never a
ceiling. Per-agent telemetry via `log_token_usage(telemetry, …)`, which also attributes the **plane** (from
`AGENT_PLANE`) and the per-call **wall-clock** (read from the `run_structured_llm` `LAST_LLM_ELAPSED_S`
ContextVar — no change to its 2-tuple return); the Developer (Claude) records directly with `plane="development"`.
`log_finops_summary` prints the GRAND TOTAL with per-agent + per-plane subtotals + total time. All planes
record into a `PipelineTelemetry`; the batch merges them into `BatchState.app_telemetry`. Related:
[repo-module-map](repo-module-map.md), [agent-contracts](agent-contracts.md).
