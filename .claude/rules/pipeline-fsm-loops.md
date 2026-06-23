---
paths:
  - "src/executor/runner.py"
---

# Executor FSM: cycle, loops, channels, termination

SSOT: `src/executor/runner.py` `run_executor()` — the per-ticket FSM (bootstrap/resume → TechLead → the
self-heal cycle → finalize). `main()` is now a thin dispatcher that resolves the run and calls it. For
`--idea --auto-execute` (E3, ADR 0019) the bridge is **`run_batch`**, an outer loop *above* `run_executor`:
it drives ALL planned tickets to `main` in TPM order (one merged ticket at a time, `--auto-merge` implied),
checkpoints progress to `batch_state.json`, and stops on the first `PipelineHalt`. After a clean batch, if
`--scaffold-deploy` is set, **`run_devops_scaffold`** runs once as a post-batch terminal phase (E4, ADR 0020):
it clones `main` onto `chore/devops-scaffold`, has the `devops` agent emit `DevOpsManifests`, static-lints
them (`run_devops_gate`, 1 self-heal retry), and merges via the same `finalize_pr` forge flow — it is NOT
part of the per-ticket FSM cycle. The control-plane (PO→SA→TPM) is linear with no loops; all cycling lives
here. Related: [repo-module-map](repo-module-map.md),
[agent-contracts](agent-contracts.md), [config-constant-convention](config-constant-convention.md).

## Outer cycle
`while ctx.current_attempt <= MAX_FUNCTIONAL_RETRIES + ctx.contract_amendments * AMENDMENT_RETRY_BONUS` —
a **dynamic ceiling** recomputed each iteration from persisted state, so an Arbiter contract amendment
(ADR 0016) grants extra cycles and `--resume` recomputes the identical bound. `MAX_FUNCTIONAL_RETRIES`
(env `PIPELINE_MAX_RETRIES`, default 3) is a module constant. `current_attempt` is bumped **before**
`save_checkpoint`, so a resumed run never re-spends a cycle. Phase order inside one cycle:
1. financial breaker → reset BOTH feedback channels (save `prev_dev_trace`/`prev_qa_trace`, clear `error_trace`/`qa_error_trace` to `""`).
2. `skip_developer = regenerate_tests AND not prev_dev_trace AND review_report is not None`.
3. **QA generate + signature-lint** — only when `regenerate_tests` (see below).
4. **Developer + guardrails** — unless `skip_developer`.
5. financial breaker → **QA test-compile gate** → **lint gate (step 3.6)** → `parallel(run_qa_unit_tests, run_security_scan)`.
6. **Reviewer** → financial breaker → decision/routing → checkpoint.

`regenerate_tests = ctx.needs_test_regeneration()` (`models.py`): True when the last review rejected
tests **OR no test snapshot exists yet**. So on **cycle 1 QA generates tests BEFORE the Developer runs**
(contract-first); `production_code_snapshot` is empty then — QA works from the contract + topology only.

`all_gates_passed = qa_success ∧ sec_success ∧ lint_success ∧ code_quality_approved ∧ test_integrity_approved`.
On `not all_gates_passed`: `error_trace ← dev_diagnostic_payload`, `qa_error_trace ← qa_diagnostic_payload`
(both `_cap_text`-capped); if `not test_integrity_approved` → `regenerate_tests = True` for next cycle. When
lint stayed red after its fast-fail budget, the classified lint findings are **re-applied** to the channels
after the Reviewer routes (the Reviewer is lint-blind), so the next budgeted cycle gets real feedback.

