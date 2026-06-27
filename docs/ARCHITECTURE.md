# Architecture (C4)

A deterministic, multi-agent **SDLC automation engine**: it turns a one-line product idea into a planned
backlog and then implements each ticket as verified, committed code — with no human in the loop. It is a
custom Python `asyncio` Finite State Machine (no agentic framework), split into three physical planes over a
shared SSOT (ADR [0021](decisions/0021-physical-three-plane-split.md)): a **Nexus control plane**
(idea → plan → orchestrate), a **Development worker plane** (one ticket → committed code), and a
**Deployment infra plane** (CI/CD scaffolding).

This document follows the [C4 model](https://c4model.com/): **Level 1 (System Context)** → **Level 2
(Containers)** → **Level 3 (Components)** — zooming from "who uses it and what it talks to" down to "how
the per-ticket Executor FSM (`run_executor`) self-heals." Diagrams are Mermaid (GitHub-rendered). The authoritative SSOTs
are [repo-module-map](../.claude/rules/repo-module-map.md), [pipeline-fsm-loops](../.claude/rules/pipeline-fsm-loops.md),
and [agent-provider-model-map](../.claude/rules/agent-provider-model-map.md); this doc visualizes them.

---

## Level 1 — System Context

Who operates the engine and which external systems it depends on.

```mermaid
flowchart TB
    human(["👤 Human Operator<br/>(developer / maintainer)"])

    engine["⚙️ Token Burners Factory<br/>Python asyncio FSM · 3 planes + shared<br/>(nexus · development · deployment · shared)"]

    gemini["☁️ Google Gemini API<br/>gemini-2.5-pro / flash<br/>structured output via instructor"]
    claude["🤖 Claude Code CLI<br/>Developer + QA<br/>(agentic file-editing sessions)"]
    docker["🐳 Docker Engine<br/>4 per-language sandbox images<br/>python · go · node · dotnet"]
    github["🔗 Git / GitHub<br/>target repo + remote"]

    human -->|"--idea [--auto-execute] [--budget] [--base-branch]<br/>--run &lt;project&gt; -f &lt;ticket&gt; [--auto-merge] [--push]<br/>--resume [--scaffold-deploy] [--release] [--reset-attempts]"| engine
    engine -->|"epic · blueprint · TASK-*.md<br/>per-role/plane/time FinOps · atomic commit<br/>PR merge · v* release tag"| human

    engine -->|"structured JSON via instructor<br/>(PO · SA · TPM · TechLead · Reviewer<br/>Arbiter · TechWriter · DevOps)"| gemini
    engine -->|"agentic sessions · tool-use file edits<br/>(Developer · QA)"| claude
    engine -->|"run code in least-privilege container<br/>--network none for test/SAST/lint gates"| docker
    engine -->|"shallow clone · feat/ticket-&lt;id&gt; branch<br/>atomic commit · optional push<br/>PR open/approve/squash-merge (--auto-merge)<br/>deploy-scaffold PR · v* annotated tag (--release)"| github

    classDef sys fill:#1168bd,stroke:#0b4884,color:#fff;
    classDef ext fill:#999,stroke:#6b6b6b,color:#fff;
    classDef person fill:#08427b,stroke:#052e56,color:#fff;
    class engine sys;
    class gemini,claude,docker,github ext;
    class human person;
```

**Key:**
- **Human Operator** drives everything through one CLI (`main.py` → `src/nexus/runner.py` `main()`):
  `--idea` plans a new project; add `--auto-execute` to drive the Executor over **all** planned tickets to
  `main` in TPM order in the same invocation (E3) — implies `--auto-merge`. `--run <project> -f <ticket>`
  executes one ticket; `--resume` recovers from a checkpoint. `--budget <usd>` sets the application-wide
  money ceiling (E5); re-passing a larger value on `--resume` "adds money." `--scaffold-deploy` triggers E4
  post-batch CI/CD scaffolding; `--release` triggers E6 annotated tag push.
- **Google Gemini API** — every *structured* agent (forced Pydantic output via `instructor`):
  PO/SA/TPM (planning) · TechLead/Reviewer/Arbiter/TechWriter (execution) · DevOps (deploy-scaffolding).
  Models: `gemini-2.5-pro` (TechLead, Arbiter, TechWriter, PO, SA, TPM) · `gemini-2.5-flash` (Reviewer, DevOps).
- **Claude Code CLI** — the *Developer* **and** *QA* agents; both run as agentic sessions that edit files
  directly in the run's clone.
- **Docker Engine** — runs build, unit-test, SAST, lint, and format gates in hardened per-language
  containers (`--network none` for test/SAST/lint; network-on for setup/restore). Four pre-built sandbox
  images: `python`, `go`, `node`, `dotnet`.
- **Git / GitHub remote + target repository** — the executor shallow-clones the target repo on a
  `feat/ticket-<id>` branch, makes one atomic commit on full success, optionally pushes; with `--auto-merge`
  it opens, approves, and squash-merges a PR via the `gh`-backed forge seam (ADR 0018).

---

## Level 2 — Containers

The major runtime units inside the engine boundary and how they collaborate.

```mermaid
flowchart TB
    human(["👤 Human Operator"])
    cli["main.py → runner.main()<br/><i>CLI parse · plane routing · batch/resume dispatch</i>"]

    subgraph engine["Agentic SDLC Engine"]
        direction TB

        nexus["🧭 Nexus Control Plane<br/>src/nexus/<br/><i>PO → SA → TPM planning (nexus_runner.py)<br/>run_executor FSM · run_batch E3 · finalize_release E6<br/>reconcile_feedback_routing (ADR 0024)</i>"]

        development["🏗️ Development Worker Plane<br/>src/development/<br/><i>TechLead · Developer · QA · Reviewer · Arbiter · TechWriter<br/>gates.py: build · test · format · lint · SAST</i>"]

        deployment["🚀 Deployment Infra Plane<br/>src/deployment/<br/><i>DevOps agent · run_devops_scaffold (E4)<br/>run_devops_gate (static-lint manifests)</i>"]

        shared["🧱 Shared Plane<br/>src/shared/core/ + utils/<br/><i>models · config · environments · observability<br/>runs · docker_adapter · prompts · llm · forge</i>"]

        prompts["📝 Prompt Store<br/>prompts/system/*.md · prompts/skills/*.md<br/><i>per-role system prompts + frontmatter-gated skill fragments<br/>assembled per node by build_agent_context</i>"]

        images["🐳 Sandbox Images<br/>docker/*.Dockerfile<br/><i>python-3.12 · go-1.23 · node-22 · dotnet-10<br/>least-privilege · cache volumes</i>"]

        runstore[("🗂️ Run Store (filesystem)<br/>runs/&lt;project&gt;/project.json<br/>NNN_nexus_plan_…/artifacts/{epic,blueprint,TASK-*.md}<br/>NNN_exec_&lt;ticket&gt;_…/{repo/ · logs/ · reports/}<br/>NNN_devops_scaffold_…/repo/")]
    end

    gemini["☁️ Gemini API<br/>gemini-2.5-pro/flash"]
    claude["🤖 Claude CLI<br/>Developer + QA"]
    docker["🐳 Docker Engine"]
    github["🔗 Git / GitHub + target repo"]

    human --> cli
    cli -->|"--idea / --run / --resume"| nexus

    nexus -->|"run_executor (per-ticket FSM, E3)"| development
    nexus -.->|"--scaffold-deploy: run_devops_scaffold (E4, post-batch)"| deployment
    deployment -.->|"lazy import: reuses transaction/forge/FinOps SSOTs"| nexus

    nexus --> shared
    development --> shared
    deployment --> shared

    nexus -->|"artifacts · checkpoint · finops<br/>batch_state.json · app_finops_report.json"| runstore
    nexus -.->|"reads role prompts"| prompts
    development -.->|"reads role prompts + skill fragments"| prompts
    deployment -.->|"reads devops prompt + archetype skills"| prompts

    shared -->|"run_structured_llm (instructor)"| gemini
    shared -->|"agentic Developer + QA sessions"| claude
    development -->|"run_in_image (gates: build/test/lint/SAST)"| docker
    docker --> images
    nexus -->|"shallow clone · branch · commit · push<br/>PR open/approve/merge (--auto-merge, E2)<br/>push_tag v* (--release, E6)"| github
    deployment -->|"deploy-scaffold PR (chore/devops-scaffold, E4)"| github

    classDef plane fill:#1168bd,stroke:#0b4884,color:#fff;
    classDef store fill:#2d6a4f,stroke:#1b4332,color:#fff;
    classDef ext fill:#999,stroke:#6b6b6b,color:#fff;
    class nexus,development,deployment,shared,prompts,images plane;
    class runstore store;
    class gemini,claude,docker,github ext;
```

**Key:**
- **Nexus control plane** (`src/nexus/`) — owns planning AND orchestration. `run_nexus` drives PO → SA →
  TPM (linear, no loops; `agents/{po,sa,tpm}.py`), writing
  `artifacts/{epic.md, blueprint.md, TASK-*.md}` + a `NexusState` checkpoint. `runner.py` owns `main()`
  (dispatch/resume), the per-ticket FSM (`run_executor`), and the E3 batch loop (`run_batch`), calling into
  the development/deployment planes — never the reverse, save the one documented lazy-import back-edge.
- **Development worker plane** (`src/development/`) — the six execution agents: TechLead (Gemini),
  Developer (Claude CLI), QA (Claude CLI), Reviewer (Gemini), Arbiter (Gemini), TechWriter (Gemini);
  plus `gates.py` (build / test-compile / **lint** / format / SAST + format pass), run per ticket under
  full git + Docker isolation by the nexus FSM.
- **Deployment infra plane** (`src/deployment/`) — the **DevOps** agent (`agents/devops.py`) +
  `provision/` (`scaffold.py` `run_devops_scaffold` + `gates.py` `run_devops_gate`). After a full
  `--auto-execute` batch, `--scaffold-deploy` runs `run_devops_scaffold` once (post-batch terminal phase)
  to generate + merge the app's CI/CD config; self-heals up to `DEVOPS_MAX_RETRIES` times via lint feedback.
  Reuses nexus's transaction/forge/FinOps SSOTs via a **lazy import** — the single `deployment → nexus` edge.
- **Shared plane** (`src/shared/`) — the engine SSOTs all planes import: `core/` (`models.py`,
  `config.py` incl. `ROLE_MODELS`/`AGENT_PLANE`, `observability.py`, `runs.py`, `docker_adapter.py`,
  `environments.py`, `prompts.py`) and `utils/` (`llm.py`, `api_retry.py`, `git_helpers.py`,
  `subprocess_helpers.py`, `redaction.py`, `forge.py`). All LLM traffic flows through here.
- **Prompt store** — per-role system prompts (`prompts/system/*.md`) + frontmatter-gated skill fragments
  (`prompts/skills/*.md`) assembled per node by `build_agent_context`.
- **Sandbox images** — pre-built per-language Docker images: `python-3.12-core`, `go-1.23-cli`,
  `node-22-web`, `dotnet-10-sdk`; each has a dedicated cache volume (pip / go mod / npm / nuget).
- **Run store** — the filesystem is the durable state. Layout SSOT: `src/shared/core/runs.py`.
  Per-ticket reports: `checkpoint.json` (FSM state), `finops_report.json`, `incident_report.json` (on halt).
  Batch-level: `batch_state.json` (`BatchState` with `completed`, `app_telemetry`, `budget_marker`,
  `released_tag`) + `app_finops_report.json` (written in a `finally`, survives any halt).

> **Model routing** ([agent-provider-model-map](../.claude/rules/agent-provider-model-map.md)):
> structured roles use **Gemini** (`ROLE_MODELS` in `config.py`); **Developer** and **QA** run as **Claude
> CLI** agentic sessions. Gemini cost is *estimated* (`MODEL_PRICING_MATRIX`), Claude cost is
> *authoritative* (CLI-reported). Neither tokens nor infra time is a ceiling — **USD only** gates the breaker.

---

## Level 3 — Executor FSM (the self-healing loop)

One ticket's execution cycle. TechLead derives the contract **once**; the outer loop self-heals across
cycles via two isolated feedback channels (Developer / QA) plus the **Arbiter**'s third route (amend the
contract). Free fast-fail reroutes (QA signature-lint, Developer guardrails, QA test-compile gate, lint
gate) bypass the Reviewer without spending the functional retry budget. Faithful to
[pipeline-fsm-loops](../.claude/rules/pipeline-fsm-loops.md).

