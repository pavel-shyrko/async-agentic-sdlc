# Backlog

Two parts:

- **Part I — Capability Roadmap (Epics `E1`–`E4`)**: the forward-looking work to close the autonomy loop
  (idea → working, merged code in `main` → deployable). Larger than a single fix; each has its own
  Goal / Current state / Design / Dependencies / Risks / Acceptance.
- **Part II — Defects & Refinements (`#4`–`#26`)**: granular fixes surfaced across pipeline runs, grouped by
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

---

# Part I — Capability Roadmap (Epics)

**North star:** an *idea in* → a *working, reviewed, merged application in `main`* → *deployable*, with the
engine driving the whole cycle autonomously. Today the engine is a **head + hands** split that stops
half-finished: **Nexus** (head) plans `Epic → Blueprint → TASK-*.md`, but the operator launches the
**Executor** (hands) by hand one ticket at a time, and verified work lands only on a `feat/ticket-<id>`
branch that is **never merged**.

**Dependency order (build in this sequence):**

```
E1  Nexus auto-dispatches Executor (one ticket)
      └─► E2  Close the loop to main (auto-approved PR + merge)
              └─► E3  Cyclical multi-ticket orchestration (all tasks, each building on the last)
                      └─► E4  DevOps / deployment   (scope only — decision deferred)
```

E3 depends on E2 for a hard structural reason (see E3): each ticket clones `main` **fresh**, so TASK-02 only
sees TASK-01 if TASK-01 has already been merged to `main`.

---

## E1. [EPIC] Nexus auto-dispatches the Executor (single ticket)

**Goal:** after planning, the engine automatically runs the Executor for `TASK-01` — no manual second
command. (User-requested feature 1: "nexus запускал executor с задачей 1".)

