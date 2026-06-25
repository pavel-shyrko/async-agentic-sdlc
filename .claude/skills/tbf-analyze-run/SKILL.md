---
name: tbf-analyze-run
description: Diagnose a pipeline run (executor or Nexus) from its persisted artifacts — classify root cause, cite evidence, and point the fix at the engine/prompts (never the clone). Use when the user asks to analyze/diagnose a run, explain a CIRCUIT BREAKER / "Retries exhausted" halt, an application-budget exhaustion / `budget_marker` clean stop (`--budget` / `PIPELINE_APP_BUDGET_USD`, E5), a looping or stuck cycle, a Gemini RECITATION/SAFETY block, a PR/merge (forge) failure under `--auto-merge`, a lint-gate reroute loop or an E4 deploy-scaffolding (`--scaffold-deploy`) static-lint halt (incl. a missing public-invoker grant on a Cloud Run web service, or a *live* deployed service returning HTTP 403 / "not authenticated"), a Developer Claude-CLI provider-quota / session-limit halt (a `🚨 PROVIDER QUOTA HALT` / "hit your session limit" stop where the Developer billed 0 tokens), a HARD HALT (wrong-path / documentation guardrail) or ENVIRONMENT/NETWORK/LINT-TOOLING halt, a missing-dependency-manifest halt (a `🚨 MISSING DEPENDENCY MANIFEST` banner, or an older run where a `ModuleNotFoundError` for a declared core library was misrouted to the Reviewer and the Arbiter halted `unrecoverable` because the toolchain restored nothing — no `requirements.txt`/`go.mod`/`package.json`/`.csproj`), a git clone/push credential failure, a non-halt crash/hang (an `embedded null byte` traceback, a Jinja-in-system-message `ValueError`, or a stalled agent call that printed no incident), or "what happened" in a runs/<project>/<NNN>_... run. Accepts a run dir, a project slug, or pasted run log output.
context: fork
---

# Pipeline Run Analysis

## Context
Operationalizes the diagnostic procedure in [debugging-protocol](../../rules/debugging-protocol.md) and
the control-flow reference in [pipeline-fsm-loops](../../rules/pipeline-fsm-loops.md). The goal is an
EVIDENCE-FIRST root-cause analysis: never assume "the LLM just failed." Locate the systemic engine/prompt
flaw, then recommend a fix in `src/`/`prompts/` — NEVER edit the generated clone
(`runs/<project>/<NNN>_exec_…/repo/`), per the workspace guardrails. **Reading** the clone for evidence
(confirming a stub was never implemented, a file landed at the wrong path, what the generated code
actually does) is expected and often decisive — only *mutating* it is forbidden.

Path note: read artifacts with the Read/Grep tools using their drive-letter Windows path (`C:\…\runs\…`);
a verbatim `/mnt/c/…` path the user pastes fails from the Bash tool (Git Bash mounts the drive at `/c/…`,
not `/mnt/c/…`) — see [run-tests-via-wsl](../../rules/run-tests-via-wsl.md).

## Step 1 — Locate the run
- If given a run dir, use it. If given a project slug, pick the relevant run under `runs/<slug>/`
  (`<NNN>_exec_<ticket>_…` for executor, `<NNN>_nexus_plan_…` for control plane); the highest `<NNN>` is
  newest. If given only pasted log output, work from it but prefer reading the artifacts when a path is
  derivable. Layout SSOT: [run-layout-and-cli](../../rules/run-layout-and-cli.md).
- **Multi-ticket batch (`--auto-execute`, E3 + E5):** read the `nexus_plan` run's `reports/batch_state.json`
  first — `failed` names the ticket that stopped the batch (analyze *that* ticket's `<NNN>_exec_<failed>_…`
  run); `completed` confirms the merged ones; `budget_marker` (if set) means the batch stopped **cleanly on
  application-budget exhaustion** (see the budget-stop class below); `app_telemetry.total_cost_usd` is the
  cumulative spend across Nexus + all tickets + DevOps. The application-wide cost lives in
  `reports/app_finops_report.json` (per-role + per-plane + time), refreshed on every batch exit. A batch with
  `failed: null`, `budget_marker: null` and a `🏁 Batch complete` line is a clean success.