```mermaid
flowchart TB
    boot["bootstrap_session<br/><i>shallow-clone · feat/ticket-&lt;id&gt; branch<br/>load or init checkpoint</i>"]
    tl["run_techlead_node<br/><i>derive TechLeadContract (once)<br/>pin working_directory from Component tag · 💰</i>"]
    boot --> tl

    subgraph cyc["Outer cycle — while attempt ≤ ceiling  (💰 breaker checked at ★)"]
        direction TB

        qa["QA: run_qa_agent_node<br/><i>generate tests (Claude CLI · QA_MODEL/QA_EFFORT)<br/>▸ free reroute loop ≤ QA_LINT_MAX_REROUTES<br/>  contract-signature lint contradictions</i>"]

        dev["Developer: run_developer_node ★<br/><i>implement production code (Claude CLI)<br/>▸ free reroute loop ≤ GUARDRAIL_MAX_REROUTES each<br/>  missing contracted files · doc guardrail · compile gate<br/>  env failure → Hard Halt · test-only compile → QA</i>"]

        tc["QA test-compile gate<br/><i>run_test_compile_gate<br/>▸ free reroute loop ≤ QA_GATE_MAX_REROUTES<br/>  test-only compile failures → QA regen<br/>  env/prod-ref failures → Reviewer unchanged</i>"]

        fmt["run_format_pass<br/><i>auto-fix style issues (best-effort, non-fatal)</i>"]

        lint["HARD lint gate: run_lint_gate ★<br/><i>run_lint_gate + classify_lint_findings<br/>▸ free reroute loop ≤ LINT_GATE_MAX_REROUTES<br/>  prod findings → Developer channel<br/>  test findings → QA channel<br/>  tooling error (bad flag/missing binary) → Hard Halt</i>"]

        gates["Docker gates (--network none)<br/><i>run_qa_unit_tests · run_security_scan<br/>(parallel: unit-tests + SAST if PIPELINE_SAST_ENABLED)</i>"]

        rev["run_reviewer_node ★<br/><i>code + test verdict<br/>dev_diagnostic_payload + dev_evidence_citation<br/>qa_diagnostic_payload · _require_routing_coherence</i>"]

        decide{"all_gates_passed?"}

        qa --> dev --> tc --> fmt --> lint --> gates --> rev --> decide
    end

    tl --> qa

    decide -->|"yes"| tw["run_techwriter_node<br/><i>update living ADR in clone (final ticket only)</i>"]
    tw --> commit["finalize_transaction<br/><i>atomic commit (+ optional push)</i>"]
    commit --> automerge{"--auto-merge?"}
    automerge -->|"yes"| pr["finalize_pr<br/><i>open PR → approve (reviewer token)<br/>→ squash-merge into base_branch</i>"]
    automerge -->|"no"| done
    pr --> done(["✅ SUCCESS"])

    decide -->|"no"| dlg{"deadlock guard<br/>gate failed AND<br/>both sides approved?"}
    dlg -->|"yes"| halt1(["🛑 incident:<br/>env/runner misconfig"])
    dlg -->|"no"| arb_q{"attempt ≥<br/>ARBITER_TRIGGER_ATTEMPT?"}

    arb_q -->|"no — early cycle"| route["reconcile_feedback_routing<br/><i>→ Developer / QA channel(s)<br/>coherence floor + Arbiter authority (ADR 0024)</i>"]
    arb_q -->|"yes"| arb["run_arbiter_node ★<br/><i>triage root cause</i>"]

    arb -->|"developer / qa<br/>(authoritative override)"| route
    arb -->|"contract<br/>(≤ MAX_CONTRACT_AMENDMENTS)"| amend["run_techlead_node — amend contract<br/><i>env_id pinned · working_directory pinned<br/>+AMENDMENT_RETRY_BONUS cycles · QA regen</i>"]
    arb -->|"halt / cap reached"| halt2(["🛑 incident:<br/>unrecoverable spec conflict"])

    route --> nxt["next cycle<br/><i>re-apply stashed lint findings<br/>append raw QA output if regenerating</i>"]
    amend --> nxt
    nxt -->|"budget left"| qa
    nxt -->|"retries exhausted"| brk(["🛑 CIRCUIT BREAKER:<br/>retries exhausted"])

    classDef ok fill:#2d6a4f,stroke:#1b4332,color:#fff;
    classDef stop fill:#9d0208,stroke:#6a040f,color:#fff;
    classDef dec fill:#e9c46a,stroke:#b08900,color:#000;
    class done ok;
    class halt1,halt2,brk stop;
    class decide,dlg,arb_q,automerge dec;
```

