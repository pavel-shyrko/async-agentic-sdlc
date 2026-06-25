---
paths:
  - "src/deployment/agents/devops.py"
  - "prompts/system/devops.md"
  - "prompts/skills/devops_*.md"
  - "prompts/skills/deploy_*.md"
  - "src/shared/core/environments.py"
  - "src/development/gates.py"
  - "src/deployment/provision/gates.py"
  - "src/deployment/provision/scaffold.py"
  - "src/nexus/runner.py"
---

# DevOps deploy-scaffolding & the `lint_cmd` CI-parity SSOT

The engine makes a finished, merged application **deployable** (E4, `--scaffold-deploy`) by generating and
merging its CI/CD config, and keeps that generated CI **green by construction** via a per-environment lint
SSOT (ADR [0020](../../docs/decisions/0020-deploy-scaffolding-and-lint-gate.md)). The first live E4 run
reddened a generated `ruff check` CI on an `F841` finding that had passed **every** engine gate — because
the engine's cleanup was lenient (`ruff check --fix --exit-zero`) while the generated CI was strict. The
invariants below prevent that class of failure (and the category error of deploying a CLI to Cloud Run).
Uphold them when you touch the `devops` agent/prompt/skills, the `environments.py` commands, or the
lint/deploy gates. SSOTs: `run_devops_scaffold` / `_env_ci_commands` (`deployment/provision/scaffold.py`),
`run_lint_gate` / `classify_lint_findings` (`development/gates.py`), `run_devops_gate`
(`deployment/provision/gates.py`), `lint_cmd`/`build_cmd`/`test_cmd` (`environments.py`).

## 1. Classify the application archetype FIRST, then branch
A **web service** (REST API / CRUD, listens on a port) → a multi-stage non-root `Dockerfile` + a Cloud Run
deploy workflow. A **CLI tool / library** → **NO Dockerfile and NO Cloud Run step** (`dockerfile_content`
is null) + a build/release matrix workflow instead.

**Why:** deploying a CLI to a serverless container is a semantic error — a CLI has no long-running server to
serve. The branch is encoded in the `devops.md` system prompt AND the archetype skills
(`devops_{rest_api,crud_app,cli_tool}.md`); the chosen class is recorded in `DevOpsManifests.archetype`.

**The README-URL step updates IN PLACE because the Technical Writer pre-seeds the markers.** The platform
skills' post-deploy/post-release step injects the live URL between `<!-- DEPLOYMENT_URL_START/END -->` /
`<!-- RELEASE_URL_START/END -->` markers (appending a new section only if they are absent). Those markers are
pre-seeded into `README.md` by the **Technical Writer** (the `README_SCAFFOLD` `## Deployment` section,
`src/shared/core/prompts.py`), and the techwriter prompt preserves the marker-block contents verbatim across
its per-ticket rewrites — so the URL the workflow commits survives the next ticket's README regeneration. See
[[agent-contracts]] (the TechWriter `DocumentationUpdate` contract).

