# Async Agentic SDLC Orchestrator (OPS_000)

An engineered, deterministic multi-agent workflow engine built to automate the entire Software Development Life Cycle (SDLC) without human intervention.

---

## 🎯 Project Mission & Hackathon Objectives

The core objective of this repository is to fully satisfy the **Mission · OPS_000** brief by building an autonomous Software Factory. The pipeline chains specialized, single-responsibility agents end-to-end to deliver verified production code from raw business requirements.

### Target Pipeline Graph

```text
Product ──> Planner ──> Architect ──> TechLead ──> Developer ──> Reviewer ──> QA ──> DevOps
```

> The **implemented** architecture (two planes — a Nexus control plane `PO→SA→TPM` and an Executor
> worker-plane FSM) is documented with C4 diagrams in **[docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)**.

### Mandated Success Criteria

* **Absolute Autonomy**: Achieve ≥ 80% human-free execution across the workflow.
* **Deterministic Execution**: Strict machine-readable Pydantic/JSON contracts between every node to prevent semantic degradation.
* **Resilience**: The engine must autonomously process, route, and heal from at least 2 simulated runtime or compilation failures.
* **Immutable Verification**: Code passes tests generated independently by a QA agent, isolated from the Developer agent's write scope.

---

## 📚 Documentation

Full docs live under **[docs/](./docs/README.md)** (start there). Highlights:

* **[docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)** — C4 diagrams (System Context, Containers, Executor FSM) + end-to-end sequence, in Mermaid.
* **[docs/guides/](./docs/guides/setup.md)** — environment setup (WSL2, Docker, venv, Gemini key).
* **[docs/decisions/](./docs/decisions/README.md)** — the ADR log (0000–0016), indexed by theme.
* **[CHANGELOG.md](./CHANGELOG.md)** · **[PRACTICUM.md](./PRACTICUM.md)** · **[docs/BACKLOG.md](./docs/BACKLOG.md)** — release history, distilled lessons, open work.

---

## 🛠️ System Architecture & Constraints

As determined during the initial research phase, this project intentionally rejects abstract agentic frameworks (e.g., LangGraph) to ensure low-latency, deterministic execution:

1. **Custom FSM Engine**: Driven by a lightweight Python `asyncio` state machine.
2. **Model Routing Matrix**:
   * **Gemini (default `gemini-3.5-flash`)**: every forced-structured role — the executor's TechLead, QA, Reviewer, TechWriter, and Arbiter (failure triage / contract self-healing) plus the Nexus control plane's Product Owner, Solution Architect, and TPM (optimized via low latency and high Free Tier quotas). Per-role models live in `ROLE_MODELS` (`src/shared/core/config.py`).
   * **Claude (Developer)**: Lead Software Engineer (sandboxed CLI executions via Claude Code). The model and reasoning effort are set in `src/shared/core/config.py` — `DEVELOPER_MODEL` (default `sonnet`) and `DEVELOPER_EFFORT` (default `medium`; one of `low|medium|high|xhigh|max`), forwarded to the CLI as `--model` / `--effort`.
