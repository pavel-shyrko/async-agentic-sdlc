# Async Agentic SDLC Orchestrator (OPS_000)

An engineered, deterministic multi-agent workflow engine built to automate the entire Software Development Life Cycle (SDLC) without human intervention.

---

## 🎯 Project Mission & Hackathon Objectives

The core objective of this repository is to fully satisfy the **Mission · OPS_000** brief by building an autonomous Software Factory. The pipeline chains specialized, single-responsibility agents end-to-end to deliver verified production code from raw business requirements.

### Target Pipeline Graph

```text
Product ──> Planner ──> Architect ──> Developer ──> Reviewer ──> QA ──> DevOps
```

### Mandated Success Criteria

* **Absolute Autonomy**: Achieve ≥ 80% human-free execution across the workflow.
* **Deterministic Execution**: Strict machine-readable Pydantic/JSON contracts between every node to prevent semantic degradation.
* **Resilience**: The engine must autonomously process, route, and heal from at least 2 simulated runtime or compilation failures.
* **Immutable Verification**: Code passes tests generated independently by a QA agent, isolated from the Developer agent's write scope.

---

## 🛠️ System Architecture & Constraints

As determined during the initial research phase, this project intentionally rejects abstract agentic frameworks (e.g., LangGraph) to ensure low-latency, deterministic execution:

1. **Custom FSM Engine**: Driven by a lightweight Python `asyncio` state machine.
2. **Model Routing Matrix**:
   * **Gemini 2.5 Flash / Pro**: Architect, QA, and Reviewer nodes (optimized via low latency and high Free Tier quotas).
   * **Claude 4.6 Sonnet**: Lead Software Engineer (sandboxed CLI executions via Claude Code).
3. **Sandboxed Runtimes**: Isolated Docker containers run code execution and verification gates to prevent agent workspace corruption.
4. **Dual-Channel Observability**: Complete console diagnostics split from a persistent, rotating debug audit log (`sdlc_audit.log`). Real-time input/output token metrics tracked natively.
5. **Git-Driven State Tracking**: Agent sandboxes are initialized as isolated Git repositories. All snapshot collection uses `git diff <base_branch> --name-only`, providing a strict causal delta and protecting context windows from binary pollution and retry bleed.
6. **Brownfield & Multi-File Support**: The pipeline accepts multi-file architecture contracts and processes them via a `--base-branch` CLI flag. QA test generation fans out concurrently via `asyncio.gather` — one isolated test file per production module — bypassing LLM output token ceilings.

---

## 📦 Project Directory Structure & Artifacts

This repository is strictly organized to provide 100% traceability for evaluation:

```text
async-agentic-sdlc/
├── src/                        # Source code (the Software Factory itself)
│   ├── core/                   # Pydantic models, observability, env config, prompt loader
│   ├── agents/                 # Architect, Developer, QA, Reviewer logic
│   ├── nodes/                  # FSM validation gates (functional tests, SAST)
│   └── utils/                  # Subprocess + workspace-path-safe helpers
├── prompts/                    # Runtime agent instructions (decoupled from src/ logic)
│   ├── system/                 # Per-role system prompts (planner, architect, developer, qa, reviewer)
│   └── skills/                 # Reusable prompt fragments injected into agents (engineering_guide, strict_validation, deterministic_mutation)
├── tickets/                    # Sample requirement tickets consumed via -f / --file
├── artifacts/                  # Volatile runtime state (created dynamically, ignored by git)
│   ├── code/                   # Generated production source files
│   ├── tests/                  # Generated unit test files
│   ├── logs/                   # Log outputs (sdlc_audit.log)
│   └── reports/                # Incident reports and json states
├── docs/
│   ├── adr/                                    # Architecture Decision Records (MADR)
│   │   ├── 0000-cloud-infra-fsm-research.md    # Cloud Infra & FSM Architecture Research
│   │   ├── 0001-baseline-sequential-loop.md    # Baseline sequential loop (Trapped Test Sabotage)
│   │   ├── 0002-async-qa-node-isolation.md     # Async Fork-Join & QA Node Isolation
│   │   ├── 0003-dual-channel-observability.md  # Observability, Token Tracking & Gemini 2.5 Routing
│   │   ├── 0004-modularization-sandbox-hardening.md       # Architectural decoupling & modularization
│   │   ├── 0005-git-driven-state-tracking-qa-fanout.md    # Git-Driven State Tracking & QA Fan-Out
│   │   ├── 0006-fsm-state-serialization-resume.md         # FSM State Serialization & Resume Mechanism
│   │   └── 0007-prompt-schema-layer-separation.md         # Prompt/Schema Layer Separation
│   ├── docker-on-windows.md    # Active host runtime configuration
│   └── setup.md                # Active environment configuration
├── orchestrator.py             # Thin entrypoint: wires src/ components + FSM loop
├── CHANGELOG.md                # Release history (Keep a Changelog), linked to ADRs
├── PRACTICUM.md                # Project manifest & Key Engineering Takeaways
├── requirements.txt            # Explicit dependency manifest
├── .gitignore                  # Ignores artifacts/ — runtime state stays out of git
└── README.md                   # System mission briefing & specifications
```