- **Deploy-scaffolding (`--scaffold-deploy`, E4):** the deploy phase is its own `<NNN>_devops_scaffold_…`
  run dir (cloned on `chore/devops-scaffold`), separate from the ticket runs. A persistent `run_devops_gate`
  failure writes an `incident_report.json` *there*; a forge merge failure of the scaffold PR is a
  loop-closure failure (no incident). The merged application code is untouched on any deploy-phase failure.
  The deploy mechanics live in the registry-driven platform skills (`prompts/skills/deploy_{gcp,github_release}.md`),
  separate from the app-shape archetype skills; `run_devops_gate(repo_dir, archetype)` is archetype-aware and,
  for a `requires_public_invoker` target (Cloud Run web service), flags a workflow that omits the
  `--allow-unauthenticated` grant (self-healed by the DevOps agent in the `DEVOPS_MAX_RETRIES` loop).
  **Live-service 403 (not a run artifact):** a deployed Cloud Run service that returns HTTP 403 / "The request
  was not authenticated" means the *deployed* workflow predates this gate (no public-invoker grant) — the fix
  is to re-run `--scaffold-deploy` (regenerates the workflow with the grant) or apply the
  `allUsers → roles/run.invoker` IAM binding once; never an app-code or clone edit.
- **Release-tagging (`--release`, E6):** the release phase is its own `<NNN>_release_tag_…` run dir (cloned
  on `chore/release-tag`), the FINAL step after the batch (+ optional scaffold). It makes **no agent call**
  and is **best-effort** — a failed `forge.push_tag` logs `🚨 [E6] Release tag … did not land` and returns;
  it writes **no incident** and does NOT fail the build (the app already merged). The pushed tag is recorded
  in `BatchState.released_tag` (a complete-batch `--resume` short-circuits via it). Diagnose a "the release
  workflow didn't run" report by checking: did the tag push log success (grep the release run's
  `sdlc_audit.log` for `🏷️`/`🏁 [E6]`)? Is `released_tag` set in `batch_state.json`? Does a tag-triggered
  workflow (`on: push: tags: ['v*']`) actually exist on `main` (an **inert tag** if `--scaffold-deploy` never
  ran is expected, not a bug)? The fix points at the forge seam / env or the missing workflow — never an agent.

## Step 2 — Gather state (in this order)
1. **Checkpoint** — `reports/checkpoint.json`. Executor (`GlobalPipelineContext`): `current_attempt`,
   `contract` (the TechLead spec — `instruction`, `function_signatures`, `architectural_constraints`,
   `files_to_modify`, `environment_id`, `topology_contract`), `review_report`
   (`code_quality_approved`/`test_integrity_approved` + `code_quality_analysis`/`test_integrity_analysis`/
   `log_verification_analysis` + `dev_diagnostic_payload`/`qa_diagnostic_payload`/`dev_evidence_citation`),
   `error_trace`/`qa_error_trace`, and the Arbiter fields `arbiter_verdict{root_cause_class,route,reasoning,
   contract_amendment_directive}` + `contract_amendments`. Nexus (`NexusState`): `completed_phase`,
   `epic_text`/`blueprint_text`/`tasks`.