3. **Sandboxed Runtimes**: Isolated Docker containers run code execution and verification gates to prevent agent workspace corruption.
4. **Dual-Channel Observability**: Complete console diagnostics split from a persistent, rotating debug audit log (`sdlc_audit.log`). Real-time input/output token metrics tracked natively.
5. **Git-Anchored Sessions**: Each executor run shallow-clones the target repository into an isolated session directory (`runs/<project>/<NNN>_exec_<ticket>_<ts>_<uid>/repo/`), checks out a `feat/ticket-<ticket>` branch, and treats the single clone's `.git` as the transactional Unit-of-Work. Snapshots use the index diff (`git add -A` → `git diff --cached <base_branch> --name-only`), giving a strict causal delta — including untracked files — while protecting context windows from binary pollution and retry bleed. On full success the orchestrator makes one atomic `feat(<ticket>): …` commit (opt-in `--push`).
6. **Brownfield & Multi-File Support**: The pipeline operates on any external repository via `--repo` and `--ticket`, with `--base-branch` as the diff anchor. Source layout is no longer pinned by CLI flags — the SA/blueprint topology decides source paths (the Developer writes by the contract's full repo-relative paths) and the QA language profile owns test placement. A generated repository topology map is injected into the TechLead and QA contexts so new files land inside existing packages rather than redundant root-level directories, and the TechLead's first `domain_tags` entry declares the target language, dynamically routing stack-specific skill files to the execution agents. QA test generation fans out concurrently via `asyncio.gather` — one isolated test file per production module — bypassing LLM output token ceilings, and returns each complete test file (whole-file assembly, preserving still-valid cases) rather than blind-overwriting the suite.
7. **Fast-Fail Documentation Guardrail**: A deterministic, zero-LLM-cost middleware runs right after the Developer phase: every newly-created file outside the architecture contract must open with a comment-block justification (language-agnostic lexical check over the first 15 lines). A miss triggers a "free reroute" back to the Developer — bypassing the expensive Reviewer/QA nodes without spending the functional circuit-breaker retry budget. After 2 failed reroutes the engine performs a deterministic Hard Halt, dumping the full FSM state to that run's `reports/incident_report.json` (under `runs/<project>/<NNN>_<plane>_<label>_<ts>_<uid>/`) and exiting safely.
8. **Autonomous Contract Self-Healing (Arbiter)**: When a cycle is genuinely stuck (a prior fix already failed, `attempt ≥ ARBITER_TRIGGER_ATTEMPT`), an **Arbiter** agent triages the root cause and adds a third routing target beyond the Developer/QA feedback channels — the **contract** itself. For a contract-level defect no downstream agent can fix (a contradictory algorithm, overlapping error conditions with no precedence, or a fix that would violate a stated NFR), it re-derives (amends) the TechLead contract instead of looping to the breaker; otherwise it routes back to Developer/QA or halts. Amendment is bounded conservatively: `environment_id` is pinned (the platform never thrashes), `MAX_CONTRACT_AMENDMENTS` (default 1) caps rewrites, and each amendment grants a bounded retry-budget bonus (`ARBITER_AMENDMENT_RETRY_BONUS`) over the env-tunable `PIPELINE_MAX_RETRIES` ceiling (the Financial Circuit Breaker remains the absolute bound). See [ADR 0016](./docs/decisions/0016-arbiter-contract-self-healing.md). Separately, Gemini content-filter blocks (`RECITATION` et al.) are treated as deterministic — fail-fast instead of burning the backoff budget, with one paraphrase-guarded retry for `RECITATION` — and the engine injects canonical baseline files (`LICENSE`/`.gitignore`) into `TASK-01` so the model never reproduces training-data boilerplate that trips the filter.

---

## 📦 Project Directory Structure & Artifacts

This repository is strictly organized to provide 100% traceability for evaluation:

```text
async-agentic-sdlc/
├── src/                        # Source code, split into logical planes (Virtual Separation)
│   ├── nexus/                  # Control Plane — idea→plan: po.py / sa.py / tpm.py agents,
│   │                           #   nexus_runner.py (run_nexus) + state.py (NexusState checkpoint)
│   ├── executor/               # Worker Plane — runs one SDLC session
│   │   ├── runner.py           # FSM driver + Nexus⇄executor bridge / resume routing
│   │   ├── agents/             # TechLead, Developer, QA, Reviewer, TechWriter, Arbiter logic
│   │   └── nodes/              # FSM gates (build/test compile gates, SAST)
│   └── shared/                 # Shared Plane — common foundations reused across planes
│       ├── core/               # Pydantic models, observability, env config, prompt loader, baseline files
│       └── utils/              # Subprocess + workspace-path-safe helpers
├── prompts/                    # Runtime agent instructions (decoupled from src/ logic)
│   ├── system/                 # Per-role system prompts (po, sa, tpm, techlead, developer, qa, reviewer, techwriter)
│   └── skills/                 # Reusable prompt fragments injected into agents (engineering_guide, strict_validation, deterministic_mutation)
├── tickets/                    # Sample requirement tickets consumed via -f / --file
├── runs/                       # Volatile per-run sessions (created dynamically, ignored by git)
│   └── <project>/              # One umbrella per idea (Nexus) or ticket (direct executor run)
│       ├── project.json        # Umbrella manifest (idea, target repo, base branch) reused by every run
│       ├── 001_nexus_plan_<ts>_<uid>/      # Numbered, human-readable run dir (plane + label + time)
│       │   ├── artifacts/      # Generated control-plane output (epic.md, blueprint.md, TASK-*.md)
│       │   ├── logs/           # Per-run audit log (sdlc_audit.log)
│       │   └── reports/        # checkpoint.json (resume) + finops/incident json
│       └── 002_exec_TASK-01_<ts>_<uid>/    # Executor run for a ticket of this project
│           ├── repo/           # Shallow clone of the target repo on branch feat/ticket-<ticket>
│           ├── logs/           # Per-run audit log
│           └── reports/        # checkpoint + finops + incident json (kept OUTSIDE the clone)
├── docs/                       # Documentation — start at docs/README.md
│   ├── README.md               # Docs index / front door (navigation table)
│   ├── ARCHITECTURE.md         # C4 diagrams: context / container / executor-FSM (Mermaid)
│   ├── guides/                 # setup.md · docker-on-windows.md (environment bring-up)
│   ├── decisions/              # Architecture Decision Records (MADR) 0000–0016 + index README
│   ├── releases/               # Per-iteration release write-ups (iteration_NN/)
│   └── BACKLOG.md              # Open, deferred fixes (prioritized)
├── main.py                     # Root CLI entrypoint: runs src/executor/runner.py:main()
├── CLAUDE.md                   # Claude Code project governance: CLI economy, dev commands, guardrails
├── CHANGELOG.md                # Release history (Keep a Changelog), linked to ADRs
├── PRACTICUM.md                # Project manifest & Key Engineering Takeaways
├── requirements.txt            # Explicit dependency manifest
├── LICENSE                     # Apache License 2.0 — the engine's own license
├── .gitignore                  # Ignores runs/ — runtime session state stays out of git
└── README.md                   # System mission briefing & specifications
```

**Separation of concerns:** `src/` holds the committed engine source code, while each
`runs/<project>/` groups one idea/ticket — its `project.json` plus numbered, human-readable run dirs
(`NNN_<plane>_<label>_<timestamp>_<uid>`) so a glance tells you the task, the plane (`nexus`/`exec`),
and the order. Every run is its own dir (the `uid` suffix guarantees no overwrite). The engine repo
root stays clean because `.gitignore` excludes `runs/`, so you keep local session history without
polluting `git status`.

---

## 🚀 Quick Start & Local Execution

### Prerequisites

For full environment setup (WSL2, Docker, Python venv, Claude CLI), see [docs/guides/setup.md](./docs/guides/setup.md).

Ensure your local environment variable contains a valid Gemini credential:

```bash
export GEMINI_API_KEY="your-api-key-here"
```

### Execution

Run the main orchestrator loop to initiate the autonomous code-generation and testing pipeline:

```bash
# Target repo + ticket are required; inline description is the task body (falls back to the ticket).
python3 main.py --repo https://github.com/acme/widgets.git --ticket WID-42 \
    "Implement is_prime(num: int) -> bool"

# Task body from a file, with a base-branch anchor. Source/test layout is contract-/profile-driven
# (the blueprint topology decides source paths; the QA language profile decides test placement).
python3 main.py --repo /path/to/local/repo --ticket WID-43 \
    -f tickets/003_multi_file_geometry.md --base-branch main

# Push the feature branch (feat/ticket-<ticket>) to origin after the atomic success commit.
python3 main.py --repo git@github.com:acme/widgets.git --ticket WID-44 "..." --push

# Resume from a persisted checkpoint after a crash or restart — by project + run number…
python3 main.py --resume widgets-is-prime 002
# …a bare project slug continues the latest Nexus planning run…
python3 main.py --resume widgets-is-prime
# …or the legacy explicit checkpoint path (also resets the retry budget here).
python3 main.py --resume runs/<project>/002_exec_WID-42_<ts>_<uid>/reports/checkpoint.json --reset-attempts
```

### Nexus control plane (idea → plan → per-ticket execution)

```bash
# Start a NEW project: expand an idea into Epic + Blueprint + tickets. --repo (optional) is captured
# into the project so the ticket runs below reuse it.
python3 main.py --idea "CLI that converts JSON to CSV with a selectable delimiter" --repo git@github.com:acme/widgets.git

# Execute one generated ticket; it runs under the SAME project umbrella, repo taken from project.json.
python3 main.py --run cli-that-converts-json-to-csv -f TASK-01
```

Each run is isolated under `runs/<project>/<NNN>_<plane>_<label>_<ts>_<uid>/`: an executor run
shallow-clones the target repo into `repo/` on a `feat/ticket-<ticket>` branch, and a single rolling
`reports/checkpoint.json` is written after every critical FSM node (TechLead approval, QA approval,
end of each self-heal cycle). On `--resume`,
nodes whose outputs are already present in the restored context are bypassed, and the Circuit Breaker
counter (`current_attempt`) is honoured exactly as it was persisted. When all gates pass, the verified work
is committed atomically to the feature branch.

---

## 📊 Monitoring Token Usage & Costs (FinOps)

The orchestrator natively extracts and logs token usage for Google GenAI models (TechLead, QA, Reviewer) directly to the console stream and `sdlc_audit.log` file. Their USD cost is **estimated** from the `MODEL_PRICING_MATRIX` in `src/shared/core/config.py` using exact-precision `decimal.Decimal` arithmetic (rates initialised from strings — no float drift). The matrix is **cache-aware** (cached tokens priced at the cheaper `cached_read` rate) and **context-tiered** (a `short`/`long` tier split at `LONG_CONTEXT_THRESHOLD` = 200k prompt tokens). These rates are estimates: tune them to your billing tier. (Claude's cost, by contrast, is authoritative — reported by the CLI. Multimodal image/audio inputs are currently priced at the text rate.)

The Developer Agent (Claude CLI) runs out-of-band via localized shell processes, but its token usage is now tracked **in real time** inside `GlobalPipelineContext` — the orchestrator parses the Claude CLI `--output-format json` result envelope (token counts, including cache, plus `total_cost_usd`) and accumulates a per-agent telemetry breakdown that is persisted into `checkpoint.json` (so the budget survives `--resume`).

This live signal feeds a **Financial Circuit Breaker**. Its **primary** gate is USD spend (`PIPELINE_BUDGET_USD`, default `$10.00`, env-overridable) — authoritative for Claude (CLI `total_cost_usd`) and estimated for Gemini — with the cumulative **fresh** token total (`PIPELINE_BUDGET_TOKENS`, default `1_000_000`, env-overridable) retained as a secondary ceiling. Cache read/write tokens are tracked separately and **excluded** from the token budget (the agentic Claude CLI re-sends its prompt each internal turn, so cheap cache reads would otherwise inflate the count). When either threshold is breached, the FSM performs a deterministic hard-halt after the offending node, dumping the full telemetry breakdown to `incident_report.json` instead of draining the API budget to exhaustion during a Developer/Reviewer/QA retry loop.

Cost is reported **per provider** so estimate and fact are never conflated: each cycle logs a sub-total line `[FINOPS] Gemini est. $X | Claude $Y | Σ $Z` (Gemini estimated from `MODEL_PRICING`, Claude authoritative from the CLI), and the run ends with a **GRAND TOTAL** block (per-agent + per-provider + % of budget). The full breakdown is persisted to that run's `reports/finops_report.json` (under `runs/<project>/<NNN>_<plane>_<label>_<ts>_<uid>/`) on both success and hard-halt, for the Nexus control plane as well as the executor.

For historical billing reconciliation across days and sessions, the full report is still available out-of-band:

```bash
npx ccusage
```

For the release-by-release history see [CHANGELOG.md](./CHANGELOG.md), the decision records in [docs/decisions/](./docs/decisions/), and the distilled engineering patterns in [PRACTICUM.md](./PRACTICUM.md).

---

## 🛠️ Developer Meta-Tools (AI-Assisted Maintenance)

The repository ships a set of native [Claude Code Agent Skills](https://docs.claude.com/en/docs/claude-code/skills) under `.claude/skills/` that automate project governance, maintain the engineering journal, and keep documentation in sync. They are auto-discoverable (invoke with `/name`, or let Claude trigger them from their description) and strictly separated from the core runtime agent prompts in `prompts/`. Project knowledge is encoded as path-scoped rules under `.claude/rules/`.

Run these at the end of an iteration or when a milestone is reached:

* **`/adr-generation`** — Generate Architecture Decision Records. Analyzes recent git diffs to catch systemic architectural shifts and documents them in MADR format into `docs/decisions/`.
* **`/docs-sync`** — Synchronize factual docs. Parses recent commits to update `CHANGELOG.md` (Keep a Changelog standard) and align `README.md` with new CLI flags / configuration.
* **`/practicum-update`** — Distill engineering lessons. Reflects on the latest ADR to extract generalized multi-agent patterns into `PRACTICUM.md`.
* **`/iteration-release`** — One-shot release documentation: runs the three skills above plus an iteration archive, with all cross-links resolved.
* **`/analyze-run`** — On-demand run diagnostics. Evidence-first root-cause analysis of a failed, looping, or circuit-breaker-halted pipeline run: reads the run's `reports/checkpoint.json` + `logs/sdlc_audit.log` + incident/finops, classifies the cause (content-filter block, agent-fixable bug, contract conflict, environment misconfig, budget breach), and points the fix at `src/`/`prompts/` — never the generated clone.

Non-interactive form: `claude -p "/adr-generation"`.

---

## 📄 License

Released under the [Apache License 2.0](./LICENSE). You are free to use, modify, and distribute this software, including for commercial purposes, provided you retain the copyright/attribution notices and state significant changes; the Apache 2.0 grant also includes an explicit patent license. The software is provided "as is", without warranty.