**Current state:**
- The two planes are bridged only inside `main()` (resume routing by checkpoint `kind`,
  [runner.py:647-673](../src/executor/runner.py#L647-L673)); neither plane invokes the other — the operator
  does, via a second `--run` invocation.
- The per-ticket Executor flow (bootstrap → FSM cycle → finalize) is **inlined inside `main()`**
  ([runner.py](../src/executor/runner.py), roughly the `bootstrap_session` → while-loop → `finalize_transaction`
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

## E2. [EPIC] Close the loop to `main` via an auto-approved PR

**Goal:** on a successful ticket, open a PR from `feat/ticket-<id>` into `base_branch` and **auto-approve +
merge** it, so verified work actually lands in `main`. (User-requested feature 2; chosen approach: **PR +
auto-approve + merge** — full-autonomy MVP, switchable to human-review later.)

**Current state:**
- `finalize_transaction` makes the atomic `feat(<ticket>): …` commit on `feat/ticket-<id>` and, with `--push`,
  runs `git push -u origin HEAD` — and stops ([runner.py:219-257](../src/executor/runner.py#L219-L257)). The
  success block that calls it is [runner.py:1155-1163](../src/executor/runner.py#L1155-L1163).
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

## E3. [EPIC] Cyclical multi-ticket orchestration

**Goal:** Nexus drives the Executor over **all** generated tasks in order — `TASK-01 → merge → TASK-02 → …` —
so each ticket builds on the previously merged state, ending with the full app on `main`. (User-requested
feature 3: "nexus циклично по таскам запускал executor".)

**Current state:** each ticket runs in its **own** exec run dir and **clones `main` fresh** on a new
`feat/ticket-<id>` branch ([bootstrap_session](../src/executor/runner.py#L165-L192)). There is no cross-ticket
state — TASK-02's clone does **not** contain TASK-01's work unless it has already merged to `main`.

**Design (seam + approach):** a batch loop over `get_tasks_for_nexus_run(...)` (from E1) calling
`execute_one_ticket(..., auto_merge=True)` in TPM order. **Correctness hinges on E2 merging to `main` before
the next ticket's fresh clone** — that is what makes the fresh-clone model compose into a coherent,
cumulative application. Add a **batch-level checkpoint** (which tickets are done) for resume, and an explicit,
tunable **failure policy** (default: stop the batch on the first unrecoverable halt, write the incident, and
let `--resume` continue from the failed ticket).

**Dependencies:** **E1 + E2** (hard).

**Risks / open questions:** a mid-batch halt strands later tickets (resume story must be solid); per-ticket
FinOps vs a batch-wide budget ceiling; inter-ticket ordering/dependencies are implicit via shared `main` (no
explicit DAG between tickets today); ties to **#20** (env_id must propagate cleanly per ticket) and **#26**
(per-ticket retry budget).

**Acceptance:** `--idea "…"` with auto-execute + auto-merge drives every task to `main` in order; a halt stops
the batch cleanly with an incident, and `--resume` continues from the failed ticket without redoing merged
ones.

## E4. [EPIC] DevOps / deployment — SCOPE ONLY (decision deferred)

**Goal:** record the epic and its decision space; **do not pick the mechanism yet** (user choice:
"только зафиксировать scope" — needs refinement on *how and where* to deploy).

**Current state:**
- The **DevOps** node is named in the mission graph (README "Target Pipeline Graph") and
  [ADR 0000](decisions/0000-cloud-infra-fsm-research.md), but has **zero implementation**; the pipeline stops
  at QA/Reviewer.
- [environments.py](../src/shared/core/environments.py) has `build`/`test`/`setup`/`format` commands but
  **no `run`/`serve`/`package`/`deploy`** command. `docker_adapter.py` runs ephemeral, least-privilege
  *verification* sandboxes only — not a deployment target.
- [techwriter.py](../src/executor/agents/techwriter.py) is the exact structural template for a success-path
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

### Reviewer accuracy & feedback-channel routing

## 11. [P1] Reviewer hallucinates production defects not present in the gate output
**Symptom:** cycle 1 `code_quality_approved=false` + `dev_diagnostic_payload` "rename go.mod module
from `main`, fix circular imports" — none of which exist (`go.mod` is `github.com/godeltech/jsonconv`,
imports are correct). Burned a Developer reroute on a phantom; the real fault was entirely in the test
file.
**Fix direction:** constrain the Reviewer prompt so `code_quality_approved=false` / `dev_diagnostic_payload`
must cite a verbatim line from the actual gate output (build/test/SAST), not inferred structure; when
the only failing file refs are test files, the production verdict must default to approved. (Partially
mitigated: `reviewer.md` now routes test-only import/linkage failures to the QA channel and forbids
flagging legacy code — but verbatim-citation is still not enforced.)

## 17. [P1] Reviewer can reject without guidance — silent retry-budget burn
**Symptom:** the Reviewer sets `code_quality_approved=false` (or `test_integrity_approved=false`) while
leaving the matching payload `""`. Routing at [runner.py:1089-1092](../src/executor/runner.py#L1089-L1092)
copies the empty trace; the agent re-runs next cycle with zero guidance, reproduces the same output, and
the loop burns all `max_retries` cycles until aborting "Retries exhausted."
**Cause:** no model/code invariant ties an approval to a non-empty payload. The deadlock guard
([runner.py:1070](../src/executor/runner.py#L1070)) only catches `gate_failed ∧ approved_both`, never
`not approved ∧ empty payload`. Payload defaults are `""` ([models.py:244-245](../src/shared/core/models.py)).
**Fix direction:** add a `ReviewReport` model validator — `not code_quality_approved ⇒ dev_diagnostic_payload != ""`
and the QA analog — so a guidance-less rejection fails fast with a debuggable validation error instead of
silently wasting the budget.

## 18. [P2] Feedback-channel isolation is enforced only by prompt, not by code
**Symptom:** `reviewer.md` mandates "never duplicate an instruction across both channels," but
[runner.py:1091-1092](../src/executor/runner.py#L1091-L1092) copies BOTH `dev_diagnostic_payload` and
`qa_diagnostic_payload` unconditionally. If the Reviewer LLM populates both (or the wrong one), the
Developer and QA both act next cycle and can fight (dev edits production while QA expects a test fix).
**Cause:** the transport is isolated (`error_trace` vs `qa_error_trace`, reset each cycle at
[runner.py:816-817](../src/executor/runner.py#L816-L817)), but *which* channel the Reviewer fills is an
LLM-trust invariant with no code guard.
**Fix direction:** validate routing coherence — e.g. a payload may be non-empty only when its own
approval is false (pairs naturally with #17), and log/incident when both are populated in one report.

## 25. [P2] Arbiter `developer`/`qa` routes are advisory — they don't change control flow
**Context:** the Arbiter (ADR [0016](decisions/0016-arbiter-contract-self-healing.md), added to the FSM at
[runner.py](../src/executor/runner.py) in the `if not all_gates_passed:` block) returns
`ArbiterVerdict.route ∈ {developer, qa, contract, halt}`. Only `contract` (re-derive the TechLead spec)
and `halt` (abort) actually alter control flow. For `developer`/`qa` the code **falls through to the
existing isolated-channel routing** — i.e. the next cycle is driven by the Reviewer's
`dev_diagnostic_payload`/`qa_diagnostic_payload`, NOT by the Arbiter's verdict.
**Symptom (observed):** in the TASK-03 run `005_exec_TASK-03_…`, the Arbiter fired once on cycle 2,
correctly diagnosed a **test defect** (`route=qa`, `root_cause_class=test_bug` — a test mocked `json.load`
while the production code streamed via `ijson`, so the mock was inert and the test ran an empty file), then
fell through. The recovery on cycle 3 was driven entirely by the Reviewer's channels + `regenerate_tests`;
the Arbiter's (correct) verdict cost one Gemini call (~$0.013) but changed nothing. So today the Arbiter
only "earns its cost" on `contract`/`halt`.
**Why it matters:** the most valuable thing a `developer`/`qa` verdict could do is **override a Reviewer
misroute**. Channel-isolation is the classic deadlock (see #18): the Reviewer can fill the wrong channel
(test fix written into `dev_diagnostic_payload`, or vice versa), and since the Developer can't touch tests
and QA can't touch production code, the run loops to the breaker. The Arbiter already has the diagnosis
needed to fix this.
**Fix direction:** make `developer`/`qa` routes authoritative. When the Arbiter's `route` disagrees with
which Reviewer payload is populated, re-route: move the fix text into the channel the Arbiter chose
(`ctx.error_trace` for `developer`, `ctx.qa_error_trace` for `qa`) and clear the other, instead of copying
both payloads verbatim. Pairs naturally with #17/#18 (payload-coherence validation). Keep the fall-through
only when the Arbiter agrees with the Reviewer's routing.

### Contract / topology integrity (Nexus → Executor)

## 19. [P1] `domain_tags[0]` and `environment_id` are validated individually, never against each other
**Symptom:** a `TechLeadContract` with `environment_id=go-1.23-cli` + `domain_tags=['python']` passes
both validators yet loads Python skills ([prompts.py:266](../src/shared/core/prompts.py)) while every gate
runs the Go toolchain ([gates.py](../src/executor/nodes/gates.py)) — split-brain execution.
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
contract dump ([reviewer.py:23](../src/executor/agents/reviewer.py#L23)), not `blueprint.md`. If the
TechLead drops an NFR from `architectural_constraints` or misreads the blueprint, no downstream agent can
detect the omission — they all inherit the flattened contract as ground truth.
**Fix direction:** feed `blueprint_markdown` to the Reviewer as a reference block so it can audit the
TechLead's extraction fidelity against the source, not just adjudicate the derived contract.

## 22. [P3] QA generates tests on cycle 1 with no production-code snapshot (by design)
**Symptom:** cycle 1 `needs_test_regeneration()` is True (no test snapshot, [models.py:283](../src/shared/core/models.py#L283)),
so QA generates BEFORE the Developer ([runner.py:825-851](../src/executor/runner.py#L825-L851)); the
`PRODUCTION CODE SNAPSHOT` block is absent ([qa.py:162](../src/executor/agents/qa.py#L162)). Import
correctness on cycle 1 rests entirely on `topology_contract` precision.
**Note:** contract-first is intentional and `qa.md` says "when present, the PRODUCTION CODE SNAPSHOT"; the
post-Developer test-compile gate ([runner.py:991](../src/executor/runner.py#L991)) catches resulting import
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

## 24. [P3] Misleading comment on the QA-self zombie-disposal path
**Symptom:** [qa.py:231](../src/executor/agents/qa.py#L231) labels the `suite.files_to_delete` disposal as
"Reviewer-routed", but that path is QA-self-identified; the Reviewer-routed disposal is the separate block
at [qa.py:126-129](../src/executor/agents/qa.py#L126-L129). Both call the same idempotent guarded
`_dispose_zombie_tests`, so behavior is correct — only the comment is wrong.
**Fix direction:** relabel the [qa.py:231](../src/executor/agents/qa.py#L231) comment to "QA-self-identified
obsolete files" to match the dual-path reality already documented in `qa.md`.