**Key:**
- **Contract once, loop many:** `run_techlead_node` runs before the loop (and only again on Arbiter
  `contract` verdict). The contract is the single source of truth; cycle 1 generates tests *before* the
  Developer (contract-first TDD).
- **Free fast-fail reroutes (no retry budget consumed):**
  - *QA lint* (`≤ QA_LINT_MAX_REROUTES`): contract-signature contradictions reroute to QA only.
  - *Developer guardrails* (`≤ GUARDRAIL_MAX_REROUTES` each): missing contracted files, doc guardrail
    (undocumented new files), compile gate — each is its own free-reroute budget. Environmental failures
    (network/restore) trigger Hard Halt. Test-only compile failures route to QA, not Developer.
  - *QA test-compile gate* (`≤ QA_GATE_MAX_REROUTES`): test-only compile failures reroute to QA for
    regeneration; env/production-referencing failures pass to the Reviewer unchanged.
  - *Lint gate* (`≤ LINT_GATE_MAX_REROUTES`): `classify_lint_findings` routes production findings to the
    Developer channel and test findings to the QA channel; residual findings after the free budget are
    stashed and re-applied after Reviewer routing in the next cycle. Tooling errors (bad flag / missing
    binary) trigger Hard Halt as an environment incident. The per-env `lint_cmd` is the SSOT the
    `--scaffold-deploy` CI runs verbatim — engine-green ⇒ CI-green (ADR 0020).
  - *Format pass* (`run_format_pass`): best-effort auto-fix before the HARD lint gate; non-fatal.