## The six loops
Only the **outer retry** loop consumes functional budget; the five inner loops are FREE fast-fail
reroutes that bypass the (expensive) Reviewer until they clear or hit their cap.
- **Outer retry** — dynamic bound `MAX_FUNCTIONAL_RETRIES + contract_amendments * AMENDMENT_RETRY_BONUS`; driven by Reviewer rejection / gate failure.
- **QA signature-lint** — bound `QA_LINT_MAX_REROUTES`; runs when `regenerate_tests`; `lint_test_suite_consistency` vs contract signatures.
- **Developer guardrail** — bound `GUARDRAIL_MAX_REROUTES`; three checks in sequence: missing contract files → documentation-justification (`enforce_documentation_guardrail`) → compile gate (`run_build_gate`).
- **QA test-compile gate** — bound `QA_GATE_MAX_REROUTES`; only TEST-only compile failures reroute to QA; env/network or production-referencing failures fall through to the Reviewer.
- **Lint gate (step 3.6)** — bound `LINT_GATE_MAX_REROUTES` (env `PIPELINE_LINT_MAX_REROUTES`, default 2); `run_format_pass` autofix → `run_lint_gate` verify → `classify_lint_findings` splits findings prod→Developer / test→QA (no functional budget), with a no-progress break. `lint_success` is a HARD gate (folds into `all_gates_passed`); deliberately NOT in the deadlock guard, so a persistent lint nit rides the budgeted cycle rather than fast-failing as an env misconfig.
- **Compile env-retry** — bound 1; an environmental/network build error retries once, else hard-halt.

## Two isolated feedback channels
`ctx.error_trace` → Developer only (from `ReviewReport.dev_diagnostic_payload`); `ctx.qa_error_trace` →
QA only (from `qa_diagnostic_payload`). Reset every cycle; consumed by `run_developer_node` /
`run_qa_agent_node`. The Developer can't edit tests and QA can't edit production code, so mis-routing
deadlocks the run. NOTE: the isolation is enforced by the Reviewer prompt, not by code — the router
copies both payloads unconditionally (hardening: docs/BACKLOG.md #18). Distinct from the
CLAUDE.md-vs-prompts boundary in [feedback-context-isolation](feedback-context-isolation.md).

## Termination states
- **Success** — `run_techwriter_node` (updates the living ADR) → `finalize_transaction` (atomic commit + optional push) → (E2, only with `--auto-merge`) `finalize_pr` (open → best-effort approve → squash-merge the PR into base, via `src/shared/utils/forge.py`) → return. `finalize_pr` is wrapped so the FinOps report/summary still print on a merge failure; a *genuine* `merge_pr` failure `sys.exit(1)`s **without** an `incident_report.json` (it is not an FSM halt — the gates already passed). A halted ticket never reaches the PR step (no PR on failure).
- **Retries exhausted** — loop ends → `_abort_with_incident("Retries exhausted")`.
- **Financial breaker** — `enforce_financial_circuit_breaker` at 6 checkpoints; gates primarily on `PIPELINE_BUDGET_USD` (see [token-budget-excludes-cache](token-budget-excludes-cache.md)).
- **Hard-halt** — misplaced contract file at cap, persistently undocumented new file, or persistent environmental build error.
- **Deadlock guard** — gate FAILED but Reviewer approved BOTH code and tests (no agent-fixable defect) → fail fast instead of looping to the breaker.

Abort (`_abort_with_incident`) writes `reports/incident_report.json` + FinOps, then **raises
`PipelineHalt`** (E3, ADR 0019) — NOT a bare `sys.exit(1)`. A single-ticket run lets it bubble to the
`main.py` entrypoint guard (`except PipelineHalt: sys.exit(1)`), so the exit code is unchanged; a `run_batch`
run **catches** it to record the `failed` ticket in `batch_state.json` and stop the batch (then exit 1).
Only FSM halts become `PipelineHalt`; infra `sys.exit(1)`s (`_run_checked` clone/push, the `finalize_pr`
merge failure above) stay `SystemExit` and are NOT caught by the batch (they kill the process; `--resume`
recovers via the not-completed check). Abort does NOT `git reset` the staged run clone (resume hygiene gap —
docs/BACKLOG.md #23). Debug entry: [debugging-protocol](debugging-protocol.md).
