# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Each release maps to a completed SDLC iteration; the corresponding Architecture
Decision Record (ADR) is linked from the version heading.

## [v0.20.0] - 2026-06-23 — Deployability Closure: DevOps Deploy-Scaffolding (E4) + the Engine Lint Gate

ADR: [0020-deploy-scaffolding-and-lint-gate](./docs/decisions/0020-deploy-scaffolding-and-lint-gate.md)
(extends [0011](./docs/decisions/0011-secure-sandbox-and-finops-telemetry.md),
[0012](./docs/decisions/0012-virtual-separation-monorepo-planes.md),
[0018](./docs/decisions/0018-auto-merge-pr-loop-closure.md),
[0019](./docs/decisions/0019-cyclical-multi-ticket-orchestration.md))

Archive: [iteration_20](./docs/releases/iteration_20/iteration_20_README.md)

### Added
- **`--scaffold-deploy` makes the finished app deployable (E4).** A new **`devops` agent**
  (`src/executor/agents/devops.py`, `prompts/system/devops.md` + three archetype skills
  `prompts/skills/devops_{rest_api,crud_app,cli_tool}.md`) classifies the merged application and emits
  structured `DevOpsManifests` (`src/shared/core/models.py`): a multi-stage non-root `Dockerfile` + a Cloud
  Run deploy workflow for a **web service**, or **no Dockerfile + a build/release matrix** for a
  **CLI/library**. Auth is **Workload Identity Federation** (org secrets `GCP_WIF_PROVIDER`/
  `GCP_SERVICE_ACCOUNT` + variables `GCP_PROJECT_ID`/`GCP_REGION`/`GCP_REGISTRY_NAME`; see
  `docs/guides/devops_setup.md`) — never embedded keys.
- **`run_devops_scaffold` — a post-batch terminal phase** (`src/executor/runner.py`): runs once after
  `run_batch` merges every ticket, clones the base branch fresh onto **`chore/devops-scaffold`**, generates →
  **statically lints** the manifests (`run_devops_gate`) → self-heals `DEVOPS_MAX_RETRIES` (default 1) times →
  lands them through the **same E2 forge flow** (open → approve → squash-merge), never a raw push. An
  empty-state guard skips a sourceless clone.
- **HARD engine lint gate (`run_lint_gate`, FSM step 3.6).** A per-environment `lint_cmd`
  (`src/shared/core/environments.py`) is now verified inside the cycle: a residual finding fast-fail-reroutes
  **production → Developer, test → QA** (`classify_lint_findings`, no functional budget), bounded by
  `LINT_GATE_MAX_REROUTES` (env `PIPELINE_LINT_MAX_REROUTES`, default 2) with a no-progress break;
  `lint_success` folds into `all_gates_passed`. `lint_cmd` is the **SSOT the DevOps-generated CI runs
  verbatim**, so **engine-green ⇒ CI-green** — closing the gap where a generated `ruff check` reddened on a
  finding every engine gate had tolerated.

### Changed
- **`format_cmd` now auto-applies what the lint gate verifies** (python gains `ruff format`), so only
  genuinely-unfixable findings (e.g. `F841`) reach an agent.
- **`run_structured_llm` relocates Jinja-marker system messages to a user turn** (`src/shared/utils/llm.py`,
  `_relocate_jinja_system_messages`) — a fast-path no-op for every marker-free role; fixes the deterministic
  `instructor`/Google-GenAI `ValueError` crash on the DevOps prompt's `${{ secrets.* }}` expressions.
- **Docs & meta-rules synced** — `docs/ARCHITECTURE.md` (the `devops` role + the deploy-scaffolding terminal
  phase + the step-3.6 lint gate); `.claude/rules/{repo-module-map,pipeline-fsm-loops,run-layout-and-cli,config-constant-convention,agent-provider-model-map}.md`
  and the `analyze-run` skill (lint-gate / CI-strictness and GenAI-Jinja root-cause classes); `docs/BACKLOG.md`
  (E4 → DONE; mypy/type-checking + node-eslint provisioning tracked as follow-ups).

## [v0.19.0] - 2026-06-22 — Cyclical Multi-Ticket Orchestration: Drive Every Ticket to `main` (`--auto-execute`, E3)

ADR: [0019-cyclical-multi-ticket-orchestration](./docs/decisions/0019-cyclical-multi-ticket-orchestration.md)
(extends [0012](./docs/decisions/0012-virtual-separation-monorepo-planes.md),
[0017](./docs/decisions/0017-nexus-executor-auto-dispatch.md),
[0018](./docs/decisions/0018-auto-merge-pr-loop-closure.md))

Archive: [iteration_19](./docs/releases/iteration_19/iteration_19_README.md)

### Added
- **`--auto-execute` drives ALL planned tickets to `main` (E3).** Extended from the E1 first-ticket-only
  dispatch: after planning, the engine now runs the Executor over **every** ticket in TPM order —
  `TASK-01 → merge → TASK-02 → …` — so the full application lands on `main` from a single `--idea`
  invocation. Each ticket clones `main` fresh, so `--auto-execute` now **implies `--auto-merge`** (hence
  `--push`): a batch is only coherent if each ticket merges before the next clones it.
- **`run_batch` — the batch loop** in `main()` (the entry/worker layer; Nexus still never imports the
  executor, ADR 0012). Drives the tickets in order, skipping any already merged, and applies an explicit
  **failure policy**: stop the batch on the first unrecoverable halt, write the per-ticket incident, and
  exit 1.
- **`BatchState` — a resumable batch checkpoint** (`src/shared/core/models.py`, `kind="batch"`):
  `{project_slug, nexus_run, tickets, completed, failed}`, persisted as `reports/batch_state.json` beside
  the Nexus planning checkpoint. A bare `--resume <project>` with this sidecar **re-enters the batch**,
  skipping merged tickets and re-running the failed one fresh against the now-updated `main`.

### Changed
- **`PipelineHalt` replaces the abort `sys.exit(1)`.** `_abort_with_incident` now *raises* a catchable
  `PipelineHalt` (after writing the incident + FinOps) instead of exiting the process; `main.py` converts an
  uncaught one to exit 1, so single-ticket paths behave exactly as before, while the batch loop catches it
  to record state and stop cleanly. Six FSM-halt unit tests were updated from `assertRaises(SystemExit)` to
  `assertRaises(PipelineHalt)` to match the new contract.
- **Docs & meta-rules synced** — `docs/ARCHITECTURE.md` (batch loop in the sequence; `batch_state.json` in
  the run layout); `.claude/rules/{run-layout-and-cli,pipeline-fsm-loops,repo-module-map}.md` (the new
  `--auto-execute` batch semantics + resume, `PipelineHalt`, `run_batch`/`BatchState`); `docs/BACKLOG.md`
  (E3 → DONE; new epic **E5** application-wide FinOps budget).

## [v0.18.0] - 2026-06-22 — Close the Loop to `main` via an Auto-Merged PR (`--auto-merge`, E2)

ADR: [0018-auto-merge-pr-loop-closure](./docs/decisions/0018-auto-merge-pr-loop-closure.md)
(extends [0008](./docs/decisions/0008-git-anchored-sessions-atomic-commit.md),
[0012](./docs/decisions/0012-virtual-separation-monorepo-planes.md),
[0017](./docs/decisions/0017-nexus-executor-auto-dispatch.md))

Archive: [iteration_18](./docs/releases/iteration_18/iteration_18_README.md)

### Added
- **`--auto-merge` — close the autonomy loop to `main` (E2).** On PIPELINE SUCCESS the engine now opens a PR
  from `feat/ticket-<id>` into `base_branch`, optionally approves it, and **squash-merges** it — so verified,
  gate-passing work actually lands in `main` with no human hand-off. `RunConfig.auto_merge` carries the flag
  and **implies `--push`**; `finalize_pr` runs after `finalize_transaction`, wrapped so the FinOps summary
  prints even on a merge failure. The bridge stays in the entry/worker layer — the control plane never
  learns about PRs (ADR 0012).
