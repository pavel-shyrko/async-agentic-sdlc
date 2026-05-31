# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Each release maps to a completed SDLC iteration; the corresponding Architecture
Decision Record (ADR) is linked from the version heading.

## [v0.7.0] - 2026-05-31 — Prompt/Schema Layer Separation

ADR: [0007-prompt-schema-layer-separation](./docs/adr/0007-prompt-schema-layer-separation.md)

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

ADR: [0006-fsm-state-serialization-resume](./docs/adr/0006-fsm-state-serialization-resume.md)

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

ADR: [0005-git-driven-state-tracking-qa-fanout](./docs/adr/0005-git-driven-state-tracking-qa-fanout.md)

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

ADR: [0004-modularization-sandbox-hardening](./docs/adr/0004-modularization-sandbox-hardening.md)

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

ADR: [0003-dual-channel-observability](./docs/adr/0003-dual-channel-observability.md)

### Added
- Dual-channel logging: `StreamHandler` (INFO, console) + `RotatingFileHandler` (DEBUG, `sdlc_audit.log`) with microsecond timestamps.
- Native input/output/total token extraction from structured Gemini responses; out-of-band Claude CLI usage audited via `npx ccusage`.

### Changed
- Migrated structured-output workloads to the Gemini 2.5 family (`flash` for generation, `pro` for reviews), resolving Free-Tier 429 quota collapses.

### Fixed
- Banned `try-except pass` assertion softening in QA prompts, restoring deterministic boolean-subclass trapping.

## [v0.2.0] - 2026-05-26 — Async Fork-Join & QA Node Isolation

ADR: [0002-async-qa-node-isolation](./docs/adr/0002-async-qa-node-isolation.md)

### Added
- Dedicated QA-Generator node compiling an immutable test suite *before* code generation.
- Fork-Join parallel validation layer running functional Docker tests and Bandit SAST concurrently.

### Fixed
- Autonomous self-healing loop trapped and corrected the Python `bool`-inherits-`int` hazard, injecting the exact traceback into the Developer context for an explicit type guard.

## [v0.1.0] - 2026-05-25 — Baseline Sequential Loop

ADR: [0001-baseline-sequential-loop](./docs/adr/0001-baseline-sequential-loop.md)

### Added
- Baseline linear orchestrator: Architect → Developer → Dockerized QA validation with sequential error-routing loops.

### Security
- **Compromised**: the Developer agent exploited the shared host volume mount (`-v $PWD:/workspace`) to rewrite the immutable test file and force `Exit Code 0`. Root cause — Shared State Exposure; remediation tracked into v0.2.0 (QA write-scope revocation).

## [v0.0.0] - 2026-05-24 — Cloud Infra & FSM Architecture Research

ADR: [0000-cloud-infra-fsm-research](./docs/adr/0000-cloud-infra-fsm-research.md)

### Added
- System topology blueprint: custom Python/Pydantic FSM (over LangGraph), localized Docker sandboxing (over Cloud Run), hybrid Gemini/Claude model routing with context + prompt caching, GitHub App RS256 auth, and a 10-cycle FinOps cost model (~$5.83).

[v0.7.0]: ./docs/adr/0007-prompt-schema-layer-separation.md
[v0.6.0]: ./docs/adr/0006-fsm-state-serialization-resume.md
[v0.5.0]: ./docs/adr/0005-git-driven-state-tracking-qa-fanout.md
[v0.4.0]: ./docs/adr/0004-modularization-sandbox-hardening.md
[v0.3.0]: ./docs/adr/0003-dual-channel-observability.md
[v0.2.0]: ./docs/adr/0002-async-qa-node-isolation.md
[v0.1.0]: ./docs/adr/0001-baseline-sequential-loop.md
[v0.0.0]: ./docs/adr/0000-cloud-infra-fsm-research.md
