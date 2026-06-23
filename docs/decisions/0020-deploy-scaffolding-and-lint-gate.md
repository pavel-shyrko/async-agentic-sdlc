# 0020 — Deployability Closure: DevOps Deploy-Scaffolding (E4) + the Engine Lint Gate (CI-Parity SSOT)

## Status

Accepted (extends [0012](0012-virtual-separation-monorepo-planes.md) plane/import discipline,
[0011](0011-secure-sandbox-and-finops-telemetry.md) sandboxed gates,
[0018](0018-auto-merge-pr-loop-closure.md) `forge` PR loop closure,
[0019](0019-cyclical-multi-ticket-orchestration.md) `run_batch` terminal phase)

## Context

After E3 (ADR 0019) a single `--idea … --auto-execute` invocation drives **every** ticket to `main` — but
the merged application is **not deployable**: there is no `Dockerfile`, no CI/CD workflow, and the sandbox
is verification-only (no `run`/`serve`/`deploy` command). The autonomy loop produced working code that
still needed a human to ship it.

The first live attempt to close that gap exposed a **second**, deeper gap. A DevOps agent generated a
GitHub Actions workflow that ran a strict `ruff check src/ tests/`, and the very first run reddened on
`F841 Local variable 'mock_stdout' is assigned to but never used` — in a QA-generated test that had passed
**every** engine gate. The cause was a tooling-strictness mismatch: the engine's python cleanup pass is
`ruff check --fix --exit-zero` (autofix-only, never-fail), `F841` is an *unsafe* fix ruff won't auto-apply,
and `--exit-zero` swallowed the residual — so a finding the engine deliberately tolerated reddened a CI
that was stricter than anything the code had been validated against. **Engine-green did not imply
CI-green.** A registration boundary bug surfaced alongside it: the `instructor` Google-GenAI path hard-rejects
Jinja markers (`{{ }}`/`{% %}`) in a *system* message, and the DevOps prompt necessarily teaches GitHub
Actions `${{ secrets.* }}` / `${{ vars.* }}` expression syntax, so every structured DevOps call crashed
deterministically with a `ValueError` before any model output.

Both gaps are facets of one goal — **make the finished app genuinely deployable, with a CI that is green by
construction** — so they are recorded together.

## Decision

### Part A — E4: DevOps deploy-scaffolding as a post-batch terminal phase
- **A `devops` agent** (`prompts/system/devops.md` + three archetype skills `prompts/skills/devops_{rest_api,crud_app,cli_tool}.md`; `src/executor/agents/devops.py` `run_devops_node`) classifies the finished app's archetype and emits structured `DevOpsManifests` (`src/shared/core/models.py`: `archetype ∈ {rest_api,crud_app,cli_tool}`, `dockerfile_content`, `workflow_content`, `env_scaffold_content`). A **web service** gets a multi-stage non-root `Dockerfile` + a Cloud Run deploy workflow; a **CLI/library** gets **no Dockerfile and no Cloud Run step** — a build/release matrix workflow instead. Auth is **Workload Identity Federation**, never embedded keys (org-provisioned secrets `GCP_WIF_PROVIDER`/`GCP_SERVICE_ACCOUNT` + variables `GCP_PROJECT_ID`/`GCP_REGION`/`GCP_REGISTRY_NAME`; see `docs/guides/devops_setup.md`).
- **`run_devops_scaffold(...)`** (`src/executor/runner.py`) runs **once, after `run_batch` merges every ticket**, behind the opt-in **`--scaffold-deploy`** flag. It allocates a `NNN_devops_scaffold_…` run dir, clones the completed base branch fresh onto **`chore/devops-scaffold`**, generates the manifests, **statically lints** them (`run_devops_gate` in `src/executor/nodes/gates.py` — host-side YAML well-formedness + Dockerfile `FROM`/`CMD` directives), self-heals exactly `DEVOPS_MAX_RETRIES` (default 1) times, then lands them through the **same E2 forge flow** tickets use (open → approve → squash-merge), never a raw push. An empty-state guard skips a sourceless clone.
- **`DEVOPS_MODEL`** + a `ROLE_MODELS["devops"]` entry register the role; the manifests persist on `GlobalPipelineContext.devops_manifests`.