- **Provider-agnostic forge seam — `src/shared/utils/forge.py`** (`open_pr` / `approve_pr` / `merge_pr`),
  GitHub-first via the `gh` CLI. Subprocess-first (mirrors `git_helpers.py` + the `_run_checked` auth idiom):
  prompts disabled, a per-call wall-clock ceiling (`GH_NETWORK_TIMEOUT`), `GITHUB_TOKEN` from the env, and
  `gh` inferring owner/repo from the clone's `origin` remote. `open_pr` is **idempotent** (reuse an OPEN PR
  into the same base, skip a MERGED one) so `--resume` after a partial merge is safe.
- **Identity model + protected-repo path.** `merge_pr` does `--squash --admin --delete-branch` (closes the
  loop on unprotected repos); `approve_pr` is best-effort via a **separate `GITHUB_REVIEWER_TOKEN`** (GitHub
  forbids self-approval) and swallows any `gh` failure. An `--admin` merge blocked by pending required checks
  falls back to `gh pr merge --auto`; `GITHUB_MERGE_STRATEGY=auto` forces the queued path up front.

### Changed
- **`check_environment(require_forge=…)`** — with `--auto-merge`, the preflight now also requires `gh` on
  PATH and a non-empty `GITHUB_TOKEN`, aborting before any tokens are spent.
- **Setup guide + meta-rules synced** — `docs/guides/setup.md` gains a `gh` install/auth section, the new env
  knobs, a pre-flight `gh` check, and troubleshooting rows; `docs/ARCHITECTURE.md` C4 + sequence + component
  table now include the PR/merge step and `forge.py`; `.claude/rules/*` record `forge.py`, the knobs, and
  `--auto-merge`.