- **Two isolated channels — routing-coherence enforced (ADR [0024](decisions/0024-routing-coherence-reconciler.md)):**
  `reconcile_feedback_routing` assigns `dev_diagnostic_payload` → Developer and `qa_diagnostic_payload` →
  QA; the `ReviewReport` biconditional validator `_require_routing_coherence` forbids a payload on an
  approved side; a production rejection must carry a verbatim `dev_evidence_citation`. The Arbiter's
  `developer`/`qa` verdict is **authoritative** and overrides a Reviewer misroute.
- **Parallel validation:** `run_qa_unit_tests` and `run_security_scan` (Semgrep SAST, if
  `PIPELINE_SAST_ENABLED`) run concurrently inside Docker (`--network none`); timed as a single
  `qa+sast` phase for wall-clock accuracy.
- **Arbiter (ADR [0016](decisions/0016-arbiter-contract-self-healing.md)):** on a stuck cycle (`attempt ≥
  ARBITER_TRIGGER_ATTEMPT`) it adds a third route — amend the **contract** — for failures no worker can
  fix. Bounded: `environment_id` pinned, `MAX_CONTRACT_AMENDMENTS` cap, a `AMENDMENT_RETRY_BONUS` per
  amendment. Its `developer`/`qa` routes are authoritative (ADR 0024).
