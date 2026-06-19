# Architecture (C4)

A deterministic, multi-agent **SDLC automation engine**: it turns a one-line product idea into a planned
backlog and then implements each ticket as verified, committed code — with no human in the loop. It is a
custom Python `asyncio` Finite State Machine (no agentic framework), split into two planes: a **Nexus
control plane** (idea → plan) and an **Executor worker plane** (one ticket → committed code).

This document follows the [C4 model](https://c4model.com/): **Level 1 (System Context)** → **Level 2
(Containers)** → **Level 3 (Components)** — zooming from "who uses it and what it talks to" down to "how
the executor's self-healing loop works." Diagrams are Mermaid (GitHub-rendered). The authoritative SSOTs
are [repo-module-map](../.claude/rules/repo-module-map.md), [pipeline-fsm-loops](../.claude/rules/pipeline-fsm-loops.md),
and [agent-provider-model-map](../.claude/rules/agent-provider-model-map.md); this doc visualizes them.

---

## Level 1 — System Context

Who operates the engine and which external systems it depends on.

```mermaid
flowchart TB
    human(["👤 Human Operator<br/>(developer / maintainer)"])

    engine["⚙️ Agentic SDLC Engine<br/>Python asyncio FSM · two planes<br/>(Nexus control + Executor worker)"]

    gemini["☁️ Google Gemini API<br/>structured output via instructor"]
    claude["🤖 Claude Code CLI<br/>agentic file-editing (Developer)"]
    docker["🐳 Docker Engine<br/>sandboxed build / test / SAST"]
    github["🔗 Git / GitHub remote<br/>+ target repository"]

    human -->|"--idea / --run / --resume (CLI)"| engine
    engine -->|"epic, blueprint, tickets;<br/>logs, FinOps, atomic commit"| human

    engine -->|"prompts → structured JSON<br/>(PO/SA/TPM, TechLead, QA,<br/>Reviewer, TechWriter, Arbiter)"| gemini
    engine -->|"prompt + tools → file edits<br/>(Developer only)"| claude
    engine -->|"run code in least-priv container"| docker
    engine -->|"shallow clone, branch,<br/>atomic commit, optional push"| github

    classDef sys fill:#1168bd,stroke:#0b4884,color:#fff;
    classDef ext fill:#999,stroke:#6b6b6b,color:#fff;
    classDef person fill:#08427b,stroke:#052e56,color:#fff;
    class engine sys;
    class gemini,claude,docker,github ext;
    class human person;
```

**Key:**
- **Human Operator** drives everything through one CLI (`main.py` → `src/executor/runner.py` `main()`):
  `--idea` plans a new project, `--run <project> -f <ticket>` executes a ticket, `--resume` recovers.
- **Google Gemini API** — every *structured* agent (forced Pydantic output via `instructor`):
  PO/SA/TPM (planning) and TechLead/QA/Reviewer/TechWriter/Arbiter (execution).
- **Claude Code CLI** — the *Developer* agent only; agentic, edits files directly in the run's clone.
- **Docker Engine** — runs the build, unit-test, and SAST gates in a hardened, least-privilege container
  (`--network none` for test/SAST).
- **Git / GitHub remote + target repository** — the executor shallow-clones the target repo, works on a
  `feat/ticket-<id>` branch, and makes one atomic commit (optionally pushed) on full success.

---

## Level 2 — Containers

The major runtime units inside the engine boundary and how they collaborate.

```mermaid
flowchart TB
    human(["👤 Human Operator"])
    cli["main.py → runner.main()<br/><i>CLI parse + plane routing</i>"]

    subgraph engine["Agentic SDLC Engine"]
        direction TB
        nexus["🧭 Nexus Control Plane<br/>src/nexus/ · PO → SA → TPM<br/><i>idea → epic → blueprint → tickets</i>"]
        executor["🏗️ Executor Worker Plane<br/>src/executor/ · FSM loop<br/><i>one ticket → committed code</i>"]
        shared["🧱 Shared Plane<br/>src/shared/ core + utils<br/><i>models, config, observability,<br/>runs, llm, git, docker adapter</i>"]
        prompts["📝 Prompt Store<br/>prompts/system + prompts/skills<br/><i>per-role prompts + gated skills</i>"]
        images["🐳 Sandbox Images<br/>docker/*.Dockerfile<br/><i>per-language hardened runtimes</i>"]
        runstore[("🗂️ Run Store (filesystem)<br/>runs/&lt;project&gt;/…<br/>project.json · checkpoint.json<br/>artifacts/ · repo/ · logs · reports")]
    end

    gemini["☁️ Gemini API"]
    claude["🤖 Claude CLI"]
    docker["🐳 Docker Engine"]
    github["🔗 Git / GitHub + target repo"]

    human --> cli
    cli -->|"--idea"| nexus
    cli -->|"--run / --resume"| executor

    nexus --> shared
    executor --> shared
    nexus -->|"epic/blueprint/TASK-*.md + checkpoint"| runstore
    executor -->|"checkpoint, finops, incident, clone"| runstore
    nexus -.->|"reads role prompts"| prompts
    executor -.->|"reads role prompts + skills"| prompts

    shared -->|"structured calls (instructor)"| gemini
    shared -->|"agentic Developer session"| claude
    executor -->|"run_in_image (gates)"| docker
    docker --> images
    executor -->|"clone / branch / commit / push"| github

    classDef plane fill:#1168bd,stroke:#0b4884,color:#fff;
    classDef store fill:#2d6a4f,stroke:#1b4332,color:#fff;
    classDef ext fill:#999,stroke:#6b6b6b,color:#fff;
    class nexus,executor,shared,prompts,images plane;
    class runstore store;
    class gemini,claude,docker,github ext;
```

**Key:**
- **Nexus control plane** (`src/nexus/`) — linear, no loops, no Docker/git: `run_nexus` drives PO → SA →
  TPM, writing `artifacts/{epic.md, blueprint.md, TASK-*.md}` + a `NexusState` checkpoint. Needs only the
  Gemini key.
- **Executor worker plane** (`src/executor/`) — `runner.py` is the FSM driver; `agents/` holds the six
  execution agents; `nodes/gates.py` runs build/test/SAST. Full git + Docker isolation per run.
- **Shared plane** (`src/shared/`) — the engine SSOTs both planes import: `core/` (`models.py`,
  `config.py` incl. `ROLE_MODELS`, `observability.py`, `runs.py`, `docker_adapter.py`, `environments.py`,
  `prompts.py`) and `utils/` (`llm.py`, `api_retry.py`, `git_helpers.py`, `subprocess_helpers.py`,
  `redaction.py`). All LLM traffic flows through here.
- **Prompt store** — per-role system prompts (`prompts/system/*.md`) + frontmatter-gated skill fragments
  (`prompts/skills/*.md`) assembled per node by `build_agent_context`.
- **Sandbox images** — pre-built per-language Docker images invoked by `environment_id`.
- **Run store** — the filesystem is the durable state: every run is `runs/<project>/<NNN>_<plane>_<label>_<ts>_<uid>/`
  with `logs/`, `reports/` (checkpoint/finops/incident), and `artifacts/` (Nexus) or `repo/` (Executor).

> **Model routing** ([agent-provider-model-map](../.claude/rules/agent-provider-model-map.md)): every
> structured role is **Gemini** (`ROLE_MODELS` in `config.py`); the **Developer** alone is the **Claude
> CLI**. Gemini cost is *estimated* (`MODEL_PRICING_MATRIX`), Claude cost is *authoritative* (CLI-reported).

---

## Level 3 — Executor FSM (the self-healing loop)

The most intricate part: one ticket's execution cycle. The TechLead derives the contract **once**; the
outer loop then self-heals across cycles via two isolated feedback channels (Developer / QA) plus the
**Arbiter**'s third route (amend the contract). Faithful to
[pipeline-fsm-loops](../.claude/rules/pipeline-fsm-loops.md).

```mermaid
flowchart TB
    boot["bootstrap_session<br/>shallow-clone + feat/ticket-&lt;id&gt; branch"]
    tl["run_techlead_node<br/><i>derive contract (once)</i>"]
    boot --> tl --> cyc

    subgraph cyc["Outer cycle — while attempt ≤ ceiling (💰 breaker checked throughout)"]
        direction TB
        qa["QA: (re)generate tests<br/><i>+ signature-lint reroute</i>"]
        dev["Developer (Claude CLI)<br/><i>+ doc/compile guardrail reroute</i>"]
        gates["Gates (Docker, network-off)<br/>build · unit-tests · SAST"]
        rev["run_reviewer_node<br/><i>code + test verdict, diagnostics</i>"]
        decide{"all_gates_passed?"}
        qa --> dev --> gates --> rev --> decide
    end

    decide -->|"yes"| tw["run_techwriter_node<br/>update living ADR"]
    tw --> commit["finalize_transaction<br/>atomic commit (+ optional push)"]
    commit --> done(["✅ SUCCESS"])

    decide -->|"no"| dlg{"deadlock guard<br/>gate failed yet<br/>both approved?"}
    dlg -->|"yes"| halt(["🛑 incident: env/runner misconfig"])
    dlg -->|"no"| arb{"attempt ≥ ARBITER_TRIGGER_ATTEMPT?"}
    arb -->|"no (early cycle)"| route["route reviewer diagnostics<br/>→ Developer / QA channels"]
    arb -->|"yes"| arbiter["run_arbiter_node<br/><i>triage root cause</i>"]

    arbiter -->|"developer / qa"| route
    arbiter -->|"contract (≤ cap)"| amend["TechLead amend contract<br/><i>env_id pinned · +retry bonus</i>"]
    arbiter -->|"halt / cap reached"| halt2(["🛑 incident: unrecoverable spec conflict"])

    route --> next["next cycle"]
    amend --> next
    next -->|"budget left"| cyc
    next -->|"exhausted"| brk(["🛑 CIRCUIT BREAKER: retries exhausted"])

    classDef ok fill:#2d6a4f,stroke:#1b4332,color:#fff;
    classDef stop fill:#9d0208,stroke:#6a040f,color:#fff;
    classDef dec fill:#e9c46a,stroke:#b08900,color:#000;
    class done ok;
    class halt,halt2,brk stop;
    class decide,dlg,arb dec;
```

**Key:**
- **Contract once, loop many:** `run_techlead_node` runs before the loop; the contract is the single
  source of truth all downstream agents inherit. Cycle 1 generates tests *before* the Developer
  (contract-first).
- **Two isolated channels:** a rejection routes `dev_diagnostic_payload` → Developer (`error_trace`) and
  `qa_diagnostic_payload` → QA (`qa_error_trace`); mis-routing deadlocks the run.
- **Free fast-fail reroutes** (QA signature-lint, Developer doc/compile guardrails, QA test-compile gate)
  bypass the expensive Reviewer without spending the functional retry budget.
- **Arbiter (ADR [0016](decisions/0016-arbiter-contract-self-healing.md)):** on a stuck cycle it adds a
  third route — amend the **contract** — for failures no worker can fix (contradictory spec, missing error
  precedence, NFR-violating "fix"). Bounded: `environment_id` pinned, `MAX_CONTRACT_AMENDMENTS` cap, a
  retry-budget bonus per amendment.
- **Terminals:** SUCCESS (commit), deadlock-guard incident, Arbiter halt, or the Financial Circuit Breaker
  / "retries exhausted" hard-halt — each writes `reports/incident_report.json`.

---

## End-to-end sequence

From a raw idea to committed code across the two planes.

```mermaid
sequenceDiagram
    actor H as Human
    participant N as Nexus (PO→SA→TPM)
    participant FS as Run Store
    participant X as Executor FSM
    participant G as Gemini
    participant C as Claude CLI
    participant R as Git/GitHub

    H->>N: main.py --idea "<idea>"
    N->>G: PO→SA→TPM (structured)
    N->>FS: artifacts/{epic,blueprint,TASK-*}.md + checkpoint
    N-->>H: planned tickets

    H->>X: main.py --run <project> -f TASK-01
    X->>R: shallow-clone → feat/ticket-TASK-01
    X->>G: TechLead → contract
    loop until gates pass or budget exhausted
        X->>G: QA (tests) · Reviewer (verdict) · [Arbiter]
        X->>C: Developer (edit repo/)
        X->>X: Docker gates (build/test/SAST)
    end
    X->>G: TechWriter (living ADR)
    X->>R: atomic commit (+ optional push)
    X-->>H: ✅ committed + FinOps total
```

---

## Component reference

The Level-3 components in text (file → responsibility). See [repo-module-map](../.claude/rules/repo-module-map.md)
for the full module map and [agent-contracts](../.claude/rules/agent-contracts.md) for each agent's I/O model.

| Plane | Component | File | Responsibility |
|---|---|---|---|
| Entry | CLI / router | `main.py` → `src/executor/runner.py` `main()` | Parse args; route to Nexus or Executor; `--resume` dispatch. |
| Nexus | PO / SA / TPM | `src/nexus/{po,sa,tpm}.py` | Idea → Epic → Blueprint → task tickets (structured Gemini). |
| Nexus | Runner / State | `src/nexus/nexus_runner.py`, `state.py` | Drive PO→SA→TPM; `NexusState` checkpoint + resume. |
| Executor | FSM driver | `src/executor/runner.py` | Outer cycle, reroutes, breaker, routing, commit. |
| Executor | TechLead | `src/executor/agents/techlead.py` | Derive (and, in amendment mode, re-derive) the `TechLeadContract`. |
| Executor | Developer | `src/executor/agents/developer.py` | Implement code in the clone (Claude CLI, agentic). |
| Executor | QA | `src/executor/agents/qa.py` | Generate per-module tests (contract-first). |
| Executor | Reviewer | `src/executor/agents/reviewer.py` | Code + test verdict; isolated dev/QA diagnostics. |
| Executor | Arbiter | `src/executor/agents/arbiter.py` | Triage stuck cycle → developer/qa/contract/halt. |
| Executor | TechWriter | `src/executor/agents/techwriter.py` | Maintain the living ADR (`docs/architecture_state.md` in the clone). |
| Executor | Gates | `src/executor/nodes/gates.py` | Build / unit-test / SAST in the sandbox. |
| Shared | Models | `src/shared/core/models.py` | `GlobalPipelineContext`, `TechLeadContract`, `ReviewReport`, `ArbiterVerdict`, telemetry. |
| Shared | Config | `src/shared/core/config.py` | `ROLE_MODELS`, budgets, pricing, FSM constants. |
| Shared | Observability | `src/shared/core/observability.py` | Logging, token/FinOps telemetry, finish-reason diagnostics. |
| Shared | Run layout | `src/shared/core/runs.py` | `Projects` store + `allocate_run_dir` (run-layout SSOT). |
| Shared | Docker adapter | `src/shared/core/docker_adapter.py` | Least-privilege `run_in_image` / `execute_in_sandbox`. |
| Shared | Environments | `src/shared/core/environments.py` | `SUPPORTED_ENVIRONMENTS` (image + build/test cmds + gitignore). |
| Shared | Prompts | `src/shared/core/prompts.py` | `get_system_prompt*`, `build_agent_context` (skill routing). |
| Shared | LLM / retry | `src/shared/utils/{llm,api_retry}.py` | `run_structured_llm`; backoff + non-retryable/RECITATION handling. |

---

*Diagrams reflect the engine as of the Arbiter iteration ([CHANGELOG](../CHANGELOG.md) v0.16.0). For the
"why" behind each decision see [decisions/](decisions/README.md); for what's still open see
[BACKLOG.md](BACKLOG.md).*
