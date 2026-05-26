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
   * **Gemini 2.5/3.5 Flash**: Architect and QA nodes (optimized via Context Caching).
   * **Claude 3.5 Sonnet**: Lead Software Engineer (optimized via Prompt Caching inside sandboxed CLI executions).
3. **Sandboxed Runtimes**: Isolated Docker containers run code execution and verification gates to prevent agent workspace corruption.

---

## 📦 Project Directory Structure & Artifacts

This repository is strictly organized to provide 100% traceability for evaluation:

```text
async-agentic-sdlc/
├── docs/
│   ├── archive/                # Chronological snapshot history
│   │   ├── iteration_000/      # Cloud Infra & FSM Architecture Research
│   │   ├── iteration_001/      # Baseline sequential loop (Trapped Test Sabotage)
│   │   └── iteration_002/      # Async Fork-Join & QA Node Isolation (Success)
│   ├── docker-on-windows.md    # Active host runtime configuration
│   └── setup.md                # Active environment configuration
├── orchestrator.py             # Current operational workflow engine
├── PRACTICUM.md                # Global Executive Summary & Engineering Journal
├── requirements.txt            # Explicit dependency manifest
└── README.md                   # System mission briefing & specifications
```

---

## 🚀 Quick Start & Local Execution

### Prerequisites

For full environment setup (WSL2, Docker, Python venv, Claude CLI), see [docs/setup.md](./docs/setup.md).

Ensure your local environment variable contains a valid Gemini credential and that the Docker engine is running natively (without Docker Desktop if restricted):

```bash
export GEMINI_API_KEY="your-api-key-here"
```

### Execution

Run the main orchestrator loop to initiate the autonomous code-generation and testing pipeline:

```bash
python3 orchestrator.py
```

For the step-by-step engineering log, metrics tracker, and architectural breakthroughs, see the [Architecture Journal (PRACTICUM.md)](./PRACTICUM.md).
