# Iteration 21 — Physical Three-Plane Split: nexus / development / deployment

> ADR: [0021-physical-three-plane-split](../../decisions/0021-physical-three-plane-split.md) ·
> CHANGELOG: [v0.21.0](../../../CHANGELOG.md) · Practicum: [PRACTICUM.md](../../../PRACTICUM.md)

## Problem Statement

ADR [0012](../../decisions/0012-virtual-separation-monorepo-planes.md) drew the engine's plane boundaries
**virtually** — by package topology + import discipline — and explicitly deferred the physical split,
leaving `src/nexus/` as "a promise the topology makes but the code has not yet kept" (inert
`planner.py`/`deployer.py` placeholders).

Four iterations of autonomy growth (E1–E4, ADRs 0017–0020) then overloaded the **worker** plane. By
iteration 20, `src/executor/` conflated **three different concerns** in one package:

- **Orchestration + the FSM** — `main`, `run_executor` (per-ticket FSM), `run_batch` (E3), `finalize_*`,
  the financial breaker, the incident writer, the resume helpers.
- **Code generation + quality gates** — the six dev agents + `nodes/gates.py` (build/test/lint/SAST).
- **Infrastructure / CI-CD** — the `devops` agent + the E4 deploy-scaffolding.

Meanwhile the control plane `src/nexus/` owned only PO/SA/TPM + `nexus_runner.py`, and its `deployer.py`
was a 0-byte orphan. "executor" had become the orchestrator **and** the quality worker **and** the infra
generator at once — the namespace no longer encoded the architecture (the exact failure class ADR 0012
existed to prevent, recurred one scale up).

## Implemented Solutions

A pure lift-and-shift — history-preserving `git mv`, **zero** FSM/agent/gate/prompt/lint behaviour change.
`src/executor/` is removed; `src/shared/` is untouched (SSOT for all planes).

### Part A — `src/nexus/` becomes the real control plane (orchestration + FSM + planning)
- `executor/runner.py` → **[nexus/runner.py](../../../src/nexus/runner.py)** *minus* the deploy-scaffolding
  functions: `main`, `parse_args`, `RunConfig`, `PipelineHalt`, `run_executor`, `run_batch`,
  `prepare_ticket_run`, `bootstrap_session`, `finalize_transaction`/`finalize_pr`, and every FinOps /
  incident / breaker / guardrail / resume helper.
- PO/SA/TPM → **`src/nexus/agents/`** ([po](../../../src/nexus/agents/po.py),
  [sa](../../../src/nexus/agents/sa.py), [tpm](../../../src/nexus/agents/tpm.py)); `nexus_runner.py` +
  `state.py` stay. The inert `deployer.py` placeholder is **deleted** — the promise is now kept.

### Part B — `src/development/` is the worker plane (code generation + quality gates)
- The six dev agents → **`src/development/agents/`** (developer, qa, reviewer, arbiter, techlead, techwriter).
- `executor/nodes/gates.py` **flattened** → **[development/gates.py](../../../src/development/gates.py)**
  (build / test-compile / unit-test / **lint** (`run_lint_gate` + `classify_lint_findings`) / SAST +
  `run_format_pass`).

### Part C — `src/deployment/` is the infra plane (CI/CD scaffolding)
- The `devops` agent → **[deployment/agents/devops.py](../../../src/deployment/agents/devops.py)**.
- Deploy-scaffolding → **`src/deployment/provision/`**:
  [scaffold.py](../../../src/deployment/provision/scaffold.py) (`run_devops_scaffold` + `_env_ci_commands`
  + `_repo_has_source` + `_nexus_environment_ids` + `DEVOPS_MAX_RETRIES`) and
  [gates.py](../../../src/deployment/provision/gates.py) (the self-contained `run_devops_gate`).

### Part D — dependency graph + the one cycle it forces
Allowed direction: **`nexus → {development, deployment}`** (control orchestrates workers). E4 forces one
back-edge — `run_devops_scaffold` reuses the control-plane SSOTs (`bootstrap_session`,
`finalize_transaction`/`finalize_pr`, `_abort_with_incident`, FinOps writers) rather than forking them, so
`deployment → nexus` at module load. `run_batch` imports `run_devops_scaffold` **lazily, at call time**
(the same pattern `main()` uses for `nexus_runner`), breaking the import cycle while keeping the SSOT reuse.

### Companion — Edge Case C test (lint no-progress guard)
A dedicated test in `LintGateLoopTests` ([test_orchestrator.py](../../../tests/framework/test_orchestrator.py))
pins the step-3.6 no-progress break: byte-identical findings across two iterations break the fast-fail loop
on the **2nd** iteration — with `LINT_GATE_MAX_REROUTES` raised to 5 so a cap-driven stop would be 6 lint
calls; observing exactly 2 proves the *guard*, not the cap, fired, leaving the global budget intact.

### Docs & Claude operating-context synced to the release
- `docs/ARCHITECTURE.md` — component table + C4 worker/infra plane nodes repointed to the new paths.
- `.claude/rules/*` — `repo-module-map` (the largest rewrite), `pipeline-fsm-loops`,
  `deploy-scaffolding-and-ci-parity`, `agent-contracts`, `agent-provider-model-map`,
  `agent-role-registration`, `config-constant-convention`, `qa-sandbox-hardening`, `run-layout-and-cli`,
  `subprocess-and-external-call-safety` — path-scope frontmatter globs + body prose repointed.
- `.claude/skills/{agent-role-scaffold,docs-sync}/SKILL.md` + `CLAUDE.md` — entrypoint/role paths repointed.

## Metrics / Logs Analysis

- **Diff footprint** (`v0.20.0` merge `73722fc` → code commit `f99c375`): **33 files, 305 insertions / 228
  deletions**, every move a history-preserving rename. Heaviest: `runner.py` → `nexus/runner.py` (−142,
  deploy-scaffolding extracted), `development/gates.py` (−42, `run_devops_gate` extracted), the new
  `deployment/provision/scaffold.py` (+147) + `gates.py` (+48), `test_orchestrator.py` (+48, Edge Case C +
  the two `run_devops_scaffold` lazy-patch targets), `test_gates.py` (+/−66, patch-target prefix swap).
- **Test suite:** **407** tests green via WSL (406 → 407, **+1** Edge Case C). Bandit clean
  (`bandit -r src/`, no issues; 28 `# nosec` preserved across the moves).
- **Import-cycle guard.** A 3-plane import smoke test (`import main` + every plane's public symbols, incl.
  `src.deployment.provision.scaffold`) passes — confirming the lazy-import seam breaks the
  `deployment → nexus` cycle with no top-level circular import.

> Validate locally via WSL:
> `wsl -e bash -lc "cd /mnt/c/code/async-agentic-sdlc && source venv/bin/activate && GEMINI_API_KEY=test-key python3 -m unittest discover -s tests"`
