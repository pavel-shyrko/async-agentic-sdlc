# Backlog

Two parts:

- **Part I — Capability Roadmap (Epics `E1`–`E7`)**: the forward-looking work to close the autonomy loop
  (idea → working, merged code in `main` → deployable). Larger than a single fix; each has its own
  Goal / Current state / Design / Dependencies / Risks / Acceptance.
- **Part II — Defects & Refinements (`#4`–`#28`)**: granular fixes surfaced across pipeline runs, grouped by
  theme. Resolved items have been removed — their fixes live in the code, tests, and `CHANGELOG.md`; only
  outstanding work remains. **Original item numbers are preserved** so existing cross-references (from
  `.claude/rules/*` and ADRs) stay valid. The `E#` epic namespace is deliberately separate from the `#NN`
  defect sequence.

> Last reviewed 2026-06-18: pruned items resolved by subsequent design changes — **#10** (zombie
> disposal: `target_modules` is now contract-scoped via `is_testable_source(files_to_modify)`, so a
> genuinely removed module is never regenerated and the disposal sticks) and **#13** (manifest
> documentation: the design was reversed — `developer.md` now *requires* a top-of-file justification
> comment on build manifests, so the guardrail flagging an uncommented manifest is correct behavior).
> Items #17–#24 added from the PO→Reviewer pipeline contract analysis. Items #25–#26 added from the
> Arbiter (ADR 0016) TASK-03 run analysis — the Arbiter's `developer`/`qa` routes are advisory, and a
> non-amending verdict grants no extra cycle budget.
>
> Updated 2026-06-19: added **Part I — Capability Roadmap** (`E1`–`E4`, closing the idea→main→deploy loop)
> and regrouped the defect items by theme (numbers unchanged).
>
> Updated 2026-06-22: **E1 shipped** (`--auto-execute`, v0.17.0 / ADR 0017) — next in the loop is **E2**.
> Updated 2026-06-22: **E2 + E3 shipped** (`--auto-merge` v0.18.0 / ADR 0018; cyclical multi-ticket
> orchestration via `--auto-execute` → all tickets to `main`, ADR 0019). New epic **E5** (application-wide
> FinOps budget) added from the E3 4-ticket validation run — the financial breaker is still per-ticket, so
> a batch can overspend `N×` the intended ceiling; the fix is one app budget threaded as the remaining
> limit into each cycle.
>
> Updated 2026-06-23: **E4 shipped** (`--scaffold-deploy` deploy-scaffolding via mechanism (a) generate
> CI/CD config, v0.20.0 / ADR 0020), together with a companion **engine lint gate** (`run_lint_gate`, FSM
> step 3.6) whose per-env `lint_cmd` is the SSOT the generated CI runs verbatim (engine-green ⇒ CI-green).
> New follow-ups noted under the lint-gate work: mypy/type-checking and node-eslint auto-provisioning.
> Added **#27** (Gemini billing-balance exhaustion: 403 billing errors retried silently with no actionable message; fix in `api_retry.py` + `config.py`).
> Added **#28** (per-role reasoning-effort/thinking routing for both providers — the second cost-tuning axis; surfaced from Cyberthone 2026 dimension-7 prep).
>
> Updated 2026-06-24: logged **E6** (autonomous release-tagging behind `--release`, nexus-owned decision +
> `forge.py` tag-push) — the first open capability epic since E1–E5 shipped; surfaced from the
> `json-to-csv-python` deploy run where the tag-gated `release` job was skipped on merge-to-`main`.
>
> Updated 2026-06-24: logged **E7** (distribute the factory itself as an installable CLI + factory
> self-release CI pipeline) — any user can `pip install git+<url>` and get a `tbf` binary; every `v*` tag
> on this repo triggers a GitHub Actions workflow that publishes a new GitHub Release.

---

# Part I — Capability Roadmap (Epics)

**North star:** an *idea in* → a *working, reviewed, merged application in `main`* → *deployable*, with the
engine driving the whole cycle autonomously. Today the engine is a **head + hands** split that stops
half-finished: **Nexus** (head) plans `Epic → Blueprint → TASK-*.md`, but the operator launches the
**Executor** (hands) by hand one ticket at a time, and verified work lands only on a `feat/ticket-<id>`
branch that is **never merged**.

**Dependency order (build in this sequence):**

```
E1 ✅ Nexus auto-dispatches Executor (one ticket)   — DONE (v0.17.0 / ADR 0017)
      └─► E2 ✅ Close the loop to main (auto-approved PR + merge)  — DONE (v0.18.0 / ADR 0018)
              └─► E3 ✅ Cyclical multi-ticket orchestration (all tasks, each building on the last)  — DONE (v0.19.0 / ADR 0019)
                      ├─► E4 ✅ DevOps deploy-scaffolding (--scaffold-deploy)  — DONE (v0.20.0 / ADR 0020)
                      │       └─► E6 ✅ Autonomous release-tagging (--release; nexus tags main → triggers the E4 workflow)  — DONE (v0.23.0 / ADR 0023)
                      └─► E5 ✅ Application-wide FinOps budget (one money ceiling, remaining threaded per ticket)  — DONE (v0.22.0 / ADR 0022)

E7 ⬜ Distribute the factory as an installable CLI + factory self-release CI pipeline   — OPEN
```

E3 depends on E2 for a hard structural reason (see E3): each ticket clones `main` **fresh**, so TASK-02 only
sees TASK-01 if TASK-01 has already been merged to `main`. E4 and E5 both build on E3's batch loop and are
independent of each other. E6 builds on E4 (a tag-triggered workflow must already exist on `main` for the
pushed tag to do anything) + E3's batch-completion point, and is independent of E5.

---

## E1. [✅ DONE — v0.17.0 / ADR 0017] Nexus auto-dispatches the Executor (single ticket)

