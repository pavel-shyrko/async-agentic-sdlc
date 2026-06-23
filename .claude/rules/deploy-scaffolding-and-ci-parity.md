---
paths:
  - "src/executor/agents/devops.py"
  - "prompts/system/devops.md"
  - "prompts/skills/devops_*.md"
  - "src/shared/core/environments.py"
  - "src/executor/nodes/gates.py"
  - "src/executor/runner.py"
---

# DevOps deploy-scaffolding & the `lint_cmd` CI-parity SSOT

The engine makes a finished, merged application **deployable** (E4, `--scaffold-deploy`) by generating and
merging its CI/CD config, and keeps that generated CI **green by construction** via a per-environment lint
SSOT (ADR [0020](../../docs/decisions/0020-deploy-scaffolding-and-lint-gate.md)). The first live E4 run
reddened a generated `ruff check` CI on an `F841` finding that had passed **every** engine gate — because
the engine's cleanup was lenient (`ruff check --fix --exit-zero`) while the generated CI was strict. The
invariants below prevent that class of failure (and the category error of deploying a CLI to Cloud Run).
Uphold them when you touch the `devops` agent/prompt/skills, the `environments.py` commands, or the
lint/deploy gates. SSOTs: `run_devops_scaffold` / `_env_ci_commands` (`runner.py`), `run_lint_gate` /
`classify_lint_findings` / `run_devops_gate` (`gates.py`), `lint_cmd`/`build_cmd`/`test_cmd`
(`environments.py`).

## 1. Classify the application archetype FIRST, then branch
A **web service** (REST API / CRUD, listens on a port) → a multi-stage non-root `Dockerfile` + a Cloud Run
deploy workflow. A **CLI tool / library** → **NO Dockerfile and NO Cloud Run step** (`dockerfile_content`
is null) + a build/release matrix workflow instead.

**Why:** deploying a CLI to a serverless container is a semantic error — a CLI has no long-running server to
serve. The branch is encoded in the `devops.md` system prompt AND the archetype skills
(`devops_{rest_api,crud_app,cli_tool}.md`, routed by `triggers:` — see [[skill-routing-frontmatter]]); the
chosen class is recorded in `DevOpsManifests.archetype`.

**How to apply:** keep the archetype branch in the prompt itself, not only the skills (a skill miss must
still produce a correct shape). Never add a Cloud Run / container step on the CLI path.

## 2. Credentials are Workload Identity Federation — never embedded
The deploy workflow authenticates to GCP via **WIF** (`google-github-actions/auth` →
`workload_identity_provider` + `service_account`), referencing the org-provisioned repository config — never
an inlined key/token/password. Secrets (`${{ secrets.* }}`): `GCP_WIF_PROVIDER`, `GCP_SERVICE_ACCOUNT`.
Variables (`${{ vars.* }}`): `GCP_PROJECT_ID`, `GCP_REGION`, `GCP_REGISTRY_NAME`.

**Why:** the engine **never holds cloud credentials** — it only generates + merges config; the actual deploy
runs in the *user's* Actions on the next push, against their one-time org setup (see
[docs/guides/devops_setup.md](../../docs/guides/devops_setup.md)). The secrets-vs-variables split is the
provisioned contract — get it wrong and the workflow can't resolve.

## 3. CI-parity: the generated CI runs the env's EXACT commands — `engine-green ⇒ CI-green`
The generated CI's build/test/lint steps MUST run the environment's exact `build_cmd` / `test_cmd` /
`lint_cmd` (fed to the DevOps prompt by `_env_ci_commands`) — **verbatim**, and MUST NOT invent a stricter
linter/formatter/type-checker (a bare `ruff check`, `mypy`, `eslint`, … the project was never validated
against). The engine's HARD lint gate (`run_lint_gate`, FSM step 3.6) runs the **same** `lint_cmd`, so a
clean engine run guarantees a clean CI run.

**Why:** a CI stricter than the gates the code passed is **red by construction** — the exact bug ADR 0020
fixed. `lint_cmd` is the single SSOT both sides share.

**How to apply:** `lint_cmd` is **verify-only**; the paired `format_cmd` must **auto-apply everything
`lint_cmd` verifies** (e.g. python `format_cmd` runs `ruff format` so `lint_cmd`'s `ruff format --check`
passes), so only genuinely-unfixable residue (an F841-class finding) ever reaches an agent. If you add a
new check to `lint_cmd`, back it with a `format_cmd` autofix in the *same* commit, or you reintroduce the
red-CI loop. A lint finding routes prod→Developer / test→QA via `classify_lint_findings`; it is a HARD gate
(`lint_success` ∈ `all_gates_passed`) but is **excluded from the deadlock guard** — see [[pipeline-fsm-loops]].

## 4. Deploy-scaffolding is once-after-batch and lands via the forge flow
`run_devops_scaffold` runs **once**, after `run_batch` has merged every ticket — never per-ticket. It clones
the completed base branch onto **`chore/devops-scaffold`**, statically lints the manifests (`run_devops_gate`,
host-side YAML + Dockerfile directives, `DEVOPS_MAX_RETRIES` self-heal), and lands them through the **same
E2 forge flow** (open → approve → squash-merge via `finalize_pr`) — **never a raw `git push origin main`**.
An empty-state guard skips a sourceless clone.

**Why:** scaffolding an incomplete app is wrong (a mid-batch halt `sys.exit(1)`s before this runs), and a raw
push would bypass branch protection + the audited PR trail every ticket uses. The merged application code is
untouched on any deploy-phase failure (a persistent gate failure writes an incident in the
`NNN_devops_scaffold_…` run dir).

Related: [[repo-module-map]] (where the symbols live), [[pipeline-fsm-loops]] (the step-3.6 lint loop +
the post-batch devops phase), [[agent-provider-model-map]] (the `devops` Gemini role),
[[config-constant-convention]] (`LINT_GATE_MAX_REROUTES` / `DEVOPS_MAX_RETRIES`),
[[skill-routing-frontmatter]] (the archetype skills), [[run-layout-and-cli]] (`--scaffold-deploy` + the run dir),
[[subprocess-and-external-call-safety]] (the DevOps prompt's `${{ }}` → the Jinja relocation seam).
