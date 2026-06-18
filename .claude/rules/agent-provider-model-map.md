---
paths:
  - "src/nexus/*.py"
  - "src/executor/agents/*.py"
  - "src/shared/utils/llm.py"
---

# Agent → provider / model map

**Gemini, via `run_structured_llm`** (`src/shared/utils/llm.py` → instructor + `instructor_client`,
forced structured Pydantic output): the executor's **TechLead, QA, Reviewer, Technical Writer** and the
Nexus control plane's **PO, SA, TPM**. Each role's model + display label is in `ROLE_MODELS`
(`src/shared/core/config.py`). On a structured failure the cause (e.g. Gemini `RECITATION`) is surfaced
by `describe_finish_reason` (`observability.py`) via `with_api_retry`.

**Claude Code CLI, via `run_claude_cli`** (agentic, NOT structured): the **Developer** only. It edits
files directly in the run's `repo/`, re-sending its prompt/transcript each turn (hence cache-heavy).

**FinOps** (see [token-budget-excludes-cache](token-budget-excludes-cache.md)): Gemini cost is
**estimated** from `MODEL_PRICING_MATRIX`; Claude cost is **authoritative** (reported by the CLI).
Budget = fresh input + output only (cache read/write tracked separately, excluded); the breaker gates
primarily on USD. Per-agent telemetry via `log_token_usage(telemetry, …)`; end-of-run
`log_finops_summary` prints the GRAND TOTAL. Both planes record into a `PipelineTelemetry`. Related:
[repo-module-map](repo-module-map.md), [agent-contracts](agent-contracts.md).