> **Delivered** ([ADR 0017](decisions/0017-nexus-executor-auto-dispatch.md),
> [iteration 17](releases/iteration_17/iteration_17_README.md)): `--auto-execute` on the `--idea` path now
> plans then runs the Executor for the first ticket in one invocation. The inlined FSM body was extracted
> **verbatim** into `run_executor(cfg, run_dir, resume_checkpoint) -> bool` (not the originally-proposed
> `run_executor_fsm_loop`/`execute_one_ticket` split — a single callable proved sufficient), the shared
> ticket setup into `prepare_ticket_run(...)`, and task enumeration into
> `get_tasks_for_nexus_run(run_dir) -> list[str]` (ticket-id strings in checkpoint/TPM order, **not** the
> `list[dict]` first sketched). Dispatch lives in `main()`; Nexus never imports the executor (ADR 0012
> held). The dropped `--push` on `--idea` was fixed in passing. Validated end-to-end on
> `cli-python-json-csv` (plan 4 tickets → TASK-01 built/committed/pushed, $0.2249). **Remaining for the
> loop: E2 (merge to `main`) + E3 (iterate all tickets, non-exiting halts).**

**Goal:** after planning, the engine automatically runs the Executor for `TASK-01` — no manual second
command. (User-requested feature 1: "nexus запускал executor с задачей 1".)

