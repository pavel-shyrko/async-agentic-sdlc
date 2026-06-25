---
name: tbf-code-quality
description: Audit the code quality and test quality/coverage of a generated application in a completed executor run's clone. Use when the user asks to review generated code, check test coverage or quality, audit the output application, or assess "how good is the code in run X". Accepts a run dir, a project slug (picks latest exec run), or a run number NNN. Complements tbf-analyze-run (which diagnoses FSM failures); this skill is for assessing the output code of a successful or partially-successful run.
context: fork
---

# Application Code & Test Quality Audit

## Context
Reads the generated application clone and the run's gate/telemetry artifacts to produce an
evidence-based quality assessment. **Reading** the clone is expected and required here — it is the
primary artifact under audit. Only *mutating* the clone is forbidden (workspace guardrails).

Path note: use the drive-letter Windows path (`C:\…`) with Read/Grep tools; a verbatim `/mnt/c/…` path
from the Bash tool fails. See [run-tests-via-wsl](../../rules/run-tests-via-wsl.md).

## Step 1 — Locate the run
- If given a run dir path, use it directly.
- If given a project slug, find all `<NNN>_exec_<ticket>_…` dirs under `runs/<slug>/`; the highest
  `<NNN>` is the newest. For a multi-ticket batch, read `batch_state.json` in the `nexus_plan` run to
  get `completed` (merged tickets) — audit each or pick the one the user specified.
- If given a run number NNN, find the matching `<NNN>_exec_…` dir.
- Layout SSOT: [run-layout-and-cli](../../rules/run-layout-and-cli.md).

## Step 2 — Gather artifacts (in this order)
1. **Checkpoint** — `reports/checkpoint.json`:
   - `contract`: `files_to_modify` (expected files), `function_signatures` (expected API surface),
     `topology_contract` (import rules), `environment_id` (language/stack), `architectural_constraints`,
     `core_libraries`, `instruction` (ticket summary).
   - `review_report`: `code_quality_approved`, `test_integrity_approved`, `code_quality_analysis`,
     `test_integrity_analysis`, `log_verification_analysis`, `dev_evidence_citation`,
     `zombie_tests_to_delete`.
   - `current_attempt`, `contract_amendments` (cycle count).
2. **Clone** — `repo/` directory:
   - List files in `src/` (or the env's source root) and `tests/` (or the env's test root).
   - For each file in `files_to_modify`: confirm it exists in the clone (`✓` / `✗`).
   - For each `function_signatures` entry: grep the relevant file for the function/method name.
   - Check `topology_contract` import rules: grep key source files for the expected import structure.
3. **Audit log** — `logs/sdlc_audit.log` — grep for:
   - `[LINT GATE]` / `🔶 Lint gate` — lint pass/fail status and reroute count.
   - `[SAST]` / `bandit` / `semgrep` — SAST severity counts.
   - `[QA GATE]` / test runner output — test pass/fail counts, coverage percentage (e.g. `TOTAL … 87%`).
   - `🔷 Orchestration cycle N/M` — how many cycles were needed.
   - `[TOKENS]` — per-agent call counts (high Developer calls relative to cycles = reroute churn).
4. **FinOps** — `reports/finops_report.json`:
   - Developer call count (`calls`), Developer cost vs total cost.
   - Flag anomaly: Developer `calls > 0` but `0t / $0.00` → blocked (quota/crash) — defer to `/tbf-analyze-run`.
5. **Reviewer analysis** (from checkpoint `review_report`):
   - `code_quality_analysis` — the Reviewer's final production-code assessment.
   - `test_integrity_analysis` — the Reviewer's final test assessment.
   - `log_verification_analysis` — the Reviewer's gate-output interpretation.
   - `dev_evidence_citation` — verbatim gate line that triggered the last production rejection (if any).

## Step 3 — Analyze and report

### Contract compliance
- List each `files_to_modify` entry as `✓ present` or `✗ missing` (check `repo/` clone).
- For each `function_signatures` entry: `✓ found` (grep hit) or `✗ absent`.
- Note any `topology_contract` import violations detected via grep.
- Verdict: **COMPLIANT** / **PARTIAL** (some files/sigs missing) / **NON-COMPLIANT**.

### Code quality
- Cite the Reviewer's `code_quality_analysis` verbatim (it is the most informed final assessment).
- Lint gate: `CLEAN` / `FINDINGS (<N> reroutes, violations: …)` / `FAILED (rode to retries)`.
- SAST: `CLEAN` / `LOW:<N> MED:<N> HIGH:<N>` from audit log.
- If `dev_evidence_citation` present: quote it — it is the verbatim gate line that drove the last rejection.

### Test quality
- Cite the Reviewer's `test_integrity_analysis` verbatim.
- Test run from audit log: total count, pass/fail; coverage % if present.
- `zombie_tests_to_delete` count if any (stale tests the Reviewer flagged; cleaned before the final snapshot).
- Verdict: **SOLID** / **ADEQUATE** / **WEAK** (low coverage, QA-rejected multiple times).

### Efficiency
- `current_attempt` N / `MAX_FUNCTIONAL_RETRIES` 3 (+ `contract_amendments × AMENDMENT_RETRY_BONUS`).
- `contract_amendments` (TechLead self-healing cycles consumed).
- Developer cost as % of total run cost.
- Flag high-reroute count (lint gate or guardrail loops in audit log) as a signal of prompt/contract friction.

### Overall verdict
- **PASS** — all gates passed, Reviewer approved both sides, contract fully compliant.
- **PASS WITH NOTES** — passed but with lint/SAST residue, high cycle count, or partial sigs.
- **FAILED** — run halted (incident written). For root-cause diagnosis, run `/tbf-analyze-run`.

## Output Format
1. **Application** — ticket ID, `environment_id`, one-line instruction summary.
2. **Contract compliance** — file and signature table (`✓`/`✗`).
3. **Code quality** — Reviewer analysis + lint/SAST status.
4. **Test quality** — counts, coverage, integrity verdict.
5. **Efficiency** — cycles, amendments, cost split.
6. **Overall verdict** + **Recommendations** (or "No issues found.").
