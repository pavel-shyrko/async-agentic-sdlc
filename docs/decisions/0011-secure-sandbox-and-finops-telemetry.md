# 0011 — Secure WSL Sandbox Binding & Real-Time FinOps Circuit Breaker

## Status

Accepted

## Context

Iteration 010 left two latent defects in the sandbox infrastructure and the
cost-control layer — one a host-level security hole, the other a FinOps blind spot:

1. **Unauthenticated remote root via the Docker API** — the WSL2 Docker daemon was
   bound to `tcp://0.0.0.0:2375` with no TLS (`daemon.json` `hosts`). Port 2375 is
   the plaintext Docker API; `0.0.0.0` publishes it on every interface, so any
   process on the local subnet could drive the daemon and, via a privileged bind
   mount, obtain **root on the Windows/WSL host**. A developer-convenience binding
   had become a remote-code-execution surface.

2. **A self-contradictory, broken setup chain** — `docs/docker-on-windows.md`
   claimed independence from Docker Desktop, while `docs/setup.md`'s troubleshooting
   table strictly required it ("make sure Docker Desktop is running"; "Docker
   Desktop manages permissions"). The chain also never installed the engine: it
   configured `daemon.json` for a `docker-ce` that no step had installed, so a clean
   machine could not reach a working runtime by following the guide.

3. **Cost telemetry the FSM could not act on** — Gemini token usage was extracted
   in real time from structured responses, but the out-of-band Developer agent
   (Claude CLI) was auditable **only retrospectively** via `npx ccusage`.
   `GlobalPipelineContext` carried no live Claude token counters, so the orchestrator
   had no in-loop budget signal. A pathological Developer ↔ Reviewer ↔ QA retry loop
   could therefore drain the API budget to exhaustion before any human saw the bill —
   the functional Circuit Breaker bounded *attempts*, but nothing bounded *spend*.

## Decision

Three coordinated changes harden the sandbox and make cost a first-class FSM signal:

- **Loopback-only Docker API binding** — the daemon `hosts` entry is restricted to
  `tcp://127.0.0.1:2375` (plus the unix socket). The API is reachable only from the
  same host, removing the subnet-exposed RCE surface while preserving the
  Windows-CLI → WSL-engine workflow (the client connects over loopback). `DOCKER_HOST`
  and the lazy-loader probe are aligned to `127.0.0.1`.

- **Infrastructure documentation refactor** — `docs/docker-on-windows.md` and
  `docs/setup.md` are rewritten to a single coherent chain: all Docker Desktop
  dependencies are purged (including the troubleshooting table), the explicit
  `docker-ce` engine installation step is added before daemon configuration, and the
  secure loopback binding is the documented default. The docs now describe a runtime
  a clean machine can actually reach.

- **Real-time Claude telemetry + Financial Circuit Breaker** — `GlobalPipelineContext`
  gains live token accounting for the Claude CLI Developer agent, so spend is tracked
  per call rather than reconciled after the fact. A Financial Circuit Breaker
  hard-halts the FSM the moment a configured budget threshold is breached during
  cyclic retries, dumping state for audit instead of looping to exhaustion — the cost
  analogue of the existing functional retry breaker.

- **Cost-primary breaker + cache-excluded token budget** — the breaker's PRIMARY gate is a
  USD budget (`PIPELINE_BUDGET_USD`, env-overridable): cost is authoritative for Claude (the
  CLI reports `total_cost_usd`) and estimated for Gemini, so money is the honest spend signal.
  The token budget (`PIPELINE_BUDGET_TOKENS`) is retained only as a SECONDARY ceiling, and its
  total now counts **fresh input + output only**. Agent caches are excluded from the budget
  uniformly across providers: the agentic Claude CLI re-sends its prompt every internal turn, so
  `cache_read_input_tokens` dominates the raw count while costing ~10% of fresh input, and
  Gemini's `prompt_token_count` likewise INCLUDES `cached_content_token_count`. Both are now split
  out — Claude via `parse_claude_usage` (no longer folding cache into `input_tokens`), Gemini via
  `log_token_usage` (`fresh = prompt − cached`) — tracked SEPARATELY
  (`PipelineTelemetry.total_cache_read_tokens`, per-agent `cache_read_tokens`/`cache_write_tokens`),
  surfaced in the FinOps report and per-agent logs, and EXCLUDED from the budgeted total. Before
  this, one ~$0.14 Developer call consumed ~22% of a 1M-token budget on cheap cache reads. The
  breaker thus bounds real spend, not cache re-reads.

- **Verified Gemini rate table** — `MODEL_PRICING_MATRIX` (`src/core/config.py`) is reconciled to
  official Google AI paid-tier pricing (verified 2026-06): `gemini-3.1-flash-lite` was 2× low
  (`(0.125, 0.75, 0.0125)` → `(0.25, 1.50, 0.025)`), `gemini-2.5-pro`'s long (>200k) tier was a
  copy of short (→ `(2.50, 15.00, 0.25)`), and the `gemini-2.5-flash` / `gemini-2.5-flash-lite`
  cached-read rates were corrected (`0.075`→`0.03`, `0.025`→`0.01`). Accuracy matters now that the
  USD budget is the primary gate. The per-hour context-cache STORAGE price is intentionally not
  modelled — it applies only to explicit `CachedContent`, which the engine never creates (it relies
  on implicit caching, priced per token at the cached-read rate).

- **`Decimal`-based cost estimation** — the pricing model that feeds the Financial
  Circuit Breaker threshold is computed in `Decimal`, not binary floating point. Per-call
  spend is `tokens × per-token rate` summed across a run; IEEE 754 floats accumulate
  representation error on exactly the fractional-cent rates involved, so a float budget
  comparison could trip the breaker early or late by a drifting margin. `Decimal` gives
  exact, rounding-controlled money math, making the budget gate deterministic and the
  FinOps report reconcilable to the cent against the billing source of truth.

- **`Architect` → `TechLead` role rename** — the design node is renamed from "Architect"
  to "TechLead" to map the name onto what the role actually produces: a machine-readable
  contract (`TechLeadContract` — function signatures, type-validation rules, and the
  language-neutral topology graph) that downstream agents consume deterministically. The
  "Architect" label implied open-ended, free-form design; "TechLead" names a node that
  authors a binding, structured contract within the FSM's contract-based workflow. The
  rename propagates across the system prompts and the orchestration layer.

- **Language-neutral topology contract** — `TechLeadContract` gains
  `topology_contract: list[TopologyNode]` (`src/core/models.py`) as the Single Source of
  Truth for project structure, separating the dependency *graph* from any language's import
  *syntax*. Each `TopologyNode` carries `file_path` (repo-root-relative), `exports` (the
  symbols the file publicly exposes), and `depends_on` (neutral `path/to/file.ext:symbol`
  links — **not** import statements); every entry in `files_to_modify` has a matching node.
  The TechLead emits this graph and is forbidden from writing language-specific syntax
  (`from … import`, `using`, `#include`) — the target language is declared separately as the
  first `domain_tags` entry (`prompts/system/techlead.md`, TOPOLOGY RULE). The Developer and
  QA agents translate the neutral links into the target language's imports, with QA consuming
  the graph for test import resolution (`prompts/system/qa.md`, `src/agents/qa.py`). This
  keeps the design node the SSOT for *structure* and the execution agents the owners of
  *syntax*, so a new language is an Open-Closed change to the routed syntax skill, not the
  contract.

## Consequences

- **Pros**: the host RCE is closed — the Docker API is no longer reachable off-host;
  the WSL2 runtime is deterministic and self-contained (no Docker Desktop, engine
  install is explicit), so the setup guide is reproducible on a clean machine; the
  API budget is protected from infinite-loop drain by a deterministic, real-time
  hard-halt rather than a post-mortem `ccusage` report.
- **Pros (cont.)**: cost gating is exact — `Decimal` arithmetic removes floating-point
  drift from the budget comparison, so the breaker trips at the configured threshold and
  the FinOps report reconciles to the cent; the `TechLead` rename makes the role's output
  contract self-describing, tightening the semantic map between node name and the
  structured artifact it emits; dependency resolution is stack-agnostic — the language-neutral
  topology graph makes new-language support Open-Closed (only the routed syntax skill changes,
  never the contract) and lets QA resolve imports from a declared graph instead of guessing
  from code; the breaker now bounds actual money (USD-primary) and a cache-excluded token total,
  so an agentic CLI's cheap cache re-reads no longer drain the budget or mislead the FinOps view —
  cache is still fully auditable, just not counted against the limit.
- **Cons / constraints**: loopback binding means a Docker client on another host can
  no longer reach this daemon without an explicit, separately-secured tunnel (a
  deliberate trade-off favouring isolation over remote convenience); the Financial
  Circuit Breaker is a new hard-failure surface — a generous-but-finite budget can
  terminate a long but legitimate run mid-flight, so the threshold needs tuning per
  workload; live Claude token accounting depends on the CLI surfacing usage per
  invocation, and `npx ccusage` is retained only for historical billing
  reconciliation, not as the in-loop signal; the `Architect` → `TechLead` rename touches
  the prompt and orchestration surface (a breaking rename for anything keyed on the old
  node name), and `Decimal` adds a small per-call conversion cost over native floats —
  both accepted as cheap relative to the correctness they buy; the topology contract adds a
  well-formed surface the TechLead must populate correctly (a mislinked `depends_on` misroutes
  a real dependency) and shifts part of the correctness burden onto the downstream
  neutral-link → import translation step; the USD-primary breaker is only as accurate as its
  inputs — Gemini cost is an *estimate* from the price table, so a stale rate table can drift the
  primary gate (Claude cost stays authoritative), which is why the cache-excluded token total is
  kept as a deterministic secondary ceiling.