- **Terminals:** SUCCESS (commit + optional PR merge), deadlock-guard incident, Arbiter halt, or the
  Financial Circuit Breaker / "retries exhausted" hard-halt — each writes `reports/incident_report.json`.
- **Money-only breaker (E5, ADR [0022](decisions/0022-application-wide-finops-budget.md)):** 💰 checkpoints
  call `enforce_financial_circuit_breaker(ctx, budget_usd)` where `budget_usd` is the *remaining*
  application budget threaded in by `run_batch` (`app_budget − spent`); gates on **USD only** — tokens are
  reported, never a ceiling.

---

## End-to-end sequence

From a raw idea to committed code across the planes (control → worker, then the optional deploy-scaffold
and release tag).

```mermaid
sequenceDiagram
    actor H as Human
    participant N as Nexus (PO→SA→TPM)
    participant FS as Run Store
    participant X as Execution FSM
    participant G as Gemini API
    participant C as Claude CLI (Dev+QA)
    participant D as Docker
    participant R as Git / GitHub

    H->>N: main.py --idea "<idea>" [--auto-execute] [--budget <usd>]
    N->>G: PO structured call (Epic)
    N->>G: SA structured call (Blueprint)
    N->>G: TPM structured call (TASK-*.md ordered backlog)
    N->>FS: artifacts/{epic,blueprint,TASK-*.md} + NexusState checkpoint
    N-->>H: planned tickets (Nexus FinOps summary)

    Note over H,X: --run [project] -f TASK-01 OR --auto-execute drives ALL tickets via run_batch E3 under ONE money budget

    loop each planned ticket → main, in TPM order (--auto-execute)
        X->>X: remaining = app_budget − app_telemetry.spent<br/>stop cleanly if remaining ≤ floor
        H->>X: execute ticket (budget_usd_ceiling = remaining)
        X->>R: shallow-clone latest main → feat/ticket-id
        X->>G: TechLead → TechLeadContract (💰 checked)
        X->>FS: checkpoint (contract)

        loop until gates pass, budget exhausted, or retries exhausted
            X->>C: QA → generate tests (free reroute: contract-signature lint)
            X->>C: Developer → implement code (💰 checked)<br/>(free reroutes: missing files · doc guardrail · compile gate)
            X->>C: QA test-compile gate (free reroute: test-only compile failures)
            X->>D: run_format_pass (auto-fix style, non-fatal)
            X->>D: run_lint_gate HARD (💰 checked)<br/>(free reroutes: prod→Dev · test→QA)
            X->>D: run_qa_unit_tests + run_security_scan (parallel, --network none)
            X->>G: Reviewer → ReviewReport (verdict + diagnostics) (💰 checked)
            alt all gates passed
                X->>X: exit inner loop → success path
            else gate failed + deadlock (both approved)
                X->>FS: incident_report.json (env/runner misconfig)
            else gate failed + attempt ≥ ARBITER_TRIGGER_ATTEMPT
                X->>G: Arbiter → triage (developer/qa/contract/halt) (💰 checked)
                opt contract verdict (≤ MAX_CONTRACT_AMENDMENTS)
                    X->>G: TechLead amend contract (env_id pinned · +retry bonus)
                end
                X->>X: reconcile_feedback_routing → next cycle
            else gate failed + early cycle
                X->>X: reconcile_feedback_routing → next cycle
            end
        end

        X->>G: TechWriter → update living ADR (final ticket)
        X->>R: finalize_transaction (atomic commit + optional push)
        opt --auto-merge (implied by --auto-execute)
            X->>R: open PR → approve (reviewer token) → squash-merge into base_branch
        end
        X->>FS: batch_state.json (completed += ticket · app_telemetry += spend)<br/>finops_report.json (per-ticket)
    end

    opt --scaffold-deploy (once, after full batch — E4 / ADR 0020)
        X->>R: shallow-clone main → chore/devops-scaffold
        X->>G: DevOps → DevOpsManifests (archetype-aware Dockerfile + workflow)
        loop ≤ DEVOPS_MAX_RETRIES self-heal
            X->>D: run_devops_gate (static-lint manifests)
            alt lint clean
                X->>X: proceed to merge
            else lint findings
                X->>G: DevOps regenerate with gate_feedback
            end
        end
        X->>R: open PR → approve → squash-merge deploy config into main
    end

    opt --release (final step — E6 / ADR 0023)
        X->>R: shallow-clone main → chore/release-tag<br/>list_remote_tags → compute_next_tag (repo-derived v* bump)
        X->>R: push_tag v* (annotated → trips tag-gated release workflow)
        X->>FS: batch_state.released_tag (idempotent resume guard)
    end

    X-->>H: ✅ all tickets merged (+ deploy config + v* tag)<br/>app FinOps: per-role · per-plane · per-provider · per-phase
```