2. **Audit log** — `logs/sdlc_audit.log`. A `tail` shows only the LAST cycle + the FinOps total; on a
   multi-cycle run the decisive evidence (a per-cycle agent failure, a `hit your session limit` line, an
   Arbiter `route`) repeats MID-log — so **grep the whole file, don't just tail it**. Trace the FSM by
   its markers: `[ROLE]` (every agent turn — the reliable anchor for who ran when), `🔷 Orchestration
   cycle N/M` (cycle boundaries), `🔶` (cycle-failed + fast-fail reroutes), `[VERDICT]`/`route=`
   (Arbiter), `[TOKENS]` (per-agent spend), and any `🚨 … HALT` / `CIRCUIT BREAKER` / `🛑` header. Then
   grep for known failure signatures: `hit your session limit`, `RECITATION`, `NU1301`/`NU1510`,
   `ModuleNotFoundError`, `MISSING DEPENDENCY MANIFEST`, `embedded null byte`, `Jinja templating`,
   `could not read Password`.
3. **Incident report** — `reports/incident_report.json` (present only on an FSM halt): the redacted final
   state + the halt header. **Tell:** a run that printed the FinOps GRAND TOTAL and then died with a raw
   Python traceback (and **no** incident report) is *not* an FSM halt — it is an uncaught exception that
   escaped to `main()` **after** the gates passed: a loop-closure (`finalize_pr`/`gh` merge) failure, an
   `embedded null byte` argv crash, or (pre-`GEMINI_REQUEST_TIMEOUT`) a stalled call. Read the traceback's
   frame, not the absent incident.
4. **FinOps** — `reports/finops_report.json` (per-agent token/USD/time + per-plane + cumulative); for a batch
   also the `nexus_plan` run's `reports/app_finops_report.json` (application-wide: Nexus + all tickets + DevOps).
   **Cross-cutting tell:** an agent with `calls > 0` but `0t / $0.00` (e.g.
   `Developer Agent (claude, development) | 0t | $0.0000 | … | calls: 3`) was *invoked but produced
   nothing* — a provider-quota block, a boundary crash, or an empty/failed turn. That one line often
   points straight at the root cause; reconcile it against the per-cycle `[ROLE]` markers. Conversely a
   role with far MORE calls than cycles signals fast-fail reroute churn (guardrail / lint / QA-compile).
5. **Gate output** — for a test/build/SAST failure, read the raw runner output captured in the log /
   checkpoint (`_extract_failure_context`); it is also surfaced in `error_trace`/`qa_error_trace`.

## Step 3 — Classify the root cause
**Triage order** (take the first that fits, then *confirm* with the verbatim evidence — don't stop at the
first plausible class): (1) Is there an `incident_report.json`? Its halt header **names the class** — read
it first. (2) No incident, but a Python traceback after the FinOps GRAND TOTAL → a boundary-crash, an
infra git clone/push failure, or a loop-closure (forge) failure (all escape `main()` without an incident).
(3) For a batch, `batch_state.json`: `budget_marker` set → clean budget-stop; `failed` set → analyze that
ticket's run. (4) Scan FinOps for a `calls>0 / 0-token` agent (step 2.4). (5) Otherwise: which gate or
Reviewer/Arbiter verdict failed, and *why did no channel/route resolve it* across cycles?

Then map the evidence to one class (decisive — pick the dominant one and say so):
- **Gemini content-filter block** (Nexus or any structured call) — `finish_reason` RECITATION / SAFETY /
  BLOCKLIST / PROHIBITED_CONTENT / SPII (`describe_finish_reason`). RECITATION = output reproduced
  training-data text verbatim (canonical boilerplate, licenses, scaffolds). Deterministic — a plain retry
  cannot help; the engine fails fast (one paraphrase retry for RECITATION) — see
  `src/shared/utils/{api_retry,llm}.py`, `src/shared/core/observability.py`.
- **Agent-fixable bug** — a real production-code defect (→ Developer / `dev_diagnostic_payload`) or a test
  defect (→ QA / `qa_diagnostic_payload`, e.g. a test mocking a function the streaming code never calls).
