# Iteration 20 — Deployability Closure: DevOps Deploy-Scaffolding (E4) + the Engine Lint Gate

> ADR: [0020-deploy-scaffolding-and-lint-gate](../../decisions/0020-deploy-scaffolding-and-lint-gate.md) ·
> CHANGELOG: [v0.20.0](../../../CHANGELOG.md) · Practicum: [PRACTICUM.md](../../../PRACTICUM.md)

## Problem Statement

After E3 (ADR 0019), a single `--idea … --auto-execute` invocation drove **every** ticket to `main` — but
the result was a working app that still **could not be shipped**: no `Dockerfile`, no CI/CD workflow, and a
verification-only sandbox. Closing that last gap (E4) immediately surfaced a second, subtler one.

- **No deploy artifacts.** The autonomy loop ended at a green `main`, then a human wrote the container +
  pipeline by hand. E4 had to generate them autonomously — archetype-aware (a CLI must not be deployed to
  Cloud Run), credential-free (WIF, never embedded keys), and landed through the same audited PR flow.
- **Engine-green did not imply CI-green.** The first live E4 run reddened on `ruff check` — `F841` in a
  QA-generated test that had passed every engine gate. The engine's cleanup was lenient
  (`ruff check --fix --exit-zero`), so an unfixable finding survived; the generated CI ran a *stricter*
  `ruff check`. A CI stricter than the gates the code passed is red by construction.
- **A registration boundary crash.** The DevOps prompt teaches GitHub Actions `${{ secrets.* }}` syntax, but
  `instructor`'s Google-GenAI path hard-rejects Jinja markers (`{{ }}`) in a *system* message — every
  structured DevOps call `ValueError`-crashed deterministically (3 identical retries) before producing
  output.

All three are facets of one goal: **make the finished app genuinely deployable, with a green CI.**

## Implemented Solutions

### Part A — E4: DevOps deploy-scaffolding (post-batch terminal phase)
- **`devops` agent** ([devops.py](../../../src/executor/agents/devops.py) `run_devops_node`,
  [prompts/system/devops.md](../../../prompts/system/devops.md) + three archetype skills) emits structured
  `DevOpsManifests` ([models.py](../../../src/shared/core/models.py)): a multi-stage non-root `Dockerfile` +
  Cloud Run workflow for a **web service**, or **no Dockerfile / a build-release matrix** for a
  **CLI/library**. Auth is **Workload Identity Federation** (org secrets/variables; see
  [docs/guides/devops_setup.md](../../guides/devops_setup.md)).
- **`run_devops_scaffold`** ([runner.py](../../../src/executor/runner.py)) runs **once, after `run_batch`
  merges every ticket**, behind opt-in **`--scaffold-deploy`**: clones the base branch fresh onto
  `chore/devops-scaffold`, generates → **statically lints** (`run_devops_gate`) → self-heals
  `DEVOPS_MAX_RETRIES` (default 1) → lands via the **same E2 forge flow** (open → approve → squash-merge),
  never a raw push. An empty-state guard skips a sourceless clone.

### Part B — the engine lint gate + CI-parity SSOT (the "engine-green ⇒ CI-green" fix)
- **`lint_cmd` per environment** ([environments.py](../../../src/shared/core/environments.py)) — a verify-only
  style/lint command (python `ruff check && ruff format --check`, go `go vet` + `gofmt -l`, dotnet
  `dotnet format --verify-no-changes`, node `eslint`); `format_cmd` autofix strengthened so only
  genuinely-unfixable findings reach an agent.
- **HARD lint gate as FSM step 3.6** (`run_lint_gate` + `classify_lint_findings` in
  [gates.py](../../../src/executor/nodes/gates.py)): a residual finding fast-fail-reroutes
  **prod → Developer, test → QA** (no functional budget), bounded by `LINT_GATE_MAX_REROUTES`
  (env `PIPELINE_LINT_MAX_REROUTES`, default 2) with a no-progress break; `lint_success` folds into
  `all_gates_passed`, excluded from the deadlock guard.
- **CI-parity coupling.** `run_devops_scaffold` feeds the env's exact `build_cmd`/`test_cmd`/`lint_cmd` to
  the DevOps prompt, which must run **those verbatim** — no invented stricter linters. Engine and CI run the
  same command.

### Part C — the structured-call boundary fix
- **`_relocate_jinja_system_messages`** ([llm.py](../../../src/shared/utils/llm.py)) demotes any
  Jinja-marker-bearing system message to a user turn before the instructor call — a fast-path no-op for every
  marker-free role; only the config-teaching DevOps prompt is rewritten, so its literal `${{ }}` reaches the
  model.

### Docs & Claude operating-context synced to the release
- `docs/ARCHITECTURE.md` — the `devops` role + the post-batch deploy-scaffolding terminal phase + the
  step-3.6 lint gate in the executor sequence / component table.
- `.claude/rules/{repo-module-map,pipeline-fsm-loops,run-layout-and-cli,config-constant-convention,agent-provider-model-map}.md`
  + the `analyze-run` skill (new root-cause classes: lint-gate / CI-strictness mismatch and the GenAI Jinja
  system-message crash).
- `docs/BACKLOG.md` — **E4 → DONE**; new epic for the application-wide lint/quality bar follow-ups
  (mypy/type-checking, node eslint provisioning).

## Metrics / Logs Analysis

- **Diff footprint** (`v0.19.0` merge `e197e1a` → HEAD `b650cbc`): **20 files, 1489 insertions / 22
  deletions**. Engine: `runner.py` (+248 — `--scaffold-deploy`, `run_devops_scaffold`, the step-3.6 lint
  loop, `LINT_GATE_MAX_REROUTES`, `_LINT_FEEDBACK_PREAMBLE`, `_env_ci_commands`), `gates.py` (+131 —
  `run_devops_gate`, `run_lint_gate`, `classify_lint_findings`), `environments.py` (+41 — `lint_cmd` ×4 +
  `format_cmd`), `models.py` (+25 — `DevOpsManifests`), `llm.py` (+29 — Jinja relocation), `config.py` (+2 —
  `DEVOPS_MODEL`/`ROLE_MODELS`), the `devops` agent (+103). Prompts: `devops.md` + 3 skills (+95). Tests:
  `test_devops.py` (+229), `test_orchestrator.py` (+182), `test_gates.py` (+125), `test_prompts.py` (+51),
  `test_models.py` (+32), `test_pipeline_e2e.py` (+14). Docs: `devops_setup.md` (+201).
- **Test suite:** **406** tests green via WSL (388 → 406, **+18**). Bandit clean (`bandit -r src/`, no issues).
- **Reproduction → fix.** The original failing run (`Cyberthon-2026-Token-Burners/json-to-csv-python`,
  run `006/007_devops_scaffold_…`) classified `cli_tool`, emitted a build-release workflow with **no
  Dockerfile**, merged PR #5 — then its CI reddened on `ruff check` `F841`. Root cause: engine `format_cmd`
  was lenient (`--fix --exit-zero`) while the generated CI was strict. The lint gate now reroutes that class
  to QA and the shared `lint_cmd` keeps the generated workflow green; the GenAI Jinja crash (which initially
  blocked E4 entirely) was fixed at the `llm.py` seam.

> Validate locally via WSL:
> `wsl -e bash -lc "cd /mnt/c/code/async-agentic-sdlc && source venv/bin/activate && GEMINI_API_KEY=test-key python3 -m unittest discover -s tests"`
