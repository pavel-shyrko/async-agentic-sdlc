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
5. **Git-Anchored Sessions**: Each run shallow-clones the target repository into an isolated session directory (`runs/run_<uuid>/repo/`), checks out a `feat/ticket-<ticket>` branch, and treats the single clone's `.git` as the transactional Unit-of-Work. Snapshots use the index diff (`git add -A` → `git diff --cached <base_branch> --name-only`), giving a strict causal delta — including untracked files — while protecting context windows from binary pollution and retry bleed. On full success the orchestrator makes one atomic `feat(<ticket>): …` commit (opt-in `--push`).
6. **Brownfield & Multi-File Support**: The pipeline operates on any external repository via `--repo` and `--ticket`, with `--src-dir` / `--tests-dir` selecting the target paths inside the clone and `--base-branch` as the diff anchor. A generated repository topology map is injected into the Architect and QA contexts so new files land inside existing packages rather than redundant root-level directories, and the Architect's first `domain_tags` entry declares the target language, dynamically routing stack-specific skill files to the execution agents. QA test generation fans out concurrently via `asyncio.gather` — one isolated test file per production module — bypassing LLM output token ceilings, and merges into any existing on-disk test suite instead of overwriting it.
7. **Fast-Fail Documentation Guardrail**: A deterministic, zero-LLM-cost middleware runs right after the Developer phase: every newly-created file outside the architecture contract must open with a comment-block justification (language-agnostic lexical check over the first 15 lines). A miss triggers a "free reroute" back to the Developer — bypassing the expensive Reviewer/QA nodes without spending the functional circuit-breaker retry budget. After 2 failed reroutes the engine performs a deterministic Hard Halt, dumping the full FSM state to `runs/run_<uuid>/reports/incident_report.json` and exiting safely.

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
├── runs/                       # Volatile per-run sessions (created dynamically, ignored by git)
│   └── run_<uuid>/             # One isolated session per orchestrator run
│       ├── repo/               # Shallow clone of the target repo on branch feat/ticket-<ticket>
│       │   ├── <src-dir>/      # Production source the Developer agent mutates (default src/)
│       │   └── <tests-dir>/    # Tests the QA agent generates (default tests/)
│       ├── logs/               # Per-session audit log (sdlc_audit.log)
│       └── reports/            # Checkpoint + incident json states (kept OUTSIDE the clone)
├── docs/
│   ├── adr/                                    # Architecture Decision Records (MADR)
│   │   ├── 0000-cloud-infra-fsm-research.md    # Cloud Infra & FSM Architecture Research
│   │   ├── 0001-baseline-sequential-loop.md    # Baseline sequential loop (Trapped Test Sabotage)
│   │   ├── 0002-async-qa-node-isolation.md     # Async Fork-Join & QA Node Isolation
│   │   ├── 0003-dual-channel-observability.md  # Observability, Token Tracking & Gemini 2.5 Routing
│   │   ├── 0004-modularization-sandbox-hardening.md       # Architectural decoupling & modularization
│   │   ├── 0005-git-driven-state-tracking-qa-fanout.md    # Git-Driven State Tracking & QA Fan-Out
│   │   ├── 0006-fsm-state-serialization-resume.md         # FSM State Serialization & Resume Mechanism
│   │   ├── 0007-prompt-schema-layer-separation.md         # Prompt/Schema Layer Separation
│   │   ├── 0008-git-anchored-sessions-atomic-commit.md    # Git-Anchored Sessions & Atomic Commit
│   │   ├── 0009-hybrid-skill-routing.md                   # Hybrid Skill Routing (declarative frontmatter)
│   │   └── 0010-fast-fail-documentation-guardrail.md      # Fast-Fail Documentation Guardrail & Smart Triage
│   ├── docker-on-windows.md    # Active host runtime configuration
│   └── setup.md                # Active environment configuration
├── orchestrator.py             # Thin entrypoint: wires src/ components + FSM loop
├── CHANGELOG.md                # Release history (Keep a Changelog), linked to ADRs
├── PRACTICUM.md                # Project manifest & Key Engineering Takeaways
├── requirements.txt            # Explicit dependency manifest
├── .gitignore                  # Ignores artifacts/ and runs/ — runtime state stays out of git
└── README.md                   # System mission briefing & specifications
```

**Separation of concerns:** `src/` holds the committed engine source code, while each
`runs/run_<uuid>/` holds one volatile, git-anchored session — the cloned target repo plus its
own logs/reports. The engine repo root stays clean because `.gitignore` excludes both
`artifacts/` (legacy) and `runs/`, so you keep local session history without polluting
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
# Target repo + ticket are required; inline description is the task body (falls back to the ticket).
python3 orchestrator.py --repo https://github.com/acme/widgets.git --ticket WID-42 \
    "Implement is_prime(num: int) -> bool"

# Task body from a file, with custom source/tests paths inside the repo and a base-branch anchor.
python3 orchestrator.py --repo /path/to/local/repo --ticket WID-43 \
    -f tickets/003_multi_file_geometry.md --src-dir src/ --tests-dir tests/ --base-branch main

# Push the feature branch (feat/ticket-<ticket>) to origin after the atomic success commit.
python3 orchestrator.py --repo git@github.com:acme/widgets.git --ticket WID-44 "..." --push

# Resume from a persisted checkpoint after a crash or process restart (path is run-scoped).
python3 orchestrator.py --resume runs/run_<uuid>/reports/checkpoint.json

# Resume but reset the Circuit Breaker retry budget (e.g. after fixing an agent prompt).
python3 orchestrator.py --resume runs/run_<uuid>/reports/checkpoint.json --reset-attempts
```

Each run is isolated under `runs/run_<uuid>/`: the target repo is shallow-cloned into `repo/` on a
`feat/ticket-<ticket>` branch, and a single rolling `runs/run_<uuid>/reports/checkpoint.json` is written
after every critical FSM node (Architect approval, QA approval, end of each self-heal cycle). On `--resume`,
nodes whose outputs are already present in the restored context are bypassed, and the Circuit Breaker
counter (`current_attempt`) is honoured exactly as it was persisted. When all gates pass, the verified work
is committed atomically to the feature branch.

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
