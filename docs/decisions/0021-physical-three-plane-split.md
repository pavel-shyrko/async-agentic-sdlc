# 0021 — Physical Three-Plane Split: Control (nexus) / Worker (development) / Infra (deployment)

## Status

Accepted — **supersedes the *virtual* topology of [0012](0012-virtual-separation-monorepo-planes.md)**
(makes the plane boundaries physical and fulfils its deferred control-plane promise); relocates the code
introduced by [0017](0017-nexus-executor-auto-dispatch.md)–[0020](0020-deploy-scaffolding-and-lint-gate.md)
without behaviour change.

## Context

ADR 0012 drew the engine's plane boundaries **virtually** — by package topology and import discipline —
and explicitly deferred the physical split: the separation was "still *virtual* … one process, one
`sys.path`", and the `src/nexus/` control plane was "a promise the topology makes but the code has not yet
kept" (its `planner.py`/`deployer.py` placeholders were inert).

Four iterations of autonomy growth (E1–E4, ADRs 0017–0020) then overloaded the **worker** plane. By
iteration 20, `src/executor/` held **three fundamentally different concerns** in one package:

1. **Per-ticket orchestration + the FSM** — `main()` (the CLI dispatcher), `run_executor` (the
   bootstrap → TechLead → self-heal cycle → finalize FSM), `run_batch` (the E3 multi-ticket loop),
   `finalize_pr`/`finalize_transaction`, the financial breaker, the incident writer, the resume helpers.
2. **Code generation + quality verification** — the six dev agents (techlead, developer, qa, reviewer,
   arbiter, techwriter) and the build/test/lint/SAST gates (`nodes/gates.py`).
3. **Infrastructure / CI-CD scaffolding** — the `devops` agent and the post-batch deploy-scaffolding
   (`run_devops_scaffold` + `run_devops_gate`, E4).

Meanwhile the **control** plane `src/nexus/` carried only the PO/SA/TPM planning trio + `nexus_runner.py`,
and its `deployer.py` placeholder remained a 0-byte orphan. The namespace had stopped encoding the
architecture: "executor" was simultaneously the orchestrator, the quality worker, **and** the infra
generator, while the plane meant to *own orchestration* (nexus) owned none of it. No FSM transition, agent,
gate, or prompt was wrong — the problem was again purely topological, exactly the class ADR 0012 set out to
prevent, now recurred at the next scale.

## Decision

Collapse the virtual line into a **physical** one: **remove `src/executor/` entirely** and redistribute its
contents along the three concern boundaries. `src/shared/` is untouched — it remains the SSOT both planes
build on. A pure lift-and-shift (history-preserving `git mv`); **no** change to FSM transitions, agent
behaviour, gates, prompts, or the lint logic.

### Part A — `src/nexus/` becomes the real control plane (orchestration + FSM + planning)
- The whole of `src/executor/runner.py` moves to **`src/nexus/runner.py`** *minus* the deploy-scaffolding
  functions: `main`, `parse_args`, `RunConfig`, `PipelineHalt`, `run_executor` (per-ticket FSM), `run_batch`
  (E3), `prepare_ticket_run`, `bootstrap_session`, `finalize_transaction`/`finalize_pr`, the FinOps/incident/
  financial-breaker/guardrail helpers, and the resume helpers all live here.
- The planning agents move under **`src/nexus/agents/`** (`po.py`, `sa.py`, `tpm.py`); `nexus_runner.py` +
  `state.py` stay. The inert `deployer.py` placeholder is **deleted** — the promise it stood for is now kept.

### Part B — `src/development/` is the worker plane (code generation + quality gates)
- The six dev agents move to **`src/development/agents/`** (`developer`, `qa`, `reviewer`, `arbiter`,
  `techlead`, `techwriter`).
- `executor/nodes/gates.py` is **flattened** to **`src/development/gates.py`** (build / test-compile /
  unit-test / **lint** (`run_lint_gate` + `classify_lint_findings`) / SAST gates + `run_format_pass`).

### Part C — `src/deployment/` is the infra plane (CI/CD scaffolding)
- The `devops` agent moves to **`src/deployment/agents/devops.py`**.
- The deploy-scaffolding orchestration moves to **`src/deployment/provision/`**: `scaffold.py`
  (`run_devops_scaffold` + `_env_ci_commands` + `_repo_has_source` + `_nexus_environment_ids` +
  `DEVOPS_MAX_RETRIES`) and `gates.py` (the self-contained `run_devops_gate` deploy-manifest static lint).

### Part D — the dependency graph and the one cycle it forces
The control plane orchestrates the workers, so the allowed edge direction is **`nexus → {development,
deployment}`** (`nexus/runner.py` now imports the dev agents + gates and, at call time, the deployment
scaffold). E4 forces **one unavoidable back-edge**: `run_devops_scaffold` (deployment) reuses the
control-plane SSOTs (`bootstrap_session`, `finalize_transaction`/`finalize_pr`, `_abort_with_incident`,
`write_finops_report`/`log_finops_summary`) rather than forking them — so `deployment → nexus` at module
load. To keep both top-level imports valid, `run_batch` imports `run_devops_scaffold` **lazily, at call
time** (the exact pattern `main()` already uses for `nexus_runner`), so `nexus.runner` finishes loading
before `scaffold.py`'s `from src.nexus.runner import …` resolves. The lazy import is the **documented seam**
for cyclic SSOT reuse: reuse the SSOT, defer the import.

### Companion — Edge Case C test hardening
A dedicated unit test pins the step-3.6 lint **no-progress guard**: when classified findings are
byte-identical across two consecutive iterations the fast-fail loop must break on the **2nd** iteration
(verified with `LINT_GATE_MAX_REROUTES` raised to 5, so a cap-driven stop would be 6 lint calls — observing
exactly 2 proves the guard, not the cap, fired) without exhausting the global retry/$ budget.

## Consequences

- **Pros.** The namespace encodes the architecture again: control / worker / infra each have an unambiguous
  home, and ADR 0012's deferred control-plane is now real rather than a placeholder. Plane boundaries are
  enforceable by import direction (`nexus → {development, deployment}`, with the single, documented
  `deployment → nexus` SSOT back-edge). `runner.py` shed the ~142 lines of deploy-scaffolding it should
  never have held. Behaviour is provably unchanged — 407 unit tests green, `bandit -r src/` clean — because
  every move was a `git mv` and the only edits were import paths + the lazy-import seam. The deploy-manifest
  gate now sits beside the scaffold that calls it (deployment owns its own validation).
- **Cons / constraints.** The split is now **physical in topology but still one process / one `sys.path` /
  one dependency set** — it buys legibility and enforceable boundaries, not yet independent deployability or
  separate packaging (no `pyproject.toml` per plane). The `deployment → nexus` cycle is real and is managed,
  not eliminated, by a lazy import — a structural reminder that the infra plane is not free of the control
  plane (it reuses the transaction/forge/FinOps SSOTs by design). The move churn was large (a 33-file
  rename surface + repo-wide import + `mock.patch` target rewrites, and a fresh ADR/docs/rules sweep), a
  one-time cost paid against future clarity.

> Validated: **407** unit tests green via WSL (406 → 407, +1 Edge Case C), `bandit -r src/` clean
> (28 `# nosec` preserved). Footprint `v0.20.0` → HEAD (`f99c375`): 33 files, +305/−228, all renames
> history-preserving. Archive: [iteration_21](../releases/iteration_21/iteration_21_README.md).
