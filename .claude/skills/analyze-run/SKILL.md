---
name: analyze-run
description: Diagnose a pipeline run (executor or Nexus) from its persisted artifacts — classify root cause, cite evidence, and point the fix at the engine/prompts (never the clone). Use when the user asks to analyze/diagnose a run, explain a CIRCUIT BREAKER / "Retries exhausted" halt, an application-budget exhaustion / `budget_marker` clean stop (`--budget` / `PIPELINE_APP_BUDGET_USD`, E5), a looping or stuck cycle, a Gemini RECITATION/SAFETY block, a PR/merge (forge) failure under `--auto-merge`, a lint-gate reroute loop or an E4 deploy-scaffolding (`--scaffold-deploy`) static-lint halt, a non-halt crash/hang (an `embedded null byte` traceback, a Jinja-in-system-message `ValueError`, or a stalled agent call that printed no incident), or "what happened" in a runs/<project>/<NNN>_... run. Accepts a run dir, a project slug, or pasted run log output.
---

# Pipeline Run Analysis

## Context
Operationalizes the diagnostic procedure in [debugging-protocol](../../rules/debugging-protocol.md) and
the control-flow reference in [pipeline-fsm-loops](../../rules/pipeline-fsm-loops.md). The goal is an
EVIDENCE-FIRST root-cause analysis: never assume "the LLM just failed." Locate the systemic engine/prompt
flaw, then recommend a fix in `src/`/`prompts/` — NEVER edit the generated clone
(`runs/<project>/<NNN>_exec_…/repo/`), per the workspace guardrails.

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
2. **Audit log** — tail `logs/sdlc_audit.log` (last ~50–100 lines): trace the FSM transitions and which
   agent/cycle failed.
3. **Incident report** — `reports/incident_report.json` (present only on an FSM halt): the redacted final
   state + the halt header. **Tell:** a run that printed the FinOps GRAND TOTAL and then died with a raw
   Python traceback (and **no** incident report) is *not* an FSM halt — it is an uncaught exception that
   escaped to `main()` **after** the gates passed: a loop-closure (`finalize_pr`/`gh` merge) failure, an
   `embedded null byte` argv crash, or (pre-`GEMINI_REQUEST_TIMEOUT`) a stalled call. Read the traceback's
   frame, not the absent incident.
4. **FinOps** — `reports/finops_report.json` (per-agent token/USD/time + per-plane + cumulative); for a batch
   also the `nexus_plan` run's `reports/app_finops_report.json` (application-wide: Nexus + all tickets + DevOps).
5. **Gate output** — for a test/build/SAST failure, read the raw runner output captured in the log /
   checkpoint (`_extract_failure_context`).

## Step 3 — Classify the root cause
Map the evidence to one class (decisive — pick the dominant one and say so):
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
  TechLead amendment (ADR [0016](../../../docs/decisions/0016-arbiter-contract-self-healing.md)).
- **Environment/runner misconfiguration** — a hard gate FAILED while the Reviewer approved BOTH sides
  (deadlock guard, `runner.py`): not agent-fixable (e.g. sandbox import-path/network).
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
- **Loop-closure (forge / `--auto-merge`) failure** — the cycle *succeeded* (all gates passed, atomic
  commit + push done) but `finalize_pr` failed at the GitHub seam (`src/shared/utils/forge.py`): a genuine
  `gh pr merge` failure (`sys.exit(1)`, no incident), a missing `gh`/`GITHUB_TOKEN` (preflight), an
  approval skipped for want of a separate `GITHUB_REVIEWER_TOKEN` (best-effort, expected), or a merge
  refused by *remote* required checks (falls back to a queued `--auto` merge). Fix the forge seam / env, not
  any agent — the generated code already passed. The E4 deploy-scaffold PR (`chore/devops-scaffold`) uses the
  same flow, so the same failure modes apply to a `<NNN>_devops_scaffold_…` run.
- **Lint-gate failure (engine quality bar, step 3.6)** — the HARD lint gate (`run_lint_gate`) found a
  style/lint violation the agents couldn't clear within `LINT_GATE_MAX_REROUTES`, so it folded into the
  budgeted cycle and rode to "Retries exhausted". **Tell:** the `[LINT GATE FAILURE]` preamble in
  `error_trace`/`qa_error_trace` + a `🔶 Lint gate failed` audit line. NOT the deadlock guard (lint is
  excluded from it). Decide: is the finding genuinely unfixable by the agent (then the engine's `format_cmd`
  autofix should cover it — fix `environments.py`), or is the per-env `lint_cmd` itself wrong/too strict?
  Distinct from a *post-merge* red CI — if a generated repo's CI reddens on lint, the cause is an
  engine/CI `lint_cmd` mismatch (the `format_cmd`↔`lint_cmd` SSOT in `environments.py`, ADR 0020), never the
  clone.
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
(see `docs/BACKLOG.md` #19–#28), missing error precedence, or boilerplate-recitation triggers.

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
