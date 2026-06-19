---
name: analyze-run
description: Diagnose a pipeline run (executor or Nexus) from its persisted artifacts — classify root cause, cite evidence, and point the fix at the engine/prompts (never the clone). Use when the user asks to analyze/diagnose a run, explain a CIRCUIT BREAKER / "Retries exhausted" halt, a looping or stuck cycle, a Gemini RECITATION/SAFETY block, or "what happened" in a runs/<project>/<NNN>_... run. Accepts a run dir, a project slug, or pasted run log output.
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

## Step 2 — Gather state (in this order)
1. **Checkpoint** — `reports/checkpoint.json`. Executor (`GlobalPipelineContext`): `current_attempt`,
   `contract` (the TechLead spec — `instruction`, `function_signatures`, `architectural_constraints`,
   `files_to_modify`, `environment_id`, `topology_contract`), `review_report`
   (`code_quality_approved`/`test_integrity_approved` + `code_quality_analysis`/`test_integrity_analysis`/
   `log_verification_analysis` + `dev_diagnostic_payload`/`qa_diagnostic_payload`), `error_trace`/
   `qa_error_trace`, and the Arbiter fields `arbiter_verdict{root_cause_class,route,reasoning,
   contract_amendment_directive}` + `contract_amendments`. Nexus (`NexusState`): `completed_phase`,
   `epic_text`/`blueprint_text`/`tasks`.
2. **Audit log** — tail `logs/sdlc_audit.log` (last ~50–100 lines): trace the FSM transitions and which
   agent/cycle failed.
3. **Incident report** — `reports/incident_report.json` (present only on a halt): the redacted final state
   + the halt header.
4. **FinOps** — `reports/finops_report.json` (per-agent token/USD + cumulative).
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
- **Financial circuit breaker** — cumulative USD/token budget breached (`enforce_financial_circuit_breaker`).
- **Stuck retry loop** — same failure repeated across cycles until "Retries exhausted"; inspect WHY no
  channel/Arbiter route resolved it (often a mis-route, an empty diagnostic payload, or a contract flaw).

## Step 4 — Trace to the systemic flaw (never blame "the LLM")
Look for engine/prompt causes per the debugging-protocol: path-routing conflicts, strict-validation
contradictions in `prompts/system/`, broken parsing/glob in `src/shared/utils/`, contract gaps
(see `docs/BACKLOG.md` #17–#26), missing error precedence, or boilerplate-recitation triggers.

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