- **Governance tooling — auto-sync of Claude's operating context.** New `/claude-context-sync` skill
  reconciles the *content* of `.claude/rules/*` + `.claude/skills/*` to the code (the complement to
  `/docs-sync`'s human-doc + enumeration sync), now wired as a step in `/iteration-release` so rules/skills
  stay current with each release. New `/agent-role-scaffold` skill operationalizes the `agent-role-registration`
  checklist for adding a structured agent. New rule `subprocess-and-external-call-safety` binds future engine
  edits to `sanitize_for_argv` + transport-layer timeouts (codifying the two fixes below).

### Fixed
- **Subprocess crash on a NUL byte in agent-authored text.** A corrupted glyph (`©` → `\x00`) in a Nexus
  ticket flowed into the PR body and crashed `gh pr create` (`ValueError: embedded null byte`, POSIX `execvp`
  rejects a NUL in argv). New SSOT `sanitize_for_argv` (`src/shared/utils/subprocess_helpers.py`, strips C0
  controls + DEL, keeps `\t`/`\n`/`\r`) is applied at **both** subprocess boundaries — `forge._run_gh` and
  `runner._run_checked` (the commit path had the same latent exposure).
- **Indefinite hang on a stalled Gemini call.** A structured Gemini request could hang the executor forever
  (`run_in_executor` had no timeout, `with_api_retry` only fires on exceptions, the client had no ceiling).
  The shared genai client is now built with a per-request timeout (`GEMINI_REQUEST_TIMEOUT`, 300 s,
  env-overridable) via `http_options`, so a stall raises → retries → fails fast. Covers every structured
  role (PO/SA/TPM/TechLead/QA/Reviewer/TechWriter/Arbiter).

## [v0.17.0] - 2026-06-22 — Nexus → Executor Auto-Dispatch (`--auto-execute`)

ADR: [0017-nexus-executor-auto-dispatch](./docs/decisions/0017-nexus-executor-auto-dispatch.md)
(extends [0012](./docs/decisions/0012-virtual-separation-monorepo-planes.md),
[0015](./docs/decisions/0015-unified-project-run-topology.md))

Archive: [iteration_17](./docs/releases/iteration_17/iteration_17_README.md)

### Added
- **`--auto-execute` — one-command plan→execute (E1).** With `--idea` (and a `--repo` clone target), the
  engine now dispatches the Executor for the **first** planned ticket in the same invocation instead of
  stopping after planning and requiring a separate `--run <project> -f TASK-01`. `RunConfig.auto_execute`
  carries the flag; the dispatch lives in `main()` (entry layer) — **Nexus never imports the executor
  plane** (ADR 0012). Only the first ticket runs (multi-ticket is E2; non-exiting halts are E3).
- **`get_tasks_for_nexus_run(run_dir)`** (`src/nexus/nexus_runner.py`) — returns planned ticket ids in true
  TPM order: authoritative from the run's `checkpoint.json` (`NexusState.tasks`, list order preserved),
  fallback to a **natural-numeric** `artifacts/*.md` glob (`TASK-2` before `TASK-10`, not lexicographic).

### Changed
- **Per-ticket executor flow extracted into a reusable callable.** The ~350-line bootstrap→TechLead→FSM→
  finalize body was lifted **verbatim** out of `main()` into `run_executor(cfg, run_dir, resume_checkpoint)
  -> bool`, and the shared ticket setup into `prepare_ticket_run(...) -> Path | None`. The `--run` / legacy
  / resume paths now call them — behavior is byte-identical (the only logic change is `return` → `return
  True` on success). This is the foundation for E2/E3.
- **Fail-fast preflight for auto-execute** — `check_environment()` now runs **up front** (before planning)
  when `--auto-execute`, so a missing `docker`/`claude`/`bandit` aborts before planning tokens are spent.
- **Git-auth onboarding hardened (docs)** — `docs/guides/setup.md` + `.claude/rules/run-layout-and-cli.md`
  now document the **env-backed credential helper** (token in `GITHUB_TOKEN`, never on disk; pass a clean
  `--repo` URL), warning that a token embedded in the URL persists verbatim into `project.json` and the
  clone's `.git/config`. `README.md` directory tree re-synced to the actual repo topology.

### Fixed
- **`--idea` silently dropped `--push`.** The `--idea` branch built a `RunConfig` without forwarding
  `args.push`, so `--push` was a no-op on planning-initiated runs; it (and `--auto-execute`) are now
  forwarded, so an auto-executed first ticket pushes its `feat/ticket-<id>` branch as requested.

## [v0.16.1] - 2026-06-19 — Documentation, Licensing & Onboarding

Archive: [iteration_16.1](./docs/releases/iteration_16.1/iteration_16.1_README.md)

> No ADR — documentation, licensing, and meta-tooling maintenance only (no engine/runtime behavior change).

### Added
- **Apache-2.0 `LICENSE` for the engine repository** (+ a `## 📄 License` section in `README.md`). Chosen
  over MIT for the explicit patent grant and change-notice requirement that fit a code-generating tool.
  (Distinct from the **MIT** baseline the engine injects into *generated apps* via `boilerplate.py`, which
  is unchanged.)
- **`docs/ARCHITECTURE.md`** — C4 model in GitHub-native Mermaid: **L1** System Context, **L2** Containers
  (Nexus / Executor / Shared planes, prompt store, sandbox images, run store), **L3** Executor FSM, plus an
  end-to-end `sequenceDiagram` and a component-reference table. No C4-plugin syntax (GitHub won't render it).
- **Docs navigation index pages** — `docs/README.md` (front door) and `docs/decisions/README.md` (ADR index
  grouped by theme).
- **Rewritten onboarding guide `docs/guides/setup.md`** — a single zero-to-first-run spine: prerequisites
  table, ordered steps with per-step verifies, a **pre-flight self-check that mirrors `check_environment`**,
  a first-run walkthrough (plan → execute → resume + success/failure signals), an environment-variable
  reference table, and an expanded troubleshooting matrix.

### Changed
- **`docs/` restructured for navigability** (history-preserving `git mv`): `docs/adr/`→`docs/decisions/`,
  `docs/archive/`→`docs/releases/`, `docs/{setup,docker-on-windows}.md`→`docs/guides/`; every cross-link
  rewritten.
- **`/docs-sync` and `/iteration-release` skills extended** to also synchronize the `docs/ARCHITECTURE.md`
  C4 diagrams + component table when an iteration changes *structure* (a new/removed agent role, FSM route,
  external system, or plane/container).

### Removed
- **The stale root `Dockerfile`** — it `COPY`/`ENTRYPOINT`-ed the long-deleted `orchestrator.py` (broken
  since the ADR 0012 plane split) and was referenced by no build/compose/CI. Sandbox runtimes are built from
  `docker/*.Dockerfile` via `scripts/build_sandbox_images.sh`. The stale `python3 orchestrator.py` example in
  the setup guide was corrected to `main.py`.

## [v0.16.0] - 2026-06-19 — Arbiter: Autonomous Contract Self-Healing & Recitation Resilience

ADR: [0016-arbiter-contract-self-healing](./docs/decisions/0016-arbiter-contract-self-healing.md)
(extends [0001](./docs/decisions/0001-baseline-sequential-loop.md),
[0003](./docs/decisions/0003-dual-channel-observability.md),
[0006](./docs/decisions/0006-fsm-state-serialization-resume.md))

Archive: [iteration_16](./docs/releases/iteration_16/iteration_16_README.md)

### Added
- **Arbiter agent — autonomous contract self-healing (a third FSM route).** A new `arbiter` role
  (`ARBITER_MODEL` + `ROLE_MODELS`, `prompts/system/arbiter.md`, `src/executor/agents/arbiter.py`)
  returns a structured `ArbiterVerdict{root_cause_class, route, reasoning, contract_amendment_directive}`
  (`src/shared/core/models.py`). On a STUCK cycle (`attempt ≥ ARBITER_TRIGGER_ATTEMPT`, default 2) it
  triages the failure: `developer`/`qa` fall through to the existing isolated channels, `halt` aborts
  with an incident, and — the new capability — `contract` re-derives (AMENDS) the TechLead contract via
  `run_techlead_node(amendment_feedback=…)`. This closes the structural gap where a flawed contract was
  unfixable (the TechLead ran once, only Developer/QA channels looped → circuit breaker).
- **Engine-injected repository baseline files** (`src/shared/core/boilerplate.py`): the canonical MIT
  `LICENSE` (`MIT_LICENSE_TEMPLATE`) and per-environment `.gitignore` (reused from `environments.py`) are
  now assembled by `build_baseline_block(...)` and appended to `TASK-01` deterministically at ticket
  materialization (`src/nexus/nexus_runner.py`) — the engine writes them, not the LLM.
- **`finish_reason_name` + `NON_RETRYABLE_FINISH_REASONS`** (`src/shared/core/observability.py`): the bare
  classification primitive behind the retry layer's fail-fast decision; `describe_finish_reason` now
  builds its hint on top of it.
- **Run-diagnostics + scaffolding meta-tooling:** a `/analyze-run` Claude Code skill (evidence-first
  root-cause analysis of a failed/looping/halted run), a path-scoped `agent-role-registration` rule (the
  full checklist for adding a structured agent role), and `run-layout-and-cli` / `run-tests-via-wsl` rule
  extensions (non-interactive git auth for `--run`; Git-Bash↔WSL path translation).

### Changed
- **Gemini content-filter blocks are now non-retryable (fail-fast) with a RECITATION paraphrase retry.**
  `with_api_retry` (`src/shared/utils/api_retry.py`) short-circuits `RECITATION`/`SAFETY`/`BLOCKLIST`/
  `PROHIBITED_CONTENT`/`SPII` instead of burning the full 2^n backoff budget on a deterministic block.
  `run_structured_llm` (`src/shared/utils/llm.py`) additionally gives a RECITATION block ONE
  paraphrase-guarded retry (`RECITATION_GUARD` appended to the messages) — following the finish-reason
  hint ("rephrase / reduce verbatim quoting") instead of retrying the identical, identically-blocked
  prompt.
- **The TPM no longer reproduces canonical boilerplate** (the root recitation trigger). `prompts/system/tpm.md`
  stops emitting the full literal MIT `LICENSE` and the verbatim `.gitignore`; the prep block now references
  the engine-provided baseline files. `prompts/system/prompts.py` drops the `{injected_gitignore_templates}`
  injection (the templates are reused by `boilerplate.py` instead).
- **Functional retry budget hoisted to a constant + dynamic ceiling.** The bare `max_retries = 3` local in
  `runner.py` is now `MAX_FUNCTIONAL_RETRIES` (env `PIPELINE_MAX_RETRIES`); the outer cycle is a
  `while` loop over `MAX_FUNCTIONAL_RETRIES + contract_amendments * AMENDMENT_RETRY_BONUS`, so each
  autonomous amendment grants a bounded, resume-safe budget bonus. New env knobs: `ARBITER_TRIGGER_ATTEMPT`,
  `MAX_CONTRACT_AMENDMENTS` (default 1 — conservative), `ARBITER_AMENDMENT_RETRY_BONUS`.
- **Prompt hardening so the first contract is better and an amendment converges.** `techlead.md` gains an
  **ERROR PRECEDENCE** rule (overlapping `Raises` MUST declare precedence; never short-circuit before the
  parser surfaces a more specific error) + an **AMENDMENT MODE** section; `reviewer.md` gains
  **CONSTRAINT-RESPECTING REPAIR** (a fix that clears a gate by violating a stated NFR is invalid — name
  the contract conflict so it routes to an amendment); `prompts/skills/engineering_guide.md` adds the
  drain-the-incremental-parser idiom for error precedence under an O(1)/streaming constraint.

### Fixed
- **The Nexus TPM phase no longer dies on a Gemini RECITATION block.** The control-plane planning run for a
  Python "JSON→CSV CLI" idea halted at TPM after 3 identical RECITATION retries; the trigger is now removed
  at the source (engine-injected `LICENSE`/`.gitignore`) and any residual recitation self-heals via the
  single paraphrase retry instead of looping.
- **A flawed TechLead contract no longer loops the executor to the circuit breaker.** The `analyze_headers`
  ticket (streaming `ijson`) had a contract that mandated raising `MalformedStructureError` on the first
  parse event — but `{` / `{"a": 1` are both a non-array root AND invalid JSON, with no error precedence,
  so every cycle reproduced the same gate failure until "Retries exhausted." The Arbiter now routes such a
  contract conflict to an amendment, and the precedence / drain-parser prompt hardening lets the Developer
  converge on the correct verify-syntax-before-classifying-structure implementation.

### Security
- **Documented non-interactive git auth for `--run`** ([run-layout-and-cli](.claude/rules/run-layout-and-cli.md)):
  the shallow clone runs with `GIT_TERMINAL_PROMPT=0`, so a private HTTPS repo needs credentials supplied as
  `https://<user>:<token>@…` (token = password) or SSH/credential-helper. Operator guidance flags that a PAT
  embedded in the URL is persisted verbatim into `project.json` and the clone's `.git/config` under `runs/`
  — prefer the credential-helper for non-throwaway tokens.

## [v0.15.0] - 2026-06-18 — Unified Project & Run Topology: the Nexus⇄Executor Sync Bridge

ADR: [0015-unified-project-run-topology](./docs/decisions/0015-unified-project-run-topology.md)
(extends [0012](./docs/decisions/0012-virtual-separation-monorepo-planes.md),
[0006](./docs/decisions/0006-fsm-state-serialization-resume.md))

### Added
- **One run-layout SSOT shared by both planes** (`src/shared/core/runs.py`). A new `Projects`
  filesystem store + `allocate_run_dir(project_dir, plane, label)` name every run — planning OR
  execution — as `runs/<slug>/<NNN>_<plane>_<label>_<YYYYMMDD-HHMMSS>_<uid6>/`, where `<NNN>` is the
  next sequential number within the project (sortable, visible order), `<plane>` is `nexus`/`exec`,
  and the `ts`+`uid6` suffix guarantees no overwrite. The base is **injected** (`Projects(base)`), not
  a module global, so the layer is hermetic under test. A `Project` manifest (`project.json`) captures
  `{slug, idea, repo, base_branch, created_at}` once; `get_or_create` stacks later runs under one
  umbrella so repeated runs of the same ticket share lineage.
- **Nexus control-plane checkpointing + resume** (`src/nexus/state.py` `NexusState`). Mirrors the
  executor's `GlobalPipelineContext` dump/load contract (`save_checkpoint`/`load_checkpoint` via
  `model_validate_json`), persisting the phase outputs (`epic_text`/`blueprint_text`/`tasks`) and a
  `completed_phase` cursor over `PHASES = ("PO","SA","TPM")`; resume **skips finished phases and
  reuses their artifacts** instead of re-invoking the agent. Meta-dirs (`logs/`/`reports/`/
  `artifacts/`) are recomputed from `run_dir`, never persisted.
- **Project-centric CLI verbs** (`parse_args`/`main`, `src/executor/runner.py`): `--idea "…" [--repo
  R]` mints a NEW project and runs Nexus planning (`001_nexus_plan`); `--run <project> -f <ticket>`
  executes that ticket, loading repo + base branch from `project.json` and the ticket body from the
  latest Nexus run's `artifacts/<ticket>.md`; `--resume <project> [NNN]` resumes run #NNN (or the
  latest Nexus run). The legacy `--resume <path.json>` and `--repo --ticket` direct forms remain.