- **Contract conflict** (not downstream-fixable) — the `contract` itself mandates a contradictory/
  impossible algorithm, overlapping `Raises` with no precedence, or the only fix would violate a stated
  `architectural_constraints` (e.g. break an O(1)/streaming NFR). This is the Arbiter's `contract` route →
  TechLead amendment (ADR [0016](../../../docs/decisions/0016-arbiter-contract-self-healing.md)). **Tell
  it was attempted-then-exhausted:** a `🚨 ARBITER: unrecoverable spec conflict (amendments N/M)` halt
  header — the Arbiter routed `contract` but `contract_amendments` already hit `MAX_CONTRACT_AMENDMENTS`,
  so self-healing was downgraded to a halt (BACKLOG #26). `contract_amendments > 0` in the checkpoint
  confirms an amendment ran.
- **Environment/runner misconfiguration** — a hard gate FAILED while the Reviewer approved BOTH sides
  (`🚨 ENVIRONMENT\RUNNER MISCONFIGURATION` deadlock guard, `runner.py`): not agent-fixable (e.g. sandbox
  import-path/network). The Reviewer approving both sides on a hard-gate FAILURE is the signature.
- **Missing dependency manifest** — a build/test/test-compile gate FAILED with a module-resolution error
  (`ModuleNotFoundError`, `Cannot find module`, `cannot find package`) because the env's declared
  `dependency_manifest` (`requirements.txt`/`package.json`/`go.mod`/`.csproj`) was ABSENT, so `setup_cmd`
  restored NOTHING (the silent `pip install -r requirements.txt 2>/dev/null || true` no-op). The
  `missing_dependency_manifest` backstop (`gates.py`) now prepends a `🚨 MISSING DEPENDENCY MANIFEST` banner,
  so a current run names itself; an OLDER run shows it mislabelled (the import error misrouted to the
  Reviewer → Arbiter `root_cause_class: unrecoverable`). Fix is **authoring-side, not the clone**: the env's
  `authoring_contract` + the language `_core` skill must mandate producing the manifest (e.g. `python_core`
  → `requirements.txt`), and the SA `## Runtime Contract` / TPM `TASK-01` propagation must carry it — see
  [agent-contracts](../../rules/agent-contracts.md). NEVER hand-add the manifest to the run clone.
- **Guardrail hard-halt (Developer pre-Reviewer fast-fail loops)** — a Developer guardrail loop hit its
  `GUARDRAIL_MAX_REROUTES` cap and aborted *before* the Reviewer ever ran. Three distinct headers/causes,
  each pointing at a different fix:
  - `🚨 HARD HALT: contracted file(s) created at the WRONG path …` — the Developer placed a contracted
    file off its `topology_contract`/`files_to_modify` path. Fix the TechLead topology contract or the
    `developer_topology` skill (the path SSOT) — not the agent.
  - `🚨 HARD HALT: Developer failed the documentation guardrail …` — a newly-created uncontracted file
    lacks the mandated top-of-file justification comment. Fix `developer.md`'s justification directive or
    the `enforce_documentation_guardrail` scanner (`runner.py`).
  - `🚨 ENVIRONMENT\NETWORK HALT: dependency restore could not reach the package feed (NU1301 / …)` — the
    sandbox couldn't reach the package registry on the compile gate. Infra/network, retry-later — NOT a
    code defect; check the proxy/offline-vendoring posture, never reroute the Developer.
- **Financial circuit breaker** — cumulative **USD** spend met/exceeded the effective ceiling
  (`enforce_financial_circuit_breaker(ctx, budget_usd)`; money-only since E5/ADR 0022 — tokens are reported,
  never a gate). On a batch the ceiling is the *remaining* application budget (`app_budget − spent`), so a
  ticket near the edge gets fewer cycles. Writes `incident_report.json` like any FSM halt. Distinct from the
  clean budget-stop below.
- **Application-budget exhaustion (clean stop, E5 — NO incident)** — `run_batch` halted *before* dispatching
  the next ticket because the remaining application budget fell to `PIPELINE_APP_BUDGET_FLOOR_USD`. **Tell:**
  `batch_state.json` has `budget_marker` set + a `🛑 App budget exhausted` audit line + `app_finops_report.json`
  present, but the would-be-next ticket has **no run dir / no `incident_report.json`** (nothing was spent on
  it). This is the budget working as designed, not a failure — the fix is to add money:
  `--resume <project> --budget <larger>` (the ceiling is never persisted, so it continues past the marker).
  Possibly a starvation signal: one expensive early ticket drained the shared pool.
- **Stuck retry loop** — same failure repeated across cycles until "Retries exhausted"; inspect WHY no
  channel/Arbiter route resolved it. An empty diagnostic payload and a Reviewer payload-on-an-approved-side
  are now structurally impossible (the `_require_routing_coherence` validator), and once the Arbiter fires
  (`attempt ≥ ARBITER_TRIGGER_ATTEMPT`) a `developer`/`qa` mis-route is auto-corrected by
  `reconcile_feedback_routing` (ADR 0024). So a genuine stuck loop now points at: a contract flaw the Arbiter
  didn't route to `contract`, a correct-but-unfixable repeated failure, or a mis-route that recurred on cycle 1
  (before the Arbiter is eligible) or that the Arbiter agreed with.
- **Developer CLI provider-quota exhaustion (infra halt — Claude session/usage limit)** — the agentic
  Developer's Claude CLI hit the subscription's rolling session/usage limit. **Tell:** a `You've hit your
  session limit · resets <time>` line in `sdlc_audit.log` (logged from `stream_claude_stdout`), the
  **Developer Agent billed `0t / $0.00` with a non-zero call count** (it printed the limit line and exited in
  ~2s without editing a file), and the now-distinct **`🚨 PROVIDER QUOTA HALT`** header + `incident_report.json`.
  This is an INFRASTRUCTURE block (the limit resets on a clock), NOT a Developer `production_bug` — detected at
  the boundary by `detect_claude_quota_block`, raised as `ClaudeCliQuotaExhausted` from `run_claude_cli`
  (`src/shared/utils/subprocess_helpers.py`), and fast-failed by the FSM via `_abort_with_incident` (so it no
  longer rides 3 cycles to "Retries exhausted" while the Reviewer/Arbiter misclassify the unchanged stub).
  **Diagnostic trap (pre-fix runs):** an OLDER run shows this as a `route=developer` / `root_cause=production_bug`
  loop with a `0t` Developer and a stub that "was never implemented" — the real cause is the session-limit line,
  not agent competence. The fix is operational (re-run after the reset window; on a batch, `--resume <project>`
  dispatches only the unmerged ticket), never an agent/prompt edit. The Gemini analog (structured roles, 403/429
  billing) is BACKLOG #27. Distinct from the **Stuck retry loop** above (which assumes the Developer actually ran).
- **Loop-closure (forge / `--auto-merge`) failure** — the cycle *succeeded* (all gates passed, atomic
  commit + push done) but `finalize_pr` failed at the GitHub seam (`src/shared/utils/forge.py`): a genuine
  `gh pr merge` failure (`sys.exit(1)`, no incident), a missing `gh`/`GITHUB_TOKEN` (preflight), an
  approval skipped for want of a separate `GITHUB_REVIEWER_TOKEN` (best-effort, expected), or a merge
  refused by *remote* required checks (falls back to a queued `--auto` merge). Fix the forge seam / env, not
  any agent — the generated code already passed. The E4 deploy-scaffold PR (`chore/devops-scaffold`) uses the
  same flow, so the same failure modes apply to a `<NNN>_devops_scaffold_…` run.
- **Infra git clone/push failure (`sys.exit(1)`, NO incident, NOT caught by the batch)** — a
  `🚨 <action> failed (exit …)` or `🚨 <action> timed out … (possible credential prompt / network hang)`
  from `_run_checked` (`runner.py`): the shallow-clone or push of the TARGET repo failed — bad/again-absent
  credentials (`GIT_TERMINAL_PROMPT=0`, so a private repo can't prompt → `could not read Password`),
  network, or a protected branch. It is a `SystemExit`, **not** a `PipelineHalt`, so `run_batch` does NOT
  catch it (the process dies; `batch_state.failed` stays as-was) and **no** `incident_report.json` is
  written — `--resume` recovers via the not-completed check. Fix the git auth/env (see
  [run-layout-and-cli](../../rules/run-layout-and-cli.md) "Git auth"), never an agent. Distinct from the
  loop-closure forge failure above (which is the `gh` PR/merge seam, *after* the gates passed).
- **Lint-gate failure (engine quality bar, step 3.6)** — the HARD lint gate (`run_lint_gate`) found a
  style/lint violation the agents couldn't clear within `LINT_GATE_MAX_REROUTES`, so it folded into the
  budgeted cycle and rode to "Retries exhausted". **Tell:** the `[LINT GATE FAILURE]` preamble in
  `error_trace`/`qa_error_trace` + a `🔶 Lint gate failed` audit line. NOT the deadlock guard (lint is
  excluded from it). Decide: is the finding genuinely unfixable by the agent (then the engine's `format_cmd`
  autofix should cover it — fix `environments.py`), or is the per-env `lint_cmd` itself wrong/too strict?
  Distinct from a *post-merge* red CI — if a generated repo's CI reddens on lint, the cause is an
  engine/CI `lint_cmd` mismatch (the `format_cmd`↔`lint_cmd` SSOT in `environments.py`, ADR 0020), never the
  clone. ALSO distinct from `🚨 ENVIRONMENT\LINT-TOOLING HALT` — there the linter BINARY couldn't run at all
  (bad flag / unknown subcommand / missing binary, `lint_failure_is_tooling`): an engine `lint_cmd`
  misconfig in `environments.py` that fails fast, not a findings loop.
- **Boundary crash / hang (escaped to `main()`, no incident)** — an `embedded null byte` `ValueError` from a
  control char in agent-authored text reaching a subprocess argv (fixed at the boundary by
  `sanitize_for_argv`; a *new* occurrence means a call site bypassed it); a `ValueError: Jinja templating is
  not supported in system messages with Google GenAI` from `{{ }}`/`{% %}` in a system prompt (fixed at the
  `llm.py` seam by `_relocate_jinja_system_messages`; a *new* occurrence means a role's system prompt grew a
  marker the relocation missed); or a structured-LLM call that hung (now bounded by `GEMINI_REQUEST_TIMEOUT`;
  a hang past that ceiling points at the client/timeout wiring). All are engine-boundary bugs, never an
  "LLM failure".

## Step 4 — Trace to the systemic flaw (never blame "the LLM")
Look for engine/prompt causes per the debugging-protocol: path-routing conflicts, strict-validation
contradictions in `prompts/system/`, broken parsing/glob in `src/shared/utils/`, contract gaps
(see the open `docs/BACKLOG.md` Part II `#NN` items, e.g. #19–#29), missing error precedence, or
boilerplate-recitation triggers.

## Output Format
A concise, scannable report:
1. **Outcome** — success/halt, which cycle, cost (from FinOps), key counters (`current_attempt`,
   `contract_amendments`, Arbiter `route` if any).
2. **Timeline** — what happened each cycle (agent → verdict → routing), citing the audit log.
3. **Root cause** — the one dominant class + the verbatim evidence (quote the finish_reason / analysis /
   gate line / contract field), and WHY a plain retry can't fix it.
4. **Fix location** — the exact `src/`/`prompts/` file(s) to change (and, where relevant, a `docs/BACKLOG.md`
   item). Explicitly NOT the clone.
5. **Recommendation** — the smallest durable fix, plus any bounded follow-up; present trade-offs and a
   single recommended option, then ask before large/architectural changes.