**Current state:**
- The two planes are bridged only inside `main()` (resume routing by checkpoint `kind`,
  [runner.py:647-673](../src/nexus/runner.py#L647-L673)); neither plane invokes the other — the operator
  does, via a second `--run` invocation.
- The per-ticket Executor flow (bootstrap → FSM cycle → finalize) is **inlined inside `main()`**
  ([runner.py](../src/nexus/runner.py), roughly the `bootstrap_session` → while-loop → `finalize_transaction`
  span), **not** a callable function. `bootstrap_session` and `finalize_transaction` already are async/standalone.
- Tasks are enumerated as `NexusState.tasks` (`list[dict]` of `ticket_id/title/environment_id/description`)
  and materialized to `artifacts/TASK-*.md` ([nexus_runner.py](../src/nexus/nexus_runner.py)); the executor
  resolves a ticket file via `_resolve_ticket_file` from the latest Nexus run.

**Design (seam + approach):**
- **Refactor:** extract the inlined FSM loop into `run_executor_fsm_loop(ctx, cfg) -> bool` and wrap
  bootstrap+loop+finalize in `execute_one_ticket(project, ticket_id, projects, *, push, auto_merge) ->
  (run_dir, ok)`, reusing the already-standalone `bootstrap_session`/`finalize_transaction`.
- Add `get_tasks_for_nexus_run(run_dir) -> list[dict]` (read `NexusState.tasks` from the checkpoint, or scan
  `artifacts/TASK-*.md`).
- Add an opt-in flag (e.g. `--auto-execute`) on the `--idea` path. **Orchestrate from `runner.main()`** (or a
  thin new orchestration entry) — do **not** make the Nexus plane import the Executor plane (preserve the
  ADR 0012 plane discipline; the bridge stays in the worker/entry layer).

**Dependencies:** none — this is the refactor foundation for E2/E3.

**Risks / open questions:** the FSM loop is coupled to module-level constants (`MAX_FUNCTIONAL_RETRIES`,
reroute caps, budgets) and the ambient `log` re-anchored per run — these must move cleanly into the extracted
function without changing per-ticket checkpoint/resume semantics.

**Acceptance:** `--idea "…" --auto-execute` plans, then executes `TASK-01` end-to-end in one invocation; the
existing manual `--run` path is unchanged; unit tests mock the loop and assert dispatch + termination.

## E2. [✅ DONE — v0.18.0 / ADR 0018] Close the loop to `main` via an auto-approved PR

**Goal:** on a successful ticket, open a PR from `feat/ticket-<id>` into `base_branch` and **auto-approve +
merge** it, so verified work actually lands in `main`. (User-requested feature 2; chosen approach: **PR +
auto-approve + merge** — full-autonomy MVP, switchable to human-review later.)

**Current state:**
- `finalize_transaction` makes the atomic `feat(<ticket>): …` commit on `feat/ticket-<id>` and, with `--push`,
  runs `git push -u origin HEAD` — and stops ([runner.py:219-257](../src/nexus/runner.py#L219-L257)). The
  success block that calls it is [runner.py:1155-1163](../src/nexus/runner.py#L1155-L1163).
- `base_branch` is only a **diff anchor + fetch ref**, **never a merge target** (grep confirms; bootstrap
  fetches it for `git diff --cached <base>`).
- **PR/merge/`gh`/GitHub API = none today (greenfield).** `ctx.pr_description` (clean ticket text) and the
  `feat(<ticket>):` subject are available for the PR body/title. The PAT embedded in the repo URL authenticates
  the GitHub REST API; a separate `GITHUB_TOKEN` is cleaner (keeps the full credentialed URL out of logs).

**Design (seam + approach):**
- New step **after** `finalize_transaction` in the success block, behind a flag (e.g. `--auto-merge`).
- A **provider-agnostic** interface (`open_pr` / `approve_pr` / `merge_pr`) with a **GitHub-first** impl via
  `gh` or REST; squash-merge into `base_branch`; PR title from the commit subject, body from
  `ctx.pr_description` + a gate/FinOps summary. Auth via `GITHUB_TOKEN` (preferred) or the existing URL PAT.

**Dependencies:** E1 (or usable standalone via `--run … --auto-merge`).

**Risks / open questions (call out before building):**
- **Self-approval:** GitHub forbids a PR author approving their *own* PR — auto-approve likely needs a
  *separate reviewer token*, or branch-protection bypass / admin auto-merge. Decide the identity model.
- Branch-protection / required-status-checks interaction (the engine already ran the checks locally).
- **Idempotency on `--resume`** after a partial merge; relates to **#23** (abort leaves a dirty index) for
  clean resume hygiene.
- Provider lock-in: keep the interface generic so GitLab/Bitbucket can follow.

**Acceptance:** a successful ticket yields a merged PR on `base_branch`; a failed/halted ticket leaves no PR
or merge; re-running or resuming is idempotent (no duplicate PRs).

## E3. [✅ DONE — v0.19.0 / ADR 0019] Cyclical multi-ticket orchestration

> **Delivered** ([ADR 0019](decisions/0019-cyclical-multi-ticket-orchestration.md),
> [iteration 19](releases/iteration_19/iteration_19_README.md)): `--auto-execute` now drives the Executor
> over ALL planned tickets to `main` in TPM order via **`run_batch`** in `main()` (not the originally-sketched
> `execute_one_ticket(..., auto_merge=True)` — `run_batch` loops the existing `prepare_ticket_run` +
> `run_executor` directly). A catchable **`PipelineHalt`** replaced `_abort_with_incident`'s `sys.exit(1)` so a
> mid-batch halt records `failed` in the **`BatchState`** checkpoint (`reports/batch_state.json`) and stops
> cleanly; a bare `--resume <project>` re-enters the batch, skipping merged tickets. `--auto-execute` now
> implies `--auto-merge`. Validated end-to-end on `cli-python-json-csv` — 4 tickets → `main`, $1.862 total,
> zero incidents. **Remaining open question became its own epic: E5 (application-wide budget).**

**Goal:** Nexus drives the Executor over **all** generated tasks in order — `TASK-01 → merge → TASK-02 → …` —
so each ticket builds on the previously merged state, ending with the full app on `main`. (User-requested
feature 3: "nexus циклично по таскам запускал executor".)

**Current state:** each ticket runs in its **own** exec run dir and **clones `main` fresh** on a new
`feat/ticket-<id>` branch ([bootstrap_session](../src/nexus/runner.py#L165-L192)). There is no cross-ticket
state — TASK-02's clone does **not** contain TASK-01's work unless it has already merged to `main`.

**Design (seam + approach):** a batch loop over `get_tasks_for_nexus_run(...)` (from E1) calling
`execute_one_ticket(..., auto_merge=True)` in TPM order. **Correctness hinges on E2 merging to `main` before
the next ticket's fresh clone** — that is what makes the fresh-clone model compose into a coherent,
cumulative application. Add a **batch-level checkpoint** (which tickets are done) for resume, and an explicit,
tunable **failure policy** (default: stop the batch on the first unrecoverable halt, write the incident, and
let `--resume` continue from the failed ticket).

**Dependencies:** **E1 + E2** (hard).

**Risks / open questions:** a mid-batch halt strands later tickets (resume story must be solid); per-ticket
FinOps vs an application-wide budget (now its own epic **E5**); inter-ticket ordering/dependencies are
implicit via shared `main` (no explicit DAG between tickets today); ties to **#20** (env_id must propagate
cleanly per ticket) and **#26** (per-ticket retry budget).

**Acceptance:** `--idea "…"` with auto-execute + auto-merge drives every task to `main` in order; a halt stops
the batch cleanly with an incident, and `--resume` continues from the failed ticket without redoing merged
ones.

## E4. [✅ DONE — v0.20.0 / ADR 0020] DevOps deploy-scaffolding (`--scaffold-deploy`)

> **Delivered** ([ADR 0020](decisions/0020-deploy-scaffolding-and-lint-gate.md),
> [iteration 20](releases/iteration_20/iteration_20_README.md)): chosen mechanism **(a) generate CI/CD
> config**. A `devops` agent emits structured `DevOpsManifests` — archetype-aware (web service → multi-stage
> non-root `Dockerfile` + Cloud Run workflow; CLI/library → **no Dockerfile** + a build/release matrix),
> authenticated via **Workload Identity Federation** (org secrets/variables; see
> [docs/guides/devops_setup.md](guides/devops_setup.md)), never embedded keys. It runs **once after the batch**
> (`run_devops_scaffold`, behind opt-in `--scaffold-deploy`), static-lints the manifests (`run_devops_gate`,
> 1 self-heal retry), and lands them through the **same E2 forge flow** on `chore/devops-scaffold` — so
> **where in the loop** resolved to *once per completed application*, not per ticket. A companion **engine
> lint gate** (`run_lint_gate`, FSM step 3.6) makes the generated strict CI green by construction: the per-env
> `lint_cmd` is the SSOT both the gate and the generated workflow run. **Deferred:** mechanisms (b) build+push
> image / (c) live cloud deploy; mypy/type-checking and node-eslint auto-provisioning for the lint gate.

**Goal:** record the epic and its decision space; **do not pick the mechanism yet** (user choice:
"только зафиксировать scope" — needs refinement on *how and where* to deploy).

**Current state:**
- The **DevOps** node is named in the mission graph (README "Target Pipeline Graph") and
  [ADR 0000](decisions/0000-cloud-infra-fsm-research.md), but has **zero implementation**; the pipeline stops
  at QA/Reviewer.
- [environments.py](../src/shared/core/environments.py) has `build`/`test`/`setup`/`format` commands but
  **no `run`/`serve`/`package`/`deploy`** command. `docker_adapter.py` runs ephemeral, least-privilege
  *verification* sandboxes only — not a deployment target.
- [techwriter.py](../src/development/agents/techwriter.py) is the exact structural template for a success-path
  "finalizing" agent (runs once on success, before commit); adding a `devops` role follows the 8-point
  checklist in [agent-role-registration](../.claude/rules/agent-role-registration.md).

**Decision space to resolve when picked up** (recommended-but-deferred lean toward the lowest-risk first):
- **(a) Generate CI/CD config** — a `devops` agent emits a `Dockerfile` + GitHub Actions workflow
  (build/test/deploy) committed to the repo; the engine makes the app *deployable* and the platform performs
  the deploy. *Lowest infra/risk; recommended MVP.*
- **(b) Build + push a container image** to a registry (needs registry credentials).
- **(c) Live cloud deploy** to a real target (AWS/GCP/Azure/k8s) — needs target credentials + infra, and is
  irreversible/highest-risk.

Plus open sub-decisions: the new `devops` agent role (model/prompt/output-model/FSM wiring), new
`environments.py` deploy-command fields, credential/secret handling, and **where in the loop deploy runs**
(per merged ticket vs once per completed epic).

**Dependencies:** E3 (a coherent application on `main` to deploy).

**Acceptance:** epic captured with a clear decision matrix and the touch-points enumerated; **no
implementation** until the mechanism is chosen.

## E5. [✅ DONE — v0.22.0 / ADR 0022] Application-wide FinOps budget (one ceiling, remaining-budget threaded per ticket)

**Shipped:** a single money ceiling `PIPELINE_APP_BUDGET_USD` (or `--budget`) governs the whole build;
`run_batch` threads the remaining budget into each ticket and accumulates spend in `BatchState.app_telemetry`
(resume-safe + re-budgetable). Budget is **money-only** (the token ceiling was removed); reporting is now
per-role + per-plane + per-time (`app_finops_report.json`). The decision record below is retained as the
design rationale; see [ADR 0022](decisions/0022-application-wide-finops-budget.md).

**Goal:** a single budget governs the **whole application build** (idea → all tickets → `main`), not each
ticket in isolation. The operator sets one ceiling (e.g. `PIPELINE_APP_BUDGET_USD`); the engine spends it
across the batch, passing the **remaining unused budget as the limit into each next cycle/ticket**, and
halts the batch cleanly when the app budget is exhausted. (Surfaced by the E3 validation run: the cost of
an autonomous `--idea` run should be bounded for the *application*, which is what the operator actually
pays for — a per-ticket cap does not bound the thing being built.)

**Current state:**
- The financial circuit breaker (`enforce_financial_circuit_breaker`, [runner.py](../src/nexus/runner.py))
  gates each ticket's OWN `GlobalPipelineContext.telemetry` against the fixed `PIPELINE_BUDGET_USD` /
  `PIPELINE_BUDGET_TOKENS` ([config.py](../src/shared/core/config.py)) — a **per-ticket** ceiling read from
  module constants, not a parameter.
- E3's `run_batch` runs N tickets, each a fresh `run_executor` whose telemetry starts at zero; there is no
  cross-ticket spend accounting, so a batch can spend up to `N × PIPELINE_BUDGET_USD` before any single
  ticket trips. `BatchState` tracks `completed`/`failed` only — no `spent_*`.
- **Observed (E3 4-ticket validation, `cli-python-json-csv`):** $0.4202 + $0.4100 + $0.6450 + $0.3864 =
  **$1.862** total, yet each ticket measured only against its own $10 budget — the batch never saw a
  cumulative figure.

**Design (seam + approach):**
- New app-wide constants `PIPELINE_APP_BUDGET_USD` / `PIPELINE_APP_BUDGET_TOKENS` (env-overridable
  UPPER_CASE, [config-constant-convention](../.claude/rules/config-constant-convention.md)).
- Accumulate each finished ticket's `telemetry.total_cost_usd` / `total_tokens` into **`BatchState`** (new
  persisted `spent_usd` / `spent_tokens` fields, so `--resume` keeps the running total across restarts).
- Before dispatching the next ticket, compute `remaining = app_budget − spent` and **thread it into
  `run_executor` as that ticket's effective ceiling** — the breaker checks against the *remaining* app
  budget, not a fixed per-ticket constant. When `remaining` ≤ a floor, stop the batch cleanly (record a
  budget marker, write the batch state, exit 1) before spending more.
- This requires `enforce_financial_circuit_breaker` / `run_executor` to take the effective ceiling as a
  **parameter** rather than reading module constants — the core signature change of this epic.

**Dependencies:** **E3** (the batch loop + `BatchState`).

**Risks / open questions:**
- **Single-ticket paths** (`--run`, legacy direct) must still work — their "remaining" is just the full app
  budget (or the legacy per-ticket value); decide whether `PIPELINE_BUDGET_USD` survives as an inner
  per-ticket sub-cap or is subsumed by the threaded remaining-budget.
- **Starvation:** one expensive early ticket consumes the shared pool and can starve later tickets (by
  design, but maybe a per-ticket floor/reserve so the batch can't strand the tail).
- **Retry-ceiling interaction:** a ticket near the budget edge effectively gets fewer cycles — make the
  fail-fast legible in the incident.
- **Resume correctness:** `spent_*` must reload so the remaining budget is exact across a `--resume`.

**Acceptance:** one `PIPELINE_APP_BUDGET_USD` governs an entire `--idea --auto-execute` run; each ticket
runs against the remaining unused budget; the batch halts cleanly with an incident when the app budget is
exhausted, and `--resume` continues with the correct remaining total. A batch can no longer overspend `N×`
the intended ceiling.

## E6. [✅ DONE — v0.23.0 / ADR 0023] Autonomous release-tagging (`--release`) — close the loop to a published artifact

**Goal:** make the final step of the autonomy loop — cutting the release — agent-driven too. Behind an
opt-in `--release` flag, after a batch has merged every ticket (and optionally scaffolded deploy), the
engine resolves the next version and pushes a `v*` tag, which triggers the deploy/release workflow the
DevOps plane already generated. Turns "idea in → merged app on `main`" into "idea in → **released artifact
out**, zero human touches" — the last unautomated step (and the first open epic since E1–E5 all shipped).

**Current state:**
- The E4 deploy-scaffold generates a release workflow that is **tag-gated** (CLI archetype:
  `if: startsWith(github.ref, 'refs/tags/v')`, per `prompts/skills/devops_cli_tool.md` lines 13/15). A merge
  to `main` runs tests but **skips** the release job — observed in the `write-a-python-cli-utility-that-takes-a`
  run (run `009` scaffold; the `release` job rendered "This job was skipped"). Today the operator must push a
  `v*` tag by hand.
- No part of the engine pushes tags; `src/shared/utils/forge.py` covers PR open/approve/merge only.

**Design (decision vs mechanism — placement settled, see also [plane-import-direction](../.claude/rules/plane-import-direction.md)):**
- **nexus owns the decision + trigger.** `run_batch` (the terminal orchestrator that knows the whole build
  finished) pushes the tag as its **final step**, after all tickets merge (+ optional `run_devops_scaffold`).
  Versioning is a control-plane lifecycle decision; it needs **no reverse import** (nexus → shared `forge` is
  free, and `run_batch` already lazy-imports the deployment plane), and it **decouples release from
  `--scaffold-deploy`** (a release is "the build finished", not "we regenerated CI").
- **deployment stays a pure config generator** — the DevOps agent emits the workflow the tag triggers; it
  does not version or tag. Unchanged.
- **shared `forge.py` gains the tag-push op** (SSOT seam alongside `open_pr`/`merge_pr`), under the same
  `GH_NETWORK_TIMEOUT` + `sanitize_for_argv` boundary rules ([subprocess-and-external-call-safety](../.claude/rules/subprocess-and-external-call-safety.md)).
- **Version policy (recommended):** derive from the target repo's existing tags — read `git tag`, find the
  latest `v*` semver, bump (minor by default); `v0.1.0` on a greenfield repo with no tags. Repo-derived (not
  invented, not persisted) → idempotent and collision-free across independent builds and `--resume`. The bump
  level is an env-overridable UPPER_CASE constant ([config-constant-convention](../.claude/rules/config-constant-convention.md)).

**Dependencies:** **E4** (a tag-triggered workflow must exist on `main` or the tag is inert) + **E3** (the
batch-completion point). Independent of E5.

**Risks / open questions:**
- **Opt-in, never default:** a release is a deliberate act; `--release` off by default keeps best-practice
  tag-driven releases for normal runs.
- **Outward-facing + low reversibility:** a published Release is public — gate behind the explicit flag and
  log the chosen tag/version. The engine still only pushes a *tag*; the user's Actions performs the actual
  publish with the user's token (consistent with E4's "engine never holds cloud creds").
- **Inert tag:** if no tag-triggered workflow exists (scaffold never run), the tag does nothing — acceptable;
  optionally warn.
- **Monorepo:** assumes one app/version per repo; revisit if one repo hosts several apps.

**Acceptance:** `--idea "…" --auto-execute --scaffold-deploy --release` ends with a `v*` tag on `main` and
the release workflow running automatically (no manual tag); the version is the repo's latest `v*` bumped (or
`v0.1.0` greenfield); `--release` is off by default; re-runs/`--resume` neither duplicate nor collide a tag.
Likely warrants an ADR (new FSM terminal action).

## E7. [⬜ OPEN] Distribute the factory as an installable CLI + factory self-release CI pipeline

**Goal:** two complementary deliverables that make the factory a first-class distributable tool:

1. **`pyproject.toml` + `tbf` entry-point** — any user runs `pip install git+<url>` and gets a `tbf`
   command available on their PATH, exactly like any other Python CLI tool. No manual `python main.py`
   invocations, no repo clone required to *use* (as opposed to develop) the factory.

2. **Factory self-release workflow** — every `v*` tag pushed to *this* repo triggers a GitHub Actions
   workflow (`.github/workflows/release-factory.yml`) that builds a wheel + sdist and publishes a GitHub
   Release with those artifacts attached. Combined with E6's `--release` flag (which tags *generated*
   apps), operators can now also release the factory itself with a single tag push.

> **Scope note:** E6's `--release` pushes tags on the *generated application's* repo. E7 is about
> releasing the *factory engine* itself. They are independent and compose: a factory release (E7) ships a
> new `tbf` version; running `tbf --release` on a project (E6) cuts a release of the app the factory built.

**Current state:**
- Entry-point is `python main.py` (a raw script, not an installed package). Any user wanting to run the
  factory must clone this repo and call the file directly — not portable.
- No `pyproject.toml` exists. `requirements.txt` lists deps but there is no package metadata, no
  `[project.scripts]`, no `pip install`-able wheel.
- No CI release workflow for the factory itself. Releases are manual (`CHANGELOG.md` updated by hand;
  no artifact attached to GitHub Releases).
- The factory already USES `--release` for generated apps (E6); the factory's own versioning is
  entirely manual today.

**Design:**

### Part A — `pyproject.toml` + entry-point

Add `pyproject.toml` at the repo root (alongside `requirements.txt`):

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "token-burners-factory"
version = "0.1.0"                        # bump manually or derive via setuptools-scm
description = "Agentic SDLC pipeline — idea → working app on main"
requires-python = ">=3.12"
dependencies = [
    "instructor>=1.15.1",
    "google-genai>=2.6.0",
    "pydantic>=2.5",
    "jsonref",
    "PyYAML>=6.0",
    "bandit>=1.9.4",
]

[project.scripts]
tbf = "src.nexus.runner:_cli_main"

[tool.setuptools.packages.find]
where = ["."]
include = ["src*", "prompts*"]
```

Add a thin `_cli_main()` shim in `src/nexus/runner.py` (the same pattern already in `main.py`):

```python
def _cli_main():
    import asyncio, sys
    try:
        asyncio.run(main())
    except PipelineHalt:
        sys.exit(1)
```

The `prompts/` directory must be included in the package (it is loaded at runtime via relative paths).
Verify `src/shared/core/prompts.py` resolves `prompts/` relative to the installed package root, not
`__file__` (use `importlib.resources` or `Path(__file__).parent` anchored correctly).

### Part B — Factory self-release GitHub Actions workflow

Add `.github/workflows/release-factory.yml`:

```yaml
name: Release factory

on:
  push:
    tags:
      - 'v*'

jobs:
  build-and-release:
    runs-on: ubuntu-latest
    permissions:
      contents: write          # needed to create GitHub Release + upload assets

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0       # full history so setuptools-scm can derive version

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install build tools
        run: pip install build

      - name: Build wheel + sdist
        run: python -m build

      - name: Create GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          files: dist/*
          generate_release_notes: true   # auto-fills body from commits since last tag
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

This workflow requires **no extra secrets** — `GITHUB_TOKEN` is provided automatically by Actions.
`generate_release_notes: true` auto-generates the changelog body from commits since the previous tag.

### Part C — User onboarding checklist (README update)

The README and/or a `docs/guides/install.md` must document the full prerequisites for a new user:

```
Prerequisites (one-time setup):
  1. Python 3.12+
  2. pip install git+https://github.com/<org>/token-burners-factory.git
     → installs the `tbf` CLI
  3. npm install -g @anthropic-ai/claude-code   # Developer agent
  4. Install gh CLI  (https://cli.github.com)
  5. Install Docker Desktop (or docker-ce on Linux)
  6. git clone https://github.com/<org>/token-burners-factory.git tbf-src
     cd tbf-src && bash scripts/build_sandbox_images.sh   # ~5 min, once per machine

Environment variables (export or .env):
  GEMINI_API_KEY=...              # required always
  GITHUB_TOKEN=...                # required for --auto-merge / --auto-execute
  GITHUB_REVIEWER_TOKEN=...       # optional: enables real PR approval; without it,
                                  # --admin merge is used (no second approver required)

Usage:
  tbf --idea "a REST API in Go" --repo https://github.com/<org>/<new-repo> \
      --auto-execute --auto-merge --scaffold-deploy --release --budget 5
```

**Note on two API keys:** the factory uses *two* LLM providers. Gemini (`GEMINI_API_KEY`) powers all
structured agents (SA, PO, TPM, TechLead, QA, Reviewer, Arbiter, DevOps, TechWriter). Claude
(`claude` CLI, authenticated separately via `claude auth login`) powers the Developer agent. Both must
be configured for a full `--auto-execute` run.

**Note on Docker images:** the sandbox images must be built locally on every machine where the factory
runs. They are not pushed to a registry — they embed the build/test toolchains for each supported
language (Python, Go, Node, .NET) plus the offline Semgrep SAST rules. `scripts/build_sandbox_images.sh`
must be re-run after any `docker/*.Dockerfile` change. (~5 min on first run, < 1 min on rebuilds with
layer cache.)

**Dependencies:** none — E7 is independent of all prior epics. It packages what already exists.

**Risks / open questions:**
- **`prompts/` path resolution:** the prompts directory is loaded at runtime; confirm the path anchor
  (`Path(__file__).parent.parent...`) resolves correctly from an installed wheel (site-packages) vs a dev
  clone. May need `importlib.resources` or a `MANIFEST.in` / `package_data` include.
- **`bandit` as a runtime dep:** `bandit` is an installed CLI tool used by `check_environment()` as a
  subprocess; listing it in `[project.dependencies]` installs it via pip but does not guarantee it lands
  on PATH in all environments. Add a startup check that gives a clear message if `bandit` is not found.
- **Version source:** `version = "0.1.0"` is hardcoded; consider `setuptools-scm` to derive version from
  git tags automatically (then the `pyproject.toml` version always matches the pushed `v*` tag with no
  manual edit). Adds a build dependency but removes version drift risk.
- **PyPI vs GitHub Releases only:** GitHub Releases with wheel/sdist attached is sufficient for `pip
  install git+...` and direct download. A future step could add `twine upload` to publish to PyPI for
  `pip install token-burners-factory` (no git required). Not in scope for E7.

**Acceptance:**
- `pip install git+https://github.com/<org>/token-burners-factory.git` succeeds on a clean Python 3.12
  environment and places `tbf` on PATH.
- `tbf --help` prints the same output as `python main.py --help`.
- `tbf --idea "..." --repo ...` runs an end-to-end pipeline identically to the current `python main.py`
  invocation.
- A `git push origin v0.X.Y` on this repo triggers `.github/workflows/release-factory.yml`, which builds
  `dist/*.whl` + `dist/*.tar.gz` and attaches them to a new GitHub Release automatically.
- The README (or `docs/guides/install.md`) contains the complete user prerequisite checklist including
  both API keys, Docker, `scripts/build_sandbox_images.sh`, and usage examples.

---

# Part II — Defects & Refinements

### Sandbox & egress security

## 4. Restrict egress during the dependency-restore phase
**Why:** the dependency-restore phase (`setup_cmd`) runs with `--network bridge`. Package managers
execute install hooks (e.g. npm `postinstall`) → an exfiltration surface for LLM-authored code. Test
execution and SAST both stay `--network none` (SAST runs fully offline — its rules are vendored into
the image), so only restore keeps a network window.
**Fix direction:** route restore through an egress-restricted proxy (allowlist package registries),
or vendor dependencies offline, so no phase has unrestricted network.

### Contract / topology integrity (Nexus → Executor)

## 19. [P1] `domain_tags[0]` and `environment_id` are validated individually, never against each other
**Symptom:** a `TechLeadContract` with `environment_id=go-1.23-cli` + `domain_tags=['python']` passes
both validators yet loads Python skills ([prompts.py:266](../src/shared/core/prompts.py)) while every gate
runs the Go toolchain ([gates.py](../src/development/gates.py)) — split-brain execution.
**Cause:** skills route on `domain_tags[0]`; gates route on `environment_id`; nothing cross-checks that
the first tag is the language of the selected platform. Currently guarded only by `techlead.md` prose.
**Fix direction:** add a `TechLeadContract` model validator — `env_language(environment_id) == domain_tags[0]`.

## 20. [P1] SA's structured `environment_id` is discarded at the Nexus→executor boundary
**Symptom:** `run_sa` returns only `result.markdown`; [nexus_runner.py:72](../src/nexus/nexus_runner.py#L72)
persists only `blueprint.md`. The validated, authoritative platform key the SA selected never crosses the
boundary — the TPM and TechLead re-extract it from blueprint prose and re-validate.
**Cause:** the markdown is the only persisted artifact; structured fields collapse to text. A blueprint
that says "Python 3.12" rather than the exact key `python-3.12-core` risks misroute/validation failure
downstream. (`sa.md` was hardened to write the exact key verbatim into `## Tech Stack`, but it remains a
text round-trip, not a structured channel.)
**Fix direction:** persist `blueprint_environment_id` in NexusState and thread it into the ticket and the
TechLead input so the chosen platform propagates as a validated value, not re-parsed prose.

## 21. [P2] TechLead contract is an un-cross-checkable single point of failure
**Symptom:** the Developer never sees the blueprint; QA sees the contract; the Reviewer audits the
contract dump ([reviewer.py:23](../src/development/agents/reviewer.py#L23)), not `blueprint.md`. If the
TechLead drops an NFR from `architectural_constraints` or misreads the blueprint, no downstream agent can
detect the omission — they all inherit the flattened contract as ground truth.
**Fix direction:** feed `blueprint_markdown` to the Reviewer as a reference block so it can audit the
TechLead's extraction fidelity against the source, not just adjudicate the derived contract.

## 22. [P3] QA generates tests on cycle 1 with no production-code snapshot (by design)
**Symptom:** cycle 1 `needs_test_regeneration()` is True (no test snapshot, [models.py:283](../src/shared/core/models.py#L283)),
so QA generates BEFORE the Developer ([runner.py:825-851](../src/nexus/runner.py#L825-L851)); the
`PRODUCTION CODE SNAPSHOT` block is absent ([qa.py:162](../src/development/agents/qa.py#L162)). Import
correctness on cycle 1 rests entirely on `topology_contract` precision.
**Note:** contract-first is intentional and `qa.md` says "when present, the PRODUCTION CODE SNAPSHOT"; the
post-Developer test-compile gate ([runner.py:991](../src/nexus/runner.py#L991)) catches resulting import
errors. Tracked as a known limitation, not a defect — monitor for cycle-1 import-collection failures that
trace back to thin/ambiguous topology nodes.

### Arbiter retry budget

## 26. [P2] Zero retry margin when the Arbiter declines to amend the contract
**Context:** the outer cycle ceiling is dynamic —
`MAX_FUNCTIONAL_RETRIES + contract_amendments * AMENDMENT_RETRY_BONUS` (`runner.py`, the `while
ctx.current_attempt <= …` loop; constants near the other reroute caps). Bonus cycles are granted **only on
a contract amendment**. Defaults: `MAX_FUNCTIONAL_RETRIES=3` (env `PIPELINE_MAX_RETRIES`),
`ARBITER_TRIGGER_ATTEMPT=2`, `AMENDMENT_RETRY_BONUS=2`.
**Symptom (observed):** in `005_exec_TASK-03_…` the Arbiter (correctly) routed `qa`/`developer` rather than
`contract`, so `contract_amendments` stayed `0` and the ceiling stayed `3`. The run succeeded on cycle
**3 of 3** — the last allowed cycle, zero slack. A genuinely agent-fixable but hard bug that first surfaces
at cycle 2 (when the Arbiter wakes) gets exactly **one** more attempt before "Retries exhausted." The
Arbiter spend is incurred yet buys no extra budget unless it amends.
**Why it matters:** the Arbiter is meant to *unstick* loops, but for non-`contract` verdicts it can detect
"this is genuinely fixable, give it another shot" and still have the run die on the next cycle for lack of
budget.
**Fix direction (pick one / combine):** (a) grant a smaller bonus (e.g. +1) when the Arbiter returns a
*confident* `developer`/`qa` verdict on a stuck cycle, so a correctly-diagnosed fixable bug gets headroom;
(b) raise the default `MAX_FUNCTIONAL_RETRIES` (it is now an env-tunable constant — cheap to bump for
operators); (c) gate the Arbiter on a *repeated/identical* failure rather than `attempt >= 2`, so it only
spends when truly stuck and any granted bonus is better targeted. Bound any bonus to keep the financial
circuit breaker the absolute ceiling.

### Git / run hygiene

## 23. [P2] Abort path leaves staged changes in the run clone's index
**Symptom:** every reroute calls `git add -A` (in `build_production_snapshot`); `_abort_with_incident`
does `sys.exit(1)` with no `git reset`. The run clone is reused on `--resume`, so a resumed run starts
with a dirty index from the failed attempt. `finalize_transaction` only stages-and-commits on success.
**Fix direction:** `git reset` (or discard the worktree) in `_abort_with_incident` for clean resume hygiene.

## 27. [P1] Gemini billing-balance exhaustion not handled gracefully — 403 billing errors are retried with no actionable message
**Symptom (reported 2026-06-23):** the Google AI Studio account went negative (−1 PLN). Depending on
what the Pay-as-you-go API returns, one of two bad paths fires:
- **429 `RESOURCE_EXHAUSTED` with billing context** — `api_retry.py:40` fast-fails correctly, but
  `handle_quota_error` (`config.py:293`) logs "quota limit / ensure Pay-as-you-go plan" — the wrong
  advice when the user IS on pay-as-you-go and the real fix is to top up the balance.
- **403 `PERMISSION_DENIED` / `BILLING_DISABLED`** — `api_retry.py:40`'s `status_code == 429` check
  does NOT match; the error falls through to `_retry_or_raise`, burns 3 retries with exponential
  backoff (6 + 8 + 12 s), then dies with a generic "API call failed after 3 attempts — ClientError"
  and no billing context. The operator has no idea why.
- **Structured (instructor) calls surface it as `InstructorRetryException`, NOT `ClientError`** —
  **OBSERVED 2026-06-23** in the `write-a-python-cli-utility-that-takes-a` 4-ticket batch (runs
  `005`/`006_exec_TASK-04`): the Reviewer Agent (the heaviest Gemini call) died twice with
  `🚨 CRITICAL: Reviewer Agent API call failed after 3 attempts — InstructorRetryException`, no incident,
  no billing context. The batch process exited (this is **not** a `PipelineHalt`, so `batch_state.failed`
  stayed `null` and no `incident_report.json` was written); TASK-04 only completed after a manual
  `--resume` (run `008`) once the balance was topped up. instructor wraps the underlying 403/429 in its
  OWN retry, so `api_retry.py`'s `except ClientError` (line 39) never matches — the error lands in the
  generic `except Exception` (line 46) with no `status_code`, so **both the existing 429 branch AND a new
  403 branch (fix #1 below) would MISS it**. Every role except the Developer is a structured call, so this
  is the dominant path.
**Root cause:** `ClientError` catches ALL 4xx HTTP errors; only 429 is branched as non-retryable. A
billing 403 is not transient — retrying it is wasteful and misleading. The error message in the 429
path also does not distinguish rate-limit (true quota) from balance-exhaustion. For structured calls the
real exception is `InstructorRetryException` wrapping the 403/429, which the `ClientError`-keyed logic
never inspects.
**Fix direction:**
1. `src/shared/utils/api_retry.py` — add a fast-fail branch for 403 alongside 429: billing errors are
   permanent, not transient; retrying them wastes backoff budget and obscures the real cause.
2. `src/shared/core/config.py` — split `handle_quota_error` (or add `handle_billing_error`) to detect
   billing-exhaustion signals in `e.status` or `e.message` (keywords: `BILLING_DISABLED`, `PERMISSION_DENIED`,
   negative balance message) and surface: *"Your Gemini account balance is negative — top up at
   console.cloud.google.com/billing"* vs the rate-limit message for a true 429 quota hit.
3. **Unwrap the instructor case (the actually-observed path):** in the generic `except Exception` of
   `api_retry.py`, detect a billing/quota 403/429 wrapped inside `InstructorRetryException` (inspect its
   `__cause__` / wrapped error) and fast-fail with the same actionable message — otherwise the common
   structured-call path (every role but the Developer) burns 3 retries and dies contextless, exactly as
   seen in the TASK-04 run. NB: this is a billing/quota stop, not an FSM defect — the batch itself behaved
   correctly and completed once funded.

## 24. [P3] Misleading comment on the QA-self zombie-disposal path
**Symptom:** [qa.py:231](../src/development/agents/qa.py#L231) labels the `suite.files_to_delete` disposal as
"Reviewer-routed", but that path is QA-self-identified; the Reviewer-routed disposal is the separate block
at [qa.py:126-129](../src/development/agents/qa.py#L126-L129). Both call the same idempotent guarded
`_dispose_zombie_tests`, so behavior is correct — only the comment is wrong.
**Fix direction:** relabel the [qa.py:231](../src/development/agents/qa.py#L231) comment to "QA-self-identified
obsolete files" to match the dual-path reality already documented in `qa.md`.

### Model routing & cost efficiency

## 28. [P2] Per-role reasoning-effort / thinking routing (both providers) — second cost-tuning axis
**Why:** model routing is currently a SINGLE axis (which model) and effectively flat — all nine Gemini roles
default to `gemini-3.5-flash` ([config.py](../src/shared/core/config.py)), and only the Developer differs (on
`claude-sonnet`). The Cyberthone cost-efficiency dimension explicitly rewards *different tiers for different
roles* (7.2 → 0 pts if every agent uses one model) and *A/B trade-off evidence* (7.3). A second tuning axis —
**how hard the model thinks** — multiplies the effective routing matrix (`{model} × {effort}`) without adding
models, so a cheap role can run a cheap model at minimal effort while a complex role runs a stronger model at
high effort.
**Current state:**
- Per-role models exist via `ROLE_MODELS` ([config.py](../src/shared/core/config.py)), but the assignment is
  uniform `gemini-3.5-flash` for every structured role.
- The Developer (Claude CLI) takes a single GLOBAL `DEVELOPER_EFFORT` constant (`AVAILABLE_EFFORT_LEVELS` =
  `low…max`) — there is **no per-role** effort knob.
- Gemini has **no** thinking control wired at all — `run_structured_llm`
  ([llm.py](../src/shared/utils/llm.py)) never passes `thinking_config` / `thinking_level` (3.x) /
  `thinking_budget` (2.5) to the genai client.
**Fix direction:**
1. Generalize each role's config from a bare model into a `(model, effort_or_thinking)` pair — extend
   `ROLE_MODELS` (or a parallel `ROLE_EFFORT` map) with an env-overridable level per role
   ([config-constant-convention](../.claude/rules/config-constant-convention.md)).
2. Thread Gemini `thinking_config` into the `instructor`/genai call in `run_structured_llm`, and a per-role
   `--effort` into the Developer CLI launcher (replacing the single global constant).
3. Surface the chosen level per agent in `PipelineTelemetry` / the FinOps report so the cost-vs-quality A/B
   is capturable (feeds 7.3). Keep cache-exclusion + the money-only breaker invariants
   ([token-budget-excludes-cache](../.claude/rules/token-budget-excludes-cache.md),
   [finops-app-budget](../.claude/rules/finops-app-budget.md)).
**Acceptance:** a role can be assigned both a model and a thinking/effort level; mechanical roles
(TechWriter, formatting, log-summary, DevOps lint) run minimal-effort and complex roles
(Architect/TechLead/Reviewer/Arbiter) run high-effort; the level is recorded per agent; an A/B comparison
across two re-runs is capturable for the cost report. (Surfaced from the Cyberthone 2026 dimension-7 prep;
see [docs/hackathon/agentic-sdlc-specification-v1.md](hackathon/agentic-sdlc-specification-v1.md) §7.)

### Performance / wall-clock

## 29. [P2] SAST/semgrep is the dominant infra time sink (~130s/cycle) — narrow ruleset + exclude build output
**Why:** the SAST scan (`SAST_CMD = "semgrep scan --error --metrics off --config /opt/semgrep-rules /workspace"`,
[environments.py](../src/shared/core/environments.py)) runs once per FSM cycle and measured ~130s/run on a
tiny .NET CLI (audit log, run 003) — the single largest *infra* (non-LLM) sink, compounded by cycle count.
It was invisible until the wall-clock telemetry surfaced it (the FinOps TOTAL had counted LLM time only; the
`by_phase` accumulator in [models.py](../src/shared/core/models.py) `PipelineTelemetry` now times it as the
`qa+sast` phase).
**Current state:** the scan walks the whole `/workspace` (post-build, so `obj/`/`bin/` with generated
`AssemblyInfo.cs` + DLLs are present) and loads the FULL vendored ruleset (`/opt/semgrep-rules`) regardless
of the ticket's language. For a 2-file project, rule-load + scanning build artifacts dominates the wall.
**Fix direction (behind a measurement spike — security-sensitive, keep coverage):**
1. Exclude build output / VCS dirs (`--exclude obj --exclude bin --exclude .git`, or a vendored
   `.semgrepignore`) so semgrep never walks generated/compiled files.
2. Scope the ruleset to the ticket's language (select the `/opt/semgrep-rules/<lang>` subset keyed off the
   env's `language_id`) instead of loading every rule for every stack.
3. Raise scan parallelism if still CPU-bound after (1)/(2) — `--jobs` tied to the sandbox CPU cap
   (`SANDBOX_CPUS`, env-overridable since the wall-clock work; default 4).
**Guardrails:** preserve the offline `--network none` + vendored-rules posture (`--config auto` is forbidden
behind the corporate TLS proxy — see [deploy-scaffolding-and-ci-parity](../.claude/rules/deploy-scaffolding-and-ci-parity.md)
and [qa-sandbox-hardening](../.claude/rules/qa-sandbox-hardening.md)), `--error` (findings -> non-zero gate),
and zero-finding coverage parity — prove with a before/after on a repo with a planted finding. Quantify the
win via the `by_phase` telemetry (`qa+sast`). Distinct from #28 (model routing).
**Acceptance:** the `qa+sast` infra phase drops materially with no loss of true-positive coverage; the scan
still runs fully offline and fails on a planted finding.