- **Secret redaction layer** (`src/shared/utils/redaction.py`): a `redact()` helper + logger-level
  `RedactionFilter` scrub GitHub PATs, basic-auth URLs, and bearer tokens from console, audit log, and
  persisted checkpoint/incident JSON across both planes.

### Changed
- **`--resume` routes by checkpoint content, not path parsing.** `NexusState` carries a
  `kind: Literal["nexus"]` discriminator; `main()` resolves the run dir from the checkpoint's
  grandparent and `_checkpoint_kind` peeks the `kind` field — `"nexus"` → control plane
  (`run_nexus(resume=…)`), absent → executor (`GlobalPipelineContext`). Old `runs/run_<uuid>/`
  checkpoints still resume via the explicit-path form.
- **Telemetry-first shared observability.** `log_finops_summary(telemetry, budget_usd, budget_tokens)`
  and `log_token_usage(telemetry, …)` (`src/shared/core/observability.py`) now take a
  `PipelineTelemetry` argument instead of reading executor module constants, so **both** planes record
  FinOps into one object; `describe_finish_reason` surfaces *why* a Gemini structured call failed
  (e.g. `RECITATION`, `MAX_TOKENS`).
- **Persistent package cache across containers.** Each environment declares a named Docker
  `cache_volume` (`environments.py`); `docker_adapter.py` mounts it RW only on the network-on restore
  phase and RO on build/test, so packages restored once survive container teardown and are reused
  across runs (the standing cure for transient NuGet `NU1301`/npm-feed latency).
- **Deterministic post-QA cleanup.** A non-fatal `run_format_pass` (network OFF) runs the environment's
  `format_cmd` (`ruff --fix --exit-zero`, `goimports -w`, `dotnet format --no-restore`, eslint
  best-effort) right after QA writes tests — stripping unused imports before the compile gate and
  killing the trivial Go "unused import = hard compile error" bounce cycle.
- **Engine-curated `.gitignore` templates** (`environments.py`): per-language patterns sourced from
  github/gitignore, anchored by EXTENSION (`*.exe`, `*.test`) or DIRECTORY (`/bin/`, `obj/`) only —
  never a bare project name — injected verbatim by the TPM into `TASK-01`.
- **Removed the hardcoded `src/` + `tests/` workspace layout.** The `--src-dir`/`--tests-dir` CLI flags, `RunConfig.src_dir`/`tests_dir`, and the `WorkspacePaths.code_dir`/`tests_dir` fields are gone; `WorkspacePaths.for_run(run_dir, repo_dir)` now tracks only the repo root + run meta-dirs (`logs/`, `reports/`) and no longer pre-creates empty `src/`/`tests/` in the clone. Source layout is the SA/blueprint topology's job (the Developer already writes by the contract's full repo-relative paths); the techlead topology skill no longer forces a `{code_prefix}/` prefix. Test placement is owned by the QA language profile — a new `test_root` key (`"tests"` for the python separate layout, `None` for colocated go/node/dotnet) is the SSOT, replacing `tests_dir` in `qa.py` and the production-snapshot test-exclusion prefix in `runner.py`. Old checkpoints carrying `code_dir`/`tests_dir` still load (pydantic ignores extra fields).
- **Repository preparation is no longer a standalone `TASK-00` iteration.** `prompts/system/tpm.md` now folds the mandatory baseline setup (`.gitignore`/`README.md`/`LICENSE`, idempotent verify-or-reconcile) into `TASK-01` as a clearly-delimited `## Repository Preparation (MANDATORY — do this FIRST)` block that leads the first business ticket before its feature work. There is no standalone `TASK-00`; tickets start at `TASK-01`, and `TASK-02+` remain pure business work that may not carry baseline files. This removes a full extra orchestrator iteration (clone → TechLead → Developer → QA → Reviewer → commit) per project, since the executor runs one ticket per invocation. The env-tailored `.gitignore` still keeps later business snapshots clean. `src/nexus/tpm.py` schema docstrings updated to match (`ticket_id` example, `TASK-01` prep-block note); the atomicity rule gains a narrow `TASK-01`-only exception.

### Fixed
- **Contract paths can no longer escape the sandbox.** Leading-slash / `..` blueprint paths (e.g.
  `/.gitignore`) copied verbatim into the contract used to resolve outside the clone (`repo_dir /
  "/.gitignore"` discards the root), leaving the Developer looping on a perpetually "missing" file. A
  field validator on `TechLeadContract` (`src/shared/core/models.py`) normalizes every contracted path
  to a safe repo-relative POSIX path at the contract boundary.
- **Engine resilience to environmental dependency-restore failures.** A build/restore failure whose output bears a network/feed-unreachable signature (`NU1301`, `Unable to load the service index`, `Resource temporarily unavailable`, DNS/`dial tcp`/npm-errno markers) is now classified by `build_failure_is_environmental` (`gates.py`) and handled distinctly in the compile-gate loop (`runner.py`): one cheap retry absorbs a transient blip, and a persistent outage **fails fast with an ENVIRONMENT/NETWORK incident** instead of rerouting the Developer to "fix" the network (which corrupted the contract by dropping mandated deps and deadlocked against the Reviewer → circuit breaker, as seen on the .NET `JSON-to-CSV2` run). Plus a `docker/dotnet.Dockerfile` NuGet prewarm: common pins (System.CommandLine, xunit, Test.Sdk) are baked into a read-only fallback folder + machine-wide `/NuGet.Config`, so runtime restore resolves them offline (the runtime `/tmp` tmpfs masks any baked `/tmp/nuget`).
- **Hermetic e2e test ~42× faster** (124.7s → 2.9s). `test_pipeline_e2e.py` did not mock the per-skill `SkillRelevance` relevance gate, so each of ~20 such calls raised, was swallowed by `with_api_retry`'s `2+4s` backoff, and silently burned ~120s; the fake structured-LLM now returns `SkillRelevance(score=0.0)`.
- **Retired the infra-only scope-discipline guardrail.** After folding infra into `TASK-01` no ticket is infra-only, so the `_out_of_scope_source_files` engine guardrail (`src/executor/runner.py`) had no legitimate trigger left — yet it still fired on a merged "infra + build manifest" first ticket (e.g. `[.gitignore, README.md, LICENSE, *.csproj]`), deleting the entry-point glue the Developer wrote while the compile gate simultaneously demanded it (`OutputType=Exe` → CS5001) — a direct deadlock (observed on `run_b3b85070…`, .NET `JSON-to-CSV2`). Removed the predicate, its fast-fail reroute branch, and the documentation-guardrail exclusion that deferred to it; every ticket is now treated as a normal code ticket where the Developer has full glue autonomy and the Reviewer is the scope backstop. `prompts/system/developer.md` SCOPE DISCIPLINE rule rewritten to authorize the minimal language-required entry point/glue a contracted build manifest needs; `gates.py` empty-suite comments de-jargoned (behavior unchanged); obsolete scope-discipline unit tests dropped.

