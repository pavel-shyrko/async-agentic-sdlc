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
│   ├── core/                   # Pydantic models, observability, env config
│   ├── agents/                 # Architect, Developer, QA, Reviewer logic
│   ├── nodes/                  # FSM validation gates (functional tests, SAST)
│   └── utils/                  # Subprocess + workspace-path-safe helpers
├── artifacts/                  # Volatile runtime state (created dynamically, ignored by git)
│   ├── code/                   # Generated production source files
│   ├── tests/                  # Generated unit test files
│   ├── logs/                   # Log outputs (sdlc_audit.log)
│   └── reports/                # Incident reports and json states
├── docs/
│   ├── archive/                # Chronological snapshot history
│   │   ├── iteration_000/      # Cloud Infra & FSM Architecture Research
│   │   ├── iteration_001/      # Baseline sequential loop (Trapped Test Sabotage)
│   │   ├── iteration_002/      # Async Fork-Join & QA Node Isolation (Success)
│   │   └── iteration_003/      # Observability, Token Tracking & Gemini 2.5 Routing
│   │   ├── iteration_004/      # Architectural decoupling & modularization
│   │   └── iteration_005/      # Git-Driven State Tracking & QA Fan-Out Concurrency
│   ├── docker-on-windows.md    # Active host runtime configuration
│   └── setup.md                # Active environment configuration
├── orchestrator.py             # Thin entrypoint: wires src/ components + FSM loop
├── PRACTICUM.md                # Global Executive Summary & Engineering Journal
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
```

---

## 📊 Monitoring Token Usage & Costs (FinOps)

The orchestrator natively extracts and logs token usage for Google GenAI models (Architect, QA, Reviewer) directly to the console stream and `sdlc_audit.log` file.

Because the Developer Agent (Claude CLI) runs out-of-band via localized shell processes, its token consumption, prompt caching, and cost analytics must be audited retrospectively. Run the following command in your terminal to output the full daily billing and session usage report:

```bash
npx ccusage
```

For the step-by-step engineering log, metrics tracker, and architectural breakthroughs, see the [Architecture Journal (PRACTICUM.md)](./PRACTICUM.md).