---

## FinOps & the application budget (E5)

A single **money** ceiling governs a whole `--idea --auto-execute` build (ADR
[0022](decisions/0022-application-wide-finops-budget.md)) — `PIPELINE_APP_BUDGET_USD` (default `$25`,
env-overridable) or the per-invocation `--budget <usd>` flag. The Financial Circuit Breaker is **money-only**:
tokens are measured and reported (`total_tokens`, `total_cache_read_tokens`, `total_cache_write_tokens`),
but never a ceiling (the agentic Claude CLI re-sends its prompt each turn, so cache-heavy token counts are
a poor gate — USD, authoritative for Claude and estimated for Gemini, is the honest signal).

```mermaid
flowchart LR
    subgraph batch["run_batch — one app budget across N tickets"]
        direction TB
        rem["remaining = app_budget − app_telemetry.total_cost_usd"]
        gate{"remaining ≤<br/>PIPELINE_APP_BUDGET_FLOOR_USD?"}
        tick["run_executor(budget_usd_ceiling = remaining)<br/>💰 breaker gates on USD only<br/>record_phase() tracks infra wall-clock"]
        merge["app_telemetry.merge(ticket_telemetry)"]
        rem --> gate
        gate -->|"no"| tick --> merge --> rem
        gate -->|"yes"| stop(["🛑 clean stop: budget_marker<br/>(resume with --budget &lt;larger&gt; to continue)"])
    end
    merge -.->|"every batch exit (finally)"| rep[["app_finops_report.json<br/>by_agent · by_plane · by_provider · by_phase"]]
    stop -.-> rep

    classDef stop fill:#9d0208,stroke:#6a040f,color:#fff;
    classDef dec fill:#e9c46a,stroke:#b08900,color:#000;
    classDef store fill:#2d6a4f,stroke:#1b4332,color:#fff;
    class stop stop;
    class gate dec;
    class rep store;
```

**Key:**
- **One ceiling, threaded remaining.** `run_batch` keeps the running spend in `BatchState.app_telemetry`
  (Nexus planning + every ticket + DevOps, via `PipelineTelemetry.merge`) and threads `remaining` into each
  ticket's breaker. Below `PIPELINE_APP_BUDGET_FLOOR_USD` it stops cleanly **before** spending more.
- **Resume-safe + re-budgetable.** `app_telemetry` persists; the ceiling is **never** persisted (re-resolved
  per invocation), so `--resume … --budget <larger>` adds money and continues past a `budget_marker`.
- **Four-dimensional reporting.** Each agent call records `cost / tokens (in/out/cache, cache excluded from
  the budgeted total) / duration / plane`; each Docker/git/forge phase records wall-clock via `record_phase`.
  `finops_report` rolls up `by_agent`, `by_plane` (nexus/development/deployment), `by_provider`
  (gemini/claude), and `by_phase` (infra phases). The per-run `reports/finops_report.json` and the
  batch-level `reports/app_finops_report.json` carry the full breakdown; `log_finops_summary` prints the
  GRAND TOTAL with per-plane subtotals + total wall-clock.