### Part B — the engine lint gate + CI-parity SSOT
- **`lint_cmd` becomes a per-environment SSOT** (`src/shared/core/environments.py`): a verify-only style/lint command for each stack (python `ruff check --no-cache . && ruff format --check .`; go `go vet ./... && test -z "$(gofmt -l .)"`; dotnet `dotnet format --verify-no-changes`; node `npx --no-install eslint .`). The paired `format_cmd` autofix is strengthened to apply everything `lint_cmd` verifies (python gains `ruff format`), so only genuinely-unfixable findings reach an agent.
- **A HARD lint gate** (`run_lint_gate` + `classify_lint_findings` in `src/executor/nodes/gates.py`) runs inside the FSM cycle as **step 3.6** (after the QA test-compile gate, before the parallel runtime gates). A residual finding fast-fail-reroutes to the offending isolated channel — **production findings → Developer, test findings → QA** (classified by the existing `is_test_file` SSOT, handling both `path:line:col` and bare-path `gofmt -l` output) — bounded by `LINT_GATE_MAX_REROUTES` (env `PIPELINE_LINT_MAX_REROUTES`, default 2) with a no-progress break. `lint_success` folds into `all_gates_passed`; a persistent finding rides the budgeted cycle, with the classified findings re-applied to the channels after the (lint-blind) Reviewer routes. It is deliberately **excluded from the deadlock guard** (a lint nit is always agent-fixable, never an environment misconfiguration), avoiding a protected Reviewer-prompt change.
- **CI-parity coupling.** `run_devops_scaffold` resolves the env's exact `build_cmd`/`test_cmd`/`lint_cmd` and feeds them to the DevOps prompt, which is instructed to run **those verbatim** and never invent a stricter linter/formatter/type-checker. The engine's lint gate and the generated CI now run the *same* command — **engine-green ⇒ CI-green by construction**.

### Part C — the structured-call boundary fix (enabling A)
- **`run_structured_llm` relocates any Jinja-marker-bearing system message into a user turn** (`src/shared/utils/llm.py`, `_relocate_jinja_system_messages`) before the instructor call. We never pass a Jinja `context`, so nothing is rendered; the relocation is a fast-path no-op for every marker-free role and only rewrites a config-teaching prompt (the DevOps `${{ }}`), letting the literal reach the model. Fixed at the shared seam, not by gutting the prompt.

## Consequences

- **Pros.** `--idea … --auto-execute --scaffold-deploy` now goes idea → plan → all tickets merged → **deploy config generated, validated, and merged** — the loop closes through to a shippable app. The lint gate guarantees the merged code is genuinely lint-clean, so the DevOps-generated strict CI is green on the first push; the shared `lint_cmd` makes that a structural invariant rather than a hope. Archetype awareness prevents the category error of deploying a CLI to Cloud Run. The seam-level Jinja and prod/test-channel handling reuse existing SSOTs (`is_test_file`, the forge flow, `bootstrap_session`/`finalize_pr` branch overrides) so E2/E3 paths stay byte-identical.
- **Cons / open questions.** A stubborn lint finding now consumes functional-retry budget (and, for production formatting, a Developer reroute — the dominant token cost) before it can hard-halt; the financial breaker still bounds it, but it is real spend. The node lint gate is conservative — it no-ops when a project ships no eslint config (so a never-configured project is not hard-failed), and **mypy/type-checking is deferred** (config/stub-heavy). The deploy provider is **hard-wired to GCP/Cloud Run/WIF** for the MVP; the engine only *generates and merges* config — the actual deploy runs in the user's Actions, and the org WIF setup is a one-time manual prerequisite. Mechanisms (b) build+push image and (c) live cloud deploy remain out of scope.

> Validated: **406** unit tests green via WSL (388 → 406, +18), `bandit -r src/` clean. The original failing
> CLI run (`json-to-csv-python`) reproduced the F841-red CI; the lint gate reroutes that class to QA and the
> shared `lint_cmd` keeps the generated workflow green. Footprint `v0.19.0` → HEAD: 20 files, +1489/−22.
> Archive: [iteration_20](../releases/iteration_20/iteration_20_README.md).