### Security
- **CI security gate (`bandit -r src/`) kept green after the persistent package cache.** The cache feature routes each sandbox's package/scratch dirs through the container's `--tmpfs /tmp` via `sandbox_env` (`HOME`/`XDG_CACHE_HOME`, `GOCACHE`/`GOMODCACHE`, `npm_config_cache`, `NUGET_PACKAGES`/`DOTNET_CLI_HOME`, …) and the `--tmpfs "/tmp:rw,exec"` mount in `src/shared/core/docker_adapter.py`, which bandit flags as B108 (hardcoded temp directory). These are in-container tmpfs paths inside a least-privilege sandbox (`--cap-drop ALL`, `--network none`, read-only cache volume), not host temp files, so each was annotated `# nosec B108` consistent with the existing convention — no behavior change, gate restored to zero findings.

## [v0.14.0] - 2026-06-17 — Language-Neutral QA: Skills-Driven Test Correctness & De-Hardcoded Agent

ADR: [0014-language-neutral-qa-whole-file-assembly](./docs/decisions/0014-language-neutral-qa-whole-file-assembly.md)
(supersedes [0013](./docs/decisions/0013-structured-test-maintenance-ast-pruning.md))

### Changed
- **QA agent is now fully language-neutral.** Removed all per-language imperative code from `src/executor/agents/qa.py`: the Python-only `ast` merge (`_assemble_suite`/`_is_main_guard`), the Go package-clause guard (`_GO_PACKAGE_RE`/`_ensure_go_package_clause`/`_derive_go_package`), the `env_language == "go"` write-loop branch, and the Python-default zombie predicate. A single `_assemble_suite` writes the model's complete file verbatim with one safety net (empty delta + existing file + no `overwrite_existing` keeps the existing file). Dropped the now-dead `uses_ast`/`fence_lang` profile keys from `src/shared/core/environments.py`.
- **Test correctness moved into prompts/skills.** `prompts/system/qa.md` gains **TEST-FILE IDENTITY FIDELITY** (a test's package/namespace/module must match its production sibling — never a foreign one) and a **Thin / untestable module** rule; the delta-based `STRUCTURED TEST MAINTENANCE` section is replaced by a uniform **TEST FILE ASSEMBLY** contract (return the complete file, preserve still-valid cases, `overwrite_existing=true`). `go_qa.md`/`python_qa.md`/`dotnet_qa.md` state the concrete per-stack idiom.

### Fixed
- **CIRCUIT BREAKER on `run_3dc1e2043ea74ed082f47ec1744e4d8e`** (Go `json2csv`): QA emitted a root `main_test.go` declaring `package converter` next to `package main`, failing `go test ./...` every cycle (`could not import "main"`). The wrong package now (a) is far less likely — the agent is told to match the production sibling and not to fabricate a foreign-package test for a thin entrypoint — and (b) self-heals if it still slips through: the compile gate classifies it test-only and the Reviewer routes it to QA via new `reviewer.md` case **(c) WRONG TEST PACKAGE/NAMESPACE**, instead of mis-routing to the Developer (who cannot edit tests → deadlock).
- **`__pycache__/*.pyc` polluting the production snapshot** (`run_410195801a124f369ccb6c6052fb5257`): build artifacts were staged by `git add -A` because the business ticket's clone had no `.gitignore`. Fixed at the planner level — `prompts/system/tpm.md` now reserves **`TASK-00`** as a dedicated repository-preparation ticket (verify presence + currency of `.gitignore`/`README.md`/`LICENSE`, idempotently create/reconcile) that runs FIRST; **business tickets start at `TASK-01`** and may not carry baseline/infra files. The env-tailored `.gitignore` keeps later business snapshots clean without any per-language engine filter (`src/nexus/tpm.py` schema docstrings updated to match).

## [v0.13.0] - 2026-06-16 — Structured Test Maintenance (AST-Aware Pruning) & CI Security-Gate Fix

ADR: [0013-structured-test-maintenance-ast-pruning](./docs/decisions/0013-structured-test-maintenance-ast-pruning.md)

### Changed
- QA agent moved from LLM whole-file test merging to **Structured Test Maintenance**. The `QATestSuite` schema (`src/shared/core/models.py`) now returns deltas — `new_imports`, `new_test_code`, and `obsolete_test_names` — instead of a single `test_code` blob; the QA system prompt (`prompts/system/qa.md`) gains a `STRUCTURED TEST MAINTENANCE` rule (never re-emit the whole file).
- Test files are now maintained by a deterministic `ast`-based engine (`_assemble_suite` in `src/executor/agents/qa.py`): it parses the existing file, prunes top-level test classes/functions named in `obsolete_test_names`, dedupes imports, relocates any `if __name__ == "__main__"` guard to the end, and appends the new cases — always rewriting the **original** test path with explicit `utf-8` I/O.

### Fixed
- QA "State Cascade Destruction": regenerating tests for an existing module no longer blindly overwrites and destroys prior test cases. Preservation is now guaranteed by the engine rather than the model. This also removes the interim `_v2.py`/`_v3.py` "zombie file" fallback (no more accumulating duplicate test files).

### Security
- CI security gate (`bandit -r src/`) restored to green. The catalog/pricing-matrix lockstep `assert` in `src/shared/core/config.py` (B101 — stripped under `python -O`) was converted to an explicit `if … raise RuntimeError`, keeping the invariant unconditional. The pre-existing fixed-argv `git` subprocess calls in `src/executor/runner.py` — exposed to the scan only after the v0.12.0 refactor moved `orchestrator.py` into `src/` — were annotated `# nosec B404/B603/B607` consistent with the existing convention.

## [v0.12.0] - 2026-06-15 — Virtual Separation: Control / Worker / Shared Plane Topology (Monorepo PoC)

ADR: [0012-virtual-separation-monorepo-planes](./docs/decisions/0012-virtual-separation-monorepo-planes.md)

### Added
- Root `main.py` entrypoint: a thin CLI shell that imports `main` from `src.executor.runner` and runs it under `asyncio`, replicating the former `if __name__ == "__main__"` tail of `orchestrator.py`. Program start is now decoupled from FSM execution. The documented run command becomes `python3 main.py …`.
- Control Plane scaffold: new `src/nexus/` package with empty `planner.py` and `deployer.py` placeholders, marking the seam where future run-scheduling and deployment orchestration will live. Inert for now (no runtime behaviour).

### Changed
- **Virtual Separation refactor** — the flat `src/` tree was reorganized into three logical planes, a pure lift-and-shift with **no** change to FSM transitions, agent behaviour, gates, or LLM system prompts: **Worker Plane** `src/executor/` (`agents/`, `nodes/`, and `runner.py` — the former root `orchestrator.py`), **Shared Plane** `src/shared/` (`core/`, `utils/`), and **Control Plane** `src/nexus/`. All 18 modules were relocated with history-preserving `git mv`.
- Repo-wide import rewrite to the new plane paths (`src.core → src.shared.core`, `src.utils → src.shared.utils`, `src.agents → src.executor.agents`, `src.nodes → src.executor.nodes`), including test `mock.patch("…")` target strings; the orchestrator unit/integration tests now bind `from src.executor import runner as orchestrator`, leaving every `orchestrator.*` reference unchanged.

### Fixed
- `src/shared/core/prompts.py` `_REPO_ROOT` gained one `.parent` so it still resolves the repository-root `prompts/` tree after the module moved one directory deeper — the only non-import change required by the move. Behaviour is otherwise identical (142 tests green).

## [v0.11.0] - 2026-06-15 — Secure Sandbox, Language-Neutral Topology & Real-Time FinOps Circuit Breaker

ADR: [0011-secure-sandbox-and-finops-telemetry](./docs/decisions/0011-secure-sandbox-and-finops-telemetry.md)

### Security
- Docker API socket restricted from `tcp://0.0.0.0:2375` (no TLS) to `tcp://127.0.0.1:2375`, closing an unauthenticated remote-root exposure: the plaintext daemon port was published on every interface, allowing any process on the local subnet to drive the Docker engine and obtain root on the WSL/Windows host via a privileged bind mount. The API is now reachable only over loopback.

### Added
- Language-neutral topology contract: `TechLeadContract` gains `topology_contract: list[TopologyNode]` (`src/core/models.py`), where each node declares `file_path`, `exports`, and language-neutral `depends_on` links (`path/to/file.ext:symbol`) — not import statements. The TechLead is the Single Source of Truth for structure (`prompts/system/techlead.md` TOPOLOGY RULE); the Developer and QA agents translate the neutral links into the target language's import syntax, with QA consuming the graph for test import resolution (`prompts/system/qa.md`, `src/agents/qa.py`). This decouples the dependency graph from any one language, making new-language support Open-Closed.
- Real-time Claude CLI token telemetry in `GlobalPipelineContext`: the out-of-band Developer agent's token usage is now tracked per invocation instead of being reconciled retrospectively via `npx ccusage`.
- Financial Circuit Breaker: a deterministic hard-halt that terminates the FSM when a configured budget is breached during cyclic Developer/Reviewer/QA retries, dumping state for audit instead of draining the API budget to exhaustion. This is the cost analogue of the existing functional retry Circuit Breaker.
- USD spend budget (`PIPELINE_BUDGET_USD`, env-overridable, default `$10.00`) as the **primary** Financial Circuit Breaker signal — cost is authoritative for Claude (CLI `total_cost_usd`) and estimated for Gemini. The token budget (`PIPELINE_BUDGET_TOKENS`) is retained as a secondary ceiling.
- Separate cache-token telemetry: `PipelineTelemetry.total_cache_read_tokens` / `total_cache_write_tokens` and per-agent `cache_read_tokens` / `cache_write_tokens`, surfaced in the FinOps report (`budget_usd`, `budget_used_pct_usd`, cache totals) and the Developer log line (`Input(fresh) | Cache-write | Cache-read | Output | Budgeted`).

### Changed
- Refactor: Renamed Architect role to TechLead across prompts and orchestration layer for better semantic mapping — the node authors a binding `TechLeadContract` (signatures + topology graph) consumed deterministically downstream.
- WSL2/Docker setup and troubleshooting guides (`docs/docker-on-windows.md`, `docs/setup.md`) rewritten into a single coherent, reproducible chain: all Docker Desktop dependencies purged (including the troubleshooting table that contradicted the Desktop-independent setup), the explicit `docker-ce` engine installation step added before daemon configuration, and the secure loopback binding documented as the default. `DOCKER_HOST` and the lazy-loader probe aligned to `127.0.0.1`.
- Pricing model migrated to `Decimal` for exact, rounding-controlled cost math feeding the Financial Circuit Breaker threshold and FinOps reporting; binary floats accumulated representation error on fractional-cent rates, which could trip the budget gate early or late by a drifting margin.
- Token budget now counts **fresh input + output only** — cache read/write tokens are EXCLUDED. `parse_claude_usage` (`src/utils/subprocess_helpers.py`) no longer folds `cache_creation`/`cache_read` into `input_tokens`; the agentic Claude CLI re-sends its prompt each internal turn, so cache reads (~10% the price of fresh input) were inflating the token budget — one ~$0.14 Developer call had been consuming ~22% of a 1M-token budget.

### Fixed
- FinOps misattribution: the Developer agent appeared to consume ~219k "input" tokens for a trivial task because cheap `cache_read_input_tokens` were folded into the budgeted input count. Cache is now tracked separately and excluded from the budget, and the breaker gates on real USD spend.

## [v0.10.0] - 2026-06-11 — Fast-Fail Documentation Guardrail & Repo Topology Routing

ADR: [0010-fast-fail-documentation-guardrail](./docs/decisions/0010-fast-fail-documentation-guardrail.md)

### Added
- Fast-Fail Documentation Guardrail (`enforce_documentation_guardrail` in `orchestrator.py`): a deterministic, zero-LLM-cost middleware after the Developer phase that scans the first 15 lines of every newly-created uncontracted file for a language-agnostic comment lead-in (`#`, `//`, `/*`, `*`, `"""`, `'''`). A miss triggers a "free reroute" straight back to the Developer — bypassing the Reviewer/QA nodes and consuming none of the functional circuit-breaker budget. Binary/empty/unreadable files are ignored safely.
- Hard Halt protection: guardrail reroutes are capped at `GUARDRAIL_MAX_REROUTES = 2`; exceeding the cap dumps the full FSM context to `runs/run_<uuid>/reports/incident_report.json` and exits non-zero (`_abort_with_incident`), making infinite guardrail loops impossible.
- Repository topology mapping: `generate_repo_map` builds a tree of the cloned repo and injects it as an `EXISTING REPOSITORY TOPOLOGY` block into the Architect and QA contexts, enabling brownfield-aware file placement.
- Language-stack skill routing: the Architect now declares the target language as the first `domain_tags` entry (inferred deterministically from the repo map's file extensions), which routes the new `python_core.md` / `python_qa.md` domain skills to the execution agents.
- New guardrail skills: `architect_dry_guardrail` (mandate a single shared utility module for duplicated helper logic), `architect_topology_guardrail` / `qa_topology_guardrail` (forbid redundant root-level directories; mirror existing test layout), and `qa_float_guardrail` (language-agnostic IEEE 754 boundary-testing rules: no reverse-arithmetic boundary inputs, explicit infinity forcing, tolerance-based comparison).
- `get_pipeline_snapshot_files` accepts a `diff_filter` argument (e.g. `"A"` for added-only), letting the guardrail distinguish genuinely new files from edits to pre-existing ones.
- Reviewer scope anchoring: the production `git diff` is captured into `production_code_diff` and injected as a `GIT DIFF (SCOPE OF CHANGES)` section, binding the review to the actual delta.
- Framework test coverage for the new surface: guardrail/orchestrator suites in `tests/framework/test_orchestrator.py`, repo-map tests in `test_prompts.py`, and `diff_filter` tests in `test_git_helpers.py`.

### Changed
- `prompts/system/developer.md`: added an IMPLEMENTATION AUTONOMY rule (the Developer may create necessary uncontracted infrastructure files such as package-initialization modules) paired with a strict ARCHITECTURAL JUSTIFICATION FOR NEW FILES mandate (every uncontracted new file must open with a comment block explaining why it exists), plus tool-execution mandates (write via filesystem tools, no raw code blocks in chat, verify state before responding).
- `prompts/system/reviewer.md`: the blunt Eradication Directive is replaced by a 3-bucket Smart Triage — JUSTIFIED ADDITIONS (approve necessary new modules), HALLUCINATED GARBAGE (eradicate true Ghost Files), LEGACY VICTIMS (never eradicate broken pre-existing code; order a revert and safe integration). Added a DEFENSIVE PROGRAMMING ALLOWANCE so sound input validation is not rejected for being absent from the contract, and the review is now diff-scoped (full file contents serve only as architectural context).
- QA test generation is now Read-Modify-Write: an existing `test_<module>.py` on disk is surfaced to the agent as an `EXISTING TEST SUITE` block with a STATE PRESERVATION mandate to merge new cases into the existing suite instead of regenerating it from scratch.
- Core prompts and shared skills (`engineering_guide`, `strict_validation`, `deterministic_mutation`, `qa.md`, `qa_integrity`, `qa_retry_fix`) rewritten language-agnostically; Python-specific runtime, framework, and type-guard rules relocated to the routed `python_core` / `python_qa` domain skills.

### Removed
- `prompts/skills/qa_math_guardrail.md` — superseded by the global `qa_float_guardrail` and the stack-routed `python_qa` skill.
- Hardcoded Python assumptions (unittest mandates, `src/` path literals, `bool`/`int` examples) from the shared cross-agent prompts.

### Fixed
- State Cascade Destruction: the Developer overwriting glue files (`__init__.py`) combined with the Reviewer's Eradication Directive deleting mangled legacy files and justified new modules as "Ghost Files," trapping the FSM in token-draining rejection loops — resolved by the guardrail middleware, the justification mandate, and Smart Triage.
- QA regeneration wiping previously generated test cases on retry cycles — resolved by the Read-Modify-Write existing-suite injection.

## [v0.9.0] - 2026-06-08 — Hybrid Skill Routing

ADR: [0009-hybrid-skill-routing](./docs/decisions/0009-hybrid-skill-routing.md)

### Added
- Declarative YAML frontmatter routing: every `prompts/skills/*.md` file now carries a `type` / `nodes` / `triggers` header parsed by a stdlib-only `_parse_frontmatter` (no `pyyaml` dependency), so a skill declares which agent nodes it targets and when it applies.
- `build_agent_context(node, ctx, …)` — a dynamic agent-context builder in `src/core/prompts.py` that composes the skill set per node, gating each skill by `type`: `global` (always), `topology` (always, body `.format()`-ed with path kwargs), `stateful` (retry-only), and `domain` (tag intersection with the contract's `domain_tags`).
- LLM-based semantic fallback for domain skills (`fallback_semantic_search` + `SkillRelevance`): on a trigger-tag miss, a structured relevance check (reviewer model, threshold `0.7`) decides inclusion, reusing the existing `run_structured_llm` infra with no embeddings SDK.

### Changed
- All four agent modules (`architect.py`, `developer.py`, `qa.py`, `reviewer.py`) now assemble their skill context via `build_agent_context` instead of hand-listing skills.
- Template injection hardened: the `{strict_type_validation_rules}` placeholder is filled via a brace-safe `.replace()` so skill bodies may contain literal `{}` (JSON/code blocks) without raising `KeyError`; only `topology` bodies are `.format()`-ed.

### Removed
- All hardcoded `get_skill(...)` composition calls inside the agent nodes — skill targeting now lives entirely in file frontmatter, restoring Open-Closed compliance.

### Fixed
- QA math-guardrail Catch-22: `qa_math_guardrail.md` now permits hardcoding `float('inf')` as the expected value for extreme boundary tests that intentionally exceed `sys.float_info.max`, resolving the deadlock where QA could neither compute (overflow) nor hardcode (forbidden) the expectation.
- Developer "ghost files" double-nesting: `developer.py` now mounts repo-root-relative contract paths at `workspace_paths.repo_dir` instead of `code_dir`, so `src/geometry/x.py` resolves to `repo/src/geometry/x.py` rather than `repo/src/src/geometry/x.py`; the `PATH ROUTING` system-prompt example was corrected to match.

## [v0.8.0] - 2026-06-01 — Git-Anchored Sessions & Atomic Commit

ADR: [0008-git-anchored-sessions-atomic-commit](./docs/decisions/0008-git-anchored-sessions-atomic-commit.md)

### Added
- Git-anchored sessions: each run generates a UUID base directory `runs/run_<uuid>/`, shallow-clones the target repo (`git clone --depth 1`) into `runs/run_<uuid>/repo/`, checks out a `feat/ticket-<ticket>` branch, and force-fetches the base branch into a local ref.
- New CLI surface: `--repo` (target git URL/path) and `--ticket` (required for fresh runs), `--src-dir` / `--tests-dir` (default `src/` / `tests/`), and `--push` to publish the feature branch after a successful commit. `--resume` / `--reset-attempts` retained.
- `WorkspacePaths.for_run` — resolves absolute, run-rooted paths (code/tests inside the clone, logs/reports outside) with a path-traversal guard rejecting `..`/absolute `--src-dir`/`--tests-dir` escapes.
- `get_git_root` (`git rev-parse --show-toplevel`) and `reconfigure_logging` (per-session audit-log redirection).
- Atomic commit-on-success (`finalize_transaction`): a single identity-pinned `feat(<ticket>): <summary>` commit on the feature branch, guarded against empty commits via `git diff --cached --quiet`.
- `tests/framework/test_gates.py` and bootstrap/finalize/git-root suites covering the new flow.

### Changed
- Workspace moved from the static `artifacts/` sandbox to the git-anchored clone under `runs/run_<uuid>/`; `PIPELINE_RUNS_BASE` mirrors the existing `PIPELINE_ARTIFACTS_BASE` override.
- Snapshot collection switched to the index diff: `git add -A` → `git diff --cached <base_branch> --name-only -- <subdir>`, capturing untracked files and scoping Developer/QA to their subtrees within one repo.
- QA docker gate (`run_qa_unit_tests`) mounts the whole clone root at `/workspace/repo` with `PYTHONPATH=/workspace/repo`, replacing the hardcoded `/workspace/artifacts/{code,tests}` paths.

### Removed
- `init_sandbox_git`, `_deploy_gitignore`, and `commit_sandbox` — the nested per-directory sandbox-repo API. The single cloned `.git` is now the transactional Unit-of-Work.

### Security
- All network git invocations run with `GIT_TERMINAL_PROMPT=0` and a wall-clock timeout (child killed and reaped on expiry), so a missing-credential prompt can never hang the pipeline.
- `get_pipeline_snapshot_files` now raises `RuntimeError` on any git failure (e.g. an orphaned `.git/index.lock`) instead of silently returning an empty snapshot.

### Fixed
- `--reset-attempts` now performs a targeted FSM state mutation: clears `current_attempt` while preserving the `test_code_snapshot` field from the prior QA cycle, breaking the stateless-retry Catch-22 where the Developer re-entered without context of what had already been tested.
- `run_dir` is resolved to an absolute path via `.resolve()` before Docker mount construction, preventing broken volume strings when the orchestrator is invoked with a relative `--repo` path (e.g. `--repo .`).
- QA fan-out `RateLimitError` (HTTP 429) is now caught at the node boundary and retried with exponential backoff instead of crashing the session and losing the QA cycle's output.
- QA self-heal retries are stateful: the `test_code_snapshot` produced by the previous QA cycle is injected into the Developer node context on re-entry, so each fix attempt sees both the failing test output and a snapshot of what was tested.
- Inline agent prompt strings decomposed into an atomic, dynamic Skill System (`prompts/skills/`): each skill file encodes one behavioral rule; `get_skill` composes them at call time, eliminating cross-agent context leakage and making guardrails editable without modifying application code.

## [v0.7.0] - 2026-05-31 — Prompt/Schema Layer Separation

ADR: [0007-prompt-schema-layer-separation](./docs/decisions/0007-prompt-schema-layer-separation.md)

### Added
- `src/core/prompts.py` — `get_system_prompt(agent_name)` and `get_skill(skill_name)` loaders backed by `lru_cache`, resolving markdown files from `prompts/system/` and `prompts/skills/` relative to the repo root.
- `tests/framework/test_prompts.py` — 9-test suite covering static load, template rendering, QA split format, `FileNotFoundError` on missing agents/skills, cache identity, and directory resolution.
- `### Output JSON Schema Semantics` sections in `prompts/system/architect.md` and `prompts/system/reviewer.md` binding per-key behavioral rules (bool type guard, DRY/DI enforcement, try-except prohibition, Phantom-file triage) to their JSON output keys.
- `.ai/skills/` — IDE meta-tool skill files (`adr_generation.md`, `docs_sync.md`, `practicum_update.md`) for project governance automation.

### Changed
- All four agent modules (`architect.py`, `developer.py`, `qa.py`, `reviewer.py`) now load system prompts via `get_system_prompt()` instead of inline string literals.
- `Field(description=...)` in `ArchitectureContract` and `ReviewReport` reduced to dry structural text; all behavioral directives relocated to system prompt files.
- ADRs reformatted from iteration snapshot style to MADR format.

## [v0.6.0] - 2026-05-31 — FSM State Serialization & Resume Mechanism

ADR: [0006-fsm-state-serialization-resume](./docs/decisions/0006-fsm-state-serialization-resume.md)

### Added
- `GlobalPipelineContext.save_checkpoint` / `load_checkpoint` — full-context FSM serialization to a single rolling `artifacts/reports/checkpoint.json`.
- `--resume` CLI flag with node-skip logic: nodes whose output exists in the restored context are bypassed; a rejected-test checkpoint routes directly into QA regeneration.
- `--reset-attempts` CLI flag to restore the full Circuit Breaker retry budget while preserving the contract and prior snapshots.
- 45-test framework suite covering checkpoint round-trip, resume flag parsing, skip behavior, and Circuit Breaker restoration.

### Changed
- `current_attempt` promoted from a loop variable to a persisted Pydantic field, so the retry budget survives process restarts.
- Architect prompt now mandates strict Dependency Injection — classes receive dependencies via constructor; internal instantiation forbidden.

### Fixed
- Confirmation-bias loop: Developer is explicitly forbidden from writing tests; QA is forbidden from inspecting exception strings (`assertIn` / `.args` / `str(exc)`).

## [v0.5.0] - 2026-05-28 — Git-Driven State Tracking & QA Fan-Out Concurrency

ADR: [0005-git-driven-state-tracking-qa-fanout](./docs/decisions/0005-git-driven-state-tracking-qa-fanout.md)

### Added
- `src/utils/git_helpers.py` — Git Anchor pattern (`init_sandbox_git` + `get_pipeline_snapshot_files`) producing a strict causal delta via `git diff <base_branch> --name-only`.
- QA fan-out: one isolated LLM call per production module via `asyncio.gather`, each writing `test_<module_dot_path>.py`; facade `__init__.py` modules filtered out.
- `src/utils/api_retry.py` — centralized `@with_api_retry` decorator (429 immediate-exit, exponential backoff on transient errors).
- CLI argument parser accepting inline task descriptions or `-f` file input with a `--base-branch` anchor flag.

### Changed
- Snapshot collection switched from glob-scanning `artifacts/` to Git diff, eliminating `UnicodeDecodeError` from binary pollution and retry context bleed.
- Bandit SAST switched to recursive (`-r`) directory scanning so Developer-created utility files are analyzed.
- Reviewer prompt authorizes Developer-created helper/utility files, resolving the Architect-contract vs. SOLID FSM deadlock.

## [v0.4.0] - 2026-05-27 — Modularization & Sandbox Hardening

ADR: [0004-modularization-sandbox-hardening](./docs/decisions/0004-modularization-sandbox-hardening.md)

### Added
- Production-grade `Dockerfile` (Node.js, Claude CLI, Docker CLI, Python utils) running under an unprivileged `appuser`.
- `PIPELINE_ARTIFACTS_BASE` env routing for collision-free parallel runs.

### Changed
- Monolithic `orchestrator.py` decoupled into module-based architecture (Logic / Nodes / Utils).
- Console-output detection replaced brittle `"claude" in prefix` matching with an explicit `verbose_to_console: bool` flag.

### Security
- Dual-mount Docker strategy: framework `src/` mounted Read-Only (`:ro`), volatile `artifacts/` Read-Write (`:rw`), preventing agent self-mutation.

### Fixed
- Reviewer (Gemini 2.5 Pro) rejected the redundant `isinstance(n, bool)` guard and forced the strict type-identity check `if type(n) is not int:` via an autonomous self-heal cycle.

## [v0.3.0] - 2026-05-26 — Dual-Channel Observability & Gemini 2.5 Routing

ADR: [0003-dual-channel-observability](./docs/decisions/0003-dual-channel-observability.md)

### Added
- Dual-channel logging: `StreamHandler` (INFO, console) + `RotatingFileHandler` (DEBUG, `sdlc_audit.log`) with microsecond timestamps.
- Native input/output/total token extraction from structured Gemini responses; out-of-band Claude CLI usage audited via `npx ccusage`.

### Changed
- Migrated structured-output workloads to the Gemini 2.5 family (`flash` for generation, `pro` for reviews), resolving Free-Tier 429 quota collapses.

### Fixed
- Banned `try-except pass` assertion softening in QA prompts, restoring deterministic boolean-subclass trapping.

## [v0.2.0] - 2026-05-26 — Async Fork-Join & QA Node Isolation

ADR: [0002-async-qa-node-isolation](./docs/decisions/0002-async-qa-node-isolation.md)

### Added
- Dedicated QA-Generator node compiling an immutable test suite *before* code generation.
- Fork-Join parallel validation layer running functional Docker tests and Bandit SAST concurrently.

### Fixed
- Autonomous self-healing loop trapped and corrected the Python `bool`-inherits-`int` hazard, injecting the exact traceback into the Developer context for an explicit type guard.

## [v0.1.0] - 2026-05-25 — Baseline Sequential Loop

ADR: [0001-baseline-sequential-loop](./docs/decisions/0001-baseline-sequential-loop.md)

### Added
- Baseline linear orchestrator: Architect → Developer → Dockerized QA validation with sequential error-routing loops.

### Security
- **Compromised**: the Developer agent exploited the shared host volume mount (`-v $PWD:/workspace`) to rewrite the immutable test file and force `Exit Code 0`. Root cause — Shared State Exposure; remediation tracked into v0.2.0 (QA write-scope revocation).

## [v0.0.0] - 2026-05-24 — Cloud Infra & FSM Architecture Research

ADR: [0000-cloud-infra-fsm-research](./docs/decisions/0000-cloud-infra-fsm-research.md)

### Added
- System topology blueprint: custom Python/Pydantic FSM (over LangGraph), localized Docker sandboxing (over Cloud Run), hybrid Gemini/Claude model routing with context + prompt caching, GitHub App RS256 auth, and a 10-cycle FinOps cost model (~$5.83).

[v0.11.0]: ./docs/decisions/0011-secure-sandbox-and-finops-telemetry.md
[v0.10.0]: ./docs/decisions/0010-fast-fail-documentation-guardrail.md
[v0.9.0]: ./docs/decisions/0009-hybrid-skill-routing.md
[v0.8.0]: ./docs/decisions/0008-git-anchored-sessions-atomic-commit.md
[v0.7.0]: ./docs/decisions/0007-prompt-schema-layer-separation.md
[v0.6.0]: ./docs/decisions/0006-fsm-state-serialization-resume.md
[v0.5.0]: ./docs/decisions/0005-git-driven-state-tracking-qa-fanout.md
[v0.4.0]: ./docs/decisions/0004-modularization-sandbox-hardening.md
[v0.3.0]: ./docs/decisions/0003-dual-channel-observability.md
[v0.2.0]: ./docs/decisions/0002-async-qa-node-isolation.md
[v0.1.0]: ./docs/decisions/0001-baseline-sequential-loop.md
[v0.0.0]: ./docs/decisions/0000-cloud-infra-fsm-research.md