**Separation of concerns:** `src/` holds the committed source code, while `artifacts/` holds
all volatile runtime state produced by the agents. The repo root stays clean because
`.gitignore` excludes `artifacts/` — you keep local iteration history without polluting
`git status`.

---

## 🚀 Quick Start & Local Execution

### Prerequisites

For full environment setup (WSL2, Docker, Python venv, Claude CLI), see [docs/setup.md](./docs/setup.md).

Ensure your local environment variable contains a valid Gemini credential:

```bash
export GEMINI_API_KEY="your-api-key-here"
```

### Execution

Run the main orchestrator loop to initiate the autonomous code-generation and testing pipeline:

```bash
# Inline task description
python3 orchestrator.py "Implement is_prime(num: int) -> bool"

# Task from a file (brownfield — specify the repo's main branch as anchor)
python3 orchestrator.py -f tickets/003_multi_file_geometry.md --base-branch main

# Resume from a persisted checkpoint after a crash or process restart
python3 orchestrator.py --resume artifacts/reports/checkpoint.json

# Resume but reset the Circuit Breaker retry budget (e.g. after fixing an agent prompt)
python3 orchestrator.py --resume artifacts/reports/checkpoint.json --reset-attempts
```

The orchestrator writes a single rolling `artifacts/reports/checkpoint.json` after every
critical FSM node (Architect approval, QA approval, end of each self-heal cycle). On
`--resume`, nodes whose outputs are already present in the restored context are bypassed,
and the Circuit Breaker counter (`current_attempt`) is honoured exactly as it was persisted.

---

## 📊 Monitoring Token Usage & Costs (FinOps)

The orchestrator natively extracts and logs token usage for Google GenAI models (Architect, QA, Reviewer) directly to the console stream and `sdlc_audit.log` file.

Because the Developer Agent (Claude CLI) runs out-of-band via localized shell processes, its token consumption, prompt caching, and cost analytics must be audited retrospectively. Run the following command in your terminal to output the full daily billing and session usage report:

```bash
npx ccusage
```

For the release-by-release history see [CHANGELOG.md](./CHANGELOG.md), the decision records in [docs/adr/](./docs/adr/), and the distilled engineering patterns in [PRACTICUM.md](./PRACTICUM.md).

---

## 🛠️ Developer Meta-Tools (AI-Assisted Maintenance)

The repository includes a set of isolated meta-instructions (skills) for your IDE Assistant (e.g., Claude Code, GitHub Copilot, Cursor) to automate project governance, maintain the engineering journal, and keep documentation in sync. These are strictly separated from the core runtime agent prompts located in `prompts/`.

Run these explicit commands at the end of an iteration or when a milestone is reached:

* **Generate Architecture Decision Records (ADR):**
    Analyzes recent git diffs to catch systemic architectural shifts and document them using the MADR format into `docs/adr/`.
    ```bash
    claude -p "Run .ai/skills/adr_generation.md to document recent architectural changes."
    ```

* **Synchronize Factual Docs (Changelog & README):**
    Parses recent commits to automatically update the project `CHANGELOG.md` strictly matching the "Keep a Changelog" standard and align `README.md` with new CLI flags or configuration parameters.
    ```bash
    claude -p "Run .ai/skills/docs_sync.md to update factual documentation."
    ```

* **Distill Engineering Lessons (Practicum Manifest):**
    Reflects on the latest ADR to extract generalized multi-agent engineering patterns, adding high-level takeaways directly into `PRACTICUM.md`.
    ```bash
    claude -p "Run .ai/skills/practicum_update.md to distill engineering lessons from the latest ADR."
    ```