---

## Component reference

The Level-3 components in text (file → responsibility). See [repo-module-map](../.claude/rules/repo-module-map.md)
for the full module map and [agent-contracts](../.claude/rules/agent-contracts.md) for each agent's I/O model.

| Plane | Component | File | Responsibility |
|---|---|---|---|
| Entry | CLI / router | `main.py` → `src/nexus/runner.py` `main()` | Parse args (`--idea / --run / --resume / --auto-execute / --auto-merge / --push / --scaffold-deploy / --release / --budget / --reset-attempts`); route to planning vs. ticket execution; `--resume` dispatch (incl. batch re-entry); on `--idea --auto-execute`, drive ALL tickets to `main` via `run_batch` (`prepare_ticket_run` + `run_executor` per ticket, `get_tasks_for_nexus_run` for order, `BatchState` checkpoint). |
| Nexus | PO / SA / TPM | `src/nexus/agents/{po,sa,tpm}.py` | Idea → Epic → Blueprint → task tickets (structured Gemini, `gemini-2.5-pro`). |
| Nexus | Runner / State | `src/nexus/nexus_runner.py`, `state.py` | Drive PO→SA→TPM; `NexusState` checkpoint + resume. |
| Nexus | FSM driver | `src/nexus/runner.py` | `main()` dispatch/resume; per-ticket FSM (`run_executor`) — bootstrap, TechLead, outer cycle (QA → Developer → test-compile gate → format → lint → parallel test+SAST → Reviewer → routing/Arbiter/amend), reroutes, breaker, `reconcile_feedback_routing` (coherence floor + Arbiter authority, ADR 0024), commit; E3 batch loop (`run_batch`). |
| Nexus | Release-tag | `src/nexus/runner.py` `finalize_release` + `compute_next_tag` | Post-batch terminal phase (`--release`, E6): clone `main` → `list_remote_tags` → `compute_next_tag` (repo-derived `v*` bump by `RELEASE_VERSION_BUMP`, `v0.1.0` greenfield) → push annotated tag via forge seam; idempotent via `BatchState.released_tag`. |
| Development | TechLead | `src/development/agents/techlead.py` | Derive (and, in amendment mode, re-derive) the `TechLeadContract`; pins `working_directory` from `## Component` tag (deterministic monorepo override). |
| Development | Developer | `src/development/agents/developer.py` | Implement production code in the clone (Claude CLI, agentic; bounded by `DEVELOPER_CLI_TIMEOUT`/`DEVELOPER_CLI_IDLE_TIMEOUT`). |
| Development | QA | `src/development/agents/qa.py` | Generate per-module tests via Claude CLI (`QA_MODEL`/`QA_EFFORT`; bounded by `QA_CLI_TIMEOUT`/`QA_CLI_IDLE_TIMEOUT`); `_sandbox_root()` roots test placement for monorepo tickets. |
| Development | Reviewer | `src/development/agents/reviewer.py` | Code + test verdict; isolated dev/QA diagnostics + `dev_evidence_citation` (verbatim proof for a production rejection); coherence-validated by `_require_routing_coherence` (ADR 0024). |
| Development | Arbiter | `src/development/agents/arbiter.py` | Triage stuck cycle (`attempt ≥ ARBITER_TRIGGER_ATTEMPT`) → developer / qa / contract / halt; authoritative channel override (ADR 0024). |
| Development | TechWriter | `src/development/agents/techwriter.py` | Maintain the living ADR (`docs/architecture_state.md` in the clone); runs on success path before commit. |
| Development | Gates | `src/development/gates.py` | `run_format_pass` (auto-fix, non-fatal) · `run_lint_gate` + `classify_lint_findings` (HARD gate, SSOT for CI) · `run_test_compile_gate` · `run_qa_unit_tests` · `run_security_scan` (Semgrep SAST) — all via `docker_adapter`. |
| Deployment | DevOps | `src/deployment/agents/devops.py` | Generate `DevOpsManifests` (archetype-aware Dockerfile + GitHub Actions deploy workflow, WIF) for the finished app (`--scaffold-deploy`, E4). Models: `gemini-2.5-flash`. |
| Deployment | Deploy-scaffold | `src/deployment/provision/scaffold.py` `run_devops_scaffold` | Post-batch terminal phase (E4): clone `main` → DevOps node → `run_devops_gate` (self-heal loop ≤ `DEVOPS_MAX_RETRIES`) → merge `chore/devops-scaffold` via the forge flow. |
| Deployment | Deploy gate | `src/deployment/provision/gates.py` `run_devops_gate` | Static-lint the manifests (YAML + Dockerfile directives); for a `requires_public_invoker` target assert public invocation (no HTTP 403) + a repo-derived service name (no overwrite) — ADR 0026. |
| Shared | Models | `src/shared/core/models.py` | `GlobalPipelineContext`, `TechLeadContract`, `ReviewReport`, `ArbiterVerdict`, `BatchState` (E3 checkpoint + E5 `app_telemetry`/`budget_marker`/`nexus_merged` + E6 `released_tag`), `DevOpsManifests` (E4 deploy config), `PipelineTelemetry` (per-agent tokens/cost/duration/**plane**/provider + `record_phase` for infra · `by_plane()`/`by_provider()`/`merge()`/`finops_report()`). |
| Shared | Config | `src/shared/core/config.py` | `ROLE_MODELS` (Developer + QA absent — Claude CLI), `AGENT_PLANE` (label→plane), app-wide money budget (`PIPELINE_APP_BUDGET_USD` + floor), `RELEASE_VERSION_BUMP` (E6 tag bump), `PIPELINE_REVIEWER_STRICT` / `PIPELINE_SAST_ENABLED` toggles, FSM constants (`MAX_FUNCTIONAL_RETRIES`, `ARBITER_TRIGGER_ATTEMPT`, `MAX_CONTRACT_AMENDMENTS`, `AMENDMENT_RETRY_BONUS`, reroute budgets), timeouts, pricing. |
| Shared | Observability | `src/shared/core/observability.py` | Logging, per-role/**plane**/provider/time FinOps telemetry (`log_token_usage` reads per-call time from the `run_structured_llm` ContextVar), money-only `log_finops_summary`, finish-reason diagnostics. |
| Shared | Run layout | `src/shared/core/runs.py` | `Projects` store + `allocate_run_dir` (run-layout SSOT: `NNN_<plane>_<label>_<ts>_<uid6>/`). |
| Shared | Docker adapter | `src/shared/core/docker_adapter.py` | Least-privilege `run_in_image` / `execute_in_sandbox`; cache-volume management. |
| Shared | Environments | `src/shared/core/environments.py` | `SUPPORTED_ENVIRONMENTS`: `python-3.12-core` · `go-1.23-cli` · `node-22-web` · `dotnet-10-sdk` — each with `image` / `setup_cmd` / `build_cmd` / `test_cmd` / `lint_cmd` / `format_cmd` / `test_compile_cmd` / `dependency_manifest` / `authoring_contract` / `language_id`; `lint_cmd` is the SSOT shared with the generated CI; `resolve_environment(env_id, env_overlays)` merges skill-declared command overrides. `SUPPORTED_DEPLOY_TARGETS`: `gcp-cloud-run` (rest_api/crud_app · public invoker) · `github-release` (cli_tool) · `gcp-cloud-run-monorepo` (fullstack_monorepo · both services public) — `archetypes`/`skill`/`runtime_constraints`/`requires_public_invoker` (ADR 0026). |
| Shared | Prompts | `src/shared/core/prompts.py` | `get_system_prompt*`, `build_agent_context` (skill routing). |
| Shared | LLM / retry | `src/shared/utils/{llm,api_retry}.py` | `run_structured_llm` (relocates Jinja-marker system messages to a user turn for GenAI); backoff + non-retryable/RECITATION handling. |
| Shared | PR forge | `src/shared/utils/forge.py` | Provider-agnostic `open_pr`/`approve_pr`/`merge_pr` (`gh`-backed, `--auto-merge` loop closure) + `list_remote_tags`/`push_tag` (E6 `--release` annotated-tag push, boundary-safe `_run_git`). |

---

*Diagrams reflect the engine as of [CHANGELOG](../CHANGELOG.md) current HEAD — Developer + QA both on Claude CLI, 4-environment registry (`python-3.12-core` · `go-1.23-cli` · `node-22-web` · `dotnet-10-sdk`), 3-target deploy registry (`gcp-cloud-run` · `github-release` · `gcp-cloud-run-monorepo`), format pass before HARD lint gate, parallel unit-test + SAST validation, four-dimensional FinOps (`by_agent`/`by_plane`/`by_provider`/`by_phase`), over the fullstack monorepo support + arbiter production-code oracle of v0.26.0 (ADR [0027](decisions/0027-installable-cli-and-factory-self-release.md)), the deployment-target registry + reachability gates of v0.25.0 (ADR [0026](decisions/0026-deploy-target-registry-and-reachability-gates.md)), and the routing-coherence hardening of v0.24.0 (ADR [0024](decisions/0024-routing-coherence-reconciler.md)). For the "why" behind each decision see [decisions/](decisions/README.md); for what's still open see [BACKLOG.md](BACKLOG.md).*