**The README-URL step pushes with the `HEAD:<default-branch>` refspec, NEVER a bare `git push`.** The
generated *deployed* workflow runs in the user's Actions on a workspace `actions/checkout` leaves in
**detached HEAD** (it checks out `github.sha`, not a branch — and the tag-gated release run has no branch at
all), so a bare `git push` dies with `fatal: You are not currently on a branch`. Both platform skills
(`deploy_{gcp,github_release}.md`) therefore commit and push with `git push origin
HEAD:"${{ github.event.repository.default_branch }}"` — the refspec form sends the detached-HEAD commit
straight to the default-branch ref (resolved from the repo context, never a hardcoded `main`). The commit
message carries `[skip ci]` so the push does not re-trigger the workflow. Only `contents: write` is needed
(no PR, no `pull-requests:` scope). **Branch protection is handled out-of-band:** a protected default branch
rejects this push unless the `github-actions` app is on the branch rule's **"Allow bypass"** list — a
one-time per-org/repo grant documented in [docs/guides/devops_setup.md](../../docs/guides/devops_setup.md).
(This is deliberately distinct from the engine's own E4 scaffold landing in §4, which is an *audited PR* via
host-side `finalize_pr`: that runs once per build under the engine's own forge creds, whereas this cosmetic
URL stamp runs inside the user's deployed workflow where no second reviewer identity exists.) Pinned by
`test_deploy_platform_skills_push_readme_via_head_refspec_not_bare_push`.

**App SHAPE vs deploy TARGET — keep them in separate skills.** The archetype skills define the app's *shape*
(container/server vs CLI artifact) ONLY; the **platform skills** (`prompts/skills/deploy_{gcp,github_release}.md`)
own the *deploy mechanics* (WIF auth, image build/push, the Cloud Run deploy step, the public-invoker grant,
the README-URL step / GitHub Release publish). The DevOps node force-loads BOTH sets — archetype skills +
the platform skills named by `SUPPORTED_DEPLOY_TARGETS[*].skill` (via `deploy_target_skills()`), assembled in
`_archetype_guidance()`. Adding a future cloud is ONE registry entry + one `deploy_<cloud>.md`, no code edit.
Do NOT re-tangle Cloud-Run/WIF mechanics back into an archetype skill.

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

**The generated release workflow is tag-gated — E6 `--release` is what trips it (ADR 0023).** The DevOps
agent emits a workflow whose publish/release job triggers on `tags: ['v*']` (the CLI archetype gates it with
`if: startsWith(github.ref, 'refs/tags/v')`), so a merge to `main` runs tests but **skips** release. The
separate **`--release`** flag (E6) makes `run_batch`'s `finalize_release` push that `v*` tag as the build's
final step, tripping this workflow — **decoupled** from `--scaffold-deploy` (gated on `cfg.release` alone).
Keep the workflow tag-gated; do NOT make the release job fire on a plain push to `main`, or every merge would
publish. See [[run-layout-and-cli]] (`--release`) and [[pipeline-fsm-loops]] (the release terminal phase).

**E5 budget (ADR 0022):** `run_batch` threads the *remaining* application budget into
`run_devops_scaffold(budget_usd_ceiling=…)`, and the deploy phase enforces it via
`enforce_financial_circuit_breaker(ctx, budget_usd)` **after every DevOps generation** — including inside the
`DEVOPS_MAX_RETRIES` self-heal loop — so an exhaustion mid-generation halts correctly. It also receives the
`app_telemetry` accumulator by reference and merges its spend into it in its **own `finally`**, so even a
budget `PipelineHalt` mid-self-heal still folds the partial DevOps spend into the application total before the
batch's `finally` writes `app_finops_report.json`. See [[finops-app-budget]].

## 5. Deployment targets are a registry; web services are publicly invocable by default
(The registry + the reachability/isolation gate + the README-URL publish below are ADR
[0026](../../docs/decisions/0026-deploy-target-registry-and-reachability-gates.md), extending ADR 0020.)
`SUPPORTED_DEPLOY_TARGETS` (`environments.py`) is the SSOT for WHERE an app deploys — mirroring
`SUPPORTED_ENVIRONMENTS` (the WHAT/runtime SSOT). Each entry carries `archetypes` (which app archetypes it
serves), `skill` (its platform skill), `runtime_constraints` (the contract the APP CODE must satisfy — bind
`$PORT`/`0.0.0.0`, **boot with zero required configuration**, statelessness, a health endpoint), and an
optional `requires_public_invoker` flag. The SA selects a target (injected awareness list
`{injected_supported_deploy_targets_list}`, like the platform list) and records it in the Blueprint's
`## Deployment Target`; the TPM propagates the runtime constraints into the relevant tickets'
architectural-constraints; the building agents satisfy them (zero-config boot is also a global
`engineering_guide` rule + a TechLead contract HARD gate). A deploy target is a *deployment classification*,
NOT a programming language — no per-language branching here (honors [[engine-language-agnostic]]).

**Public invocation (the 403 class).** A target with `requires_public_invoker: True` (Cloud Run) deploys a
public-facing service: its workflow MUST grant unauthenticated invocation, or the live service rejects every
anonymous request with **HTTP 403**. This is enforced two ways: the `deploy_gcp` platform skill instructs
`flags: '--allow-unauthenticated'` PLUS an explicit `allUsers` → `roles/run.invoker` binding, AND
`run_devops_gate(repo_dir, archetype)` deterministically asserts the generated workflow grants public
invocation — a miss flows into the existing `DEVOPS_MAX_RETRIES` self-heal loop. **The grant lives in IAM,
outside the Knative service spec**, so the gate is **deploy-mode-aware**: in *image-deploy* mode either
`--allow-unauthenticated` OR an `allUsers`→`run.invoker` binding satisfies it; but when the workflow deploys a
`service.yaml` manifest instead (`gcloud run services replace`, or a `metadata:` input on `deploy-cloudrun`),
the flag is incompatible and silently dropped, so ONLY the explicit IAM binding counts — the gate demands it
there. (This was a live 403: a generated `metadata:`-mode workflow whose `--allow-unauthenticated` was inert.)
The gate is archetype-aware: `archetype=None` (or a target without the flag) skips the check, so CLI runs are
unaffected.

**Service-name collision guard (the overwrite class).** A managed service is keyed by `(name, region,
project)`, so a **hardcoded** service name lets one app's deploy silently overwrite another's (a new revision
takes over the live URL) — a real risk in a multi-app factory. The `deploy_gcp` skill forbids static names and
requires deriving the name from the repository context (`${{ github.event.repository.name }}`, optionally
branch-suffixed for non-default-branch deploys); `run_devops_gate` deterministically asserts the workflow
references `github.event.repository.name` (or `github.repository`) for a `requires_public_invoker` target.

**Why a gate, not just the prompt:** prompt adherence is probabilistic; the gate makes reachability +
isolation green-by-construction, the same philosophy as the `lint_cmd` CI-parity SSOT above.

Related: [[repo-module-map]] (where the symbols live), [[pipeline-fsm-loops]] (the step-3.6 lint loop +
the post-batch devops phase), [[agent-provider-model-map]] (the `devops` Gemini role),
[[config-constant-convention]] (`LINT_GATE_MAX_REROUTES` / `DEVOPS_MAX_RETRIES`),
[[skill-routing-frontmatter]] (the archetype skills), [[run-layout-and-cli]] (`--scaffold-deploy` + the run dir),
[[subprocess-and-external-call-safety]] (the DevOps prompt's `${{ }}` → the Jinja relocation seam).
