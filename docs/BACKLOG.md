# Backlog

Open, deferred fixes surfaced across pipeline runs. Resolved items have been removed — their fixes
live in the code, tests, and `CHANGELOG.md`; only outstanding work remains. Original item numbers are
preserved so existing cross-references stay valid.

> Last reviewed 2026-06-18: pruned items resolved by subsequent design changes — **#10** (zombie
> disposal: `target_modules` is now contract-scoped via `is_testable_source(files_to_modify)`, so a
> genuinely removed module is never regenerated and the disposal sticks) and **#13** (manifest
> documentation: the design was reversed — `developer.md` now *requires* a top-of-file justification
> comment on build manifests, so the guardrail flagging an uncommented manifest is correct behavior).
> Items #17–#24 added from the PO→Reviewer pipeline contract analysis.

## 4. Restrict egress during the dependency-restore phase
**Why:** the dependency-restore phase (`setup_cmd`) runs with `--network bridge`. Package managers
execute install hooks (e.g. npm `postinstall`) → an exfiltration surface for LLM-authored code. Test
execution and SAST both stay `--network none` (SAST runs fully offline — its rules are vendored into
the image), so only restore keeps a network window.
**Fix direction:** route restore through an egress-restricted proxy (allowlist package registries),
or vendor dependencies offline, so no phase has unrestricted network.

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
leaving the matching payload `""`. Routing at [runner.py:1089-1092](src/executor/runner.py#L1089-L1092)
copies the empty trace; the agent re-runs next cycle with zero guidance, reproduces the same output, and
the loop burns all `max_retries` cycles until aborting "Retries exhausted."
**Cause:** no model/code invariant ties an approval to a non-empty payload. The deadlock guard
([runner.py:1070](src/executor/runner.py#L1070)) only catches `gate_failed ∧ approved_both`, never
`not approved ∧ empty payload`. Payload defaults are `""` ([models.py:244-245](src/shared/core/models.py)).
**Fix direction:** add a `ReviewReport` model validator — `not code_quality_approved ⇒ dev_diagnostic_payload != ""`
and the QA analog — so a guidance-less rejection fails fast with a debuggable validation error instead of
silently wasting the budget.

## 18. [P2] Feedback-channel isolation is enforced only by prompt, not by code
**Symptom:** `reviewer.md` mandates "never duplicate an instruction across both channels," but
[runner.py:1091-1092](src/executor/runner.py#L1091-L1092) copies BOTH `dev_diagnostic_payload` and
`qa_diagnostic_payload` unconditionally. If the Reviewer LLM populates both (or the wrong one), the
Developer and QA both act next cycle and can fight (dev edits production while QA expects a test fix).
**Cause:** the transport is isolated (`error_trace` vs `qa_error_trace`, reset each cycle at
[runner.py:816-817](src/executor/runner.py#L816-L817)), but *which* channel the Reviewer fills is an
LLM-trust invariant with no code guard.
**Fix direction:** validate routing coherence — e.g. a payload may be non-empty only when its own
approval is false (pairs naturally with #17), and log/incident when both are populated in one report.

## 19. [P1] `domain_tags[0]` and `environment_id` are validated individually, never against each other
**Symptom:** a `TechLeadContract` with `environment_id=go-1.23-cli` + `domain_tags=['python']` passes
both validators yet loads Python skills ([prompts.py:266](src/shared/core/prompts.py)) while every gate
runs the Go toolchain ([gates.py](src/executor/nodes/gates.py)) — split-brain execution.
**Cause:** skills route on `domain_tags[0]`; gates route on `environment_id`; nothing cross-checks that
the first tag is the language of the selected platform. Currently guarded only by `techlead.md` prose.
**Fix direction:** add a `TechLeadContract` model validator — `env_language(environment_id) == domain_tags[0]`.

## 20. [P1] SA's structured `environment_id` is discarded at the Nexus→executor boundary
**Symptom:** `run_sa` returns only `result.markdown`; [nexus_runner.py:72](src/nexus/nexus_runner.py#L72)
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
contract dump ([reviewer.py:23](src/executor/agents/reviewer.py#L23)), not `blueprint.md`. If the
TechLead drops an NFR from `architectural_constraints` or misreads the blueprint, no downstream agent can
detect the omission — they all inherit the flattened contract as ground truth.
**Fix direction:** feed `blueprint_markdown` to the Reviewer as a reference block so it can audit the
TechLead's extraction fidelity against the source, not just adjudicate the derived contract.

## 22. [P3] QA generates tests on cycle 1 with no production-code snapshot (by design)
**Symptom:** cycle 1 `needs_test_regeneration()` is True (no test snapshot, [models.py:283](src/shared/core/models.py#L283)),
so QA generates BEFORE the Developer ([runner.py:825-851](src/executor/runner.py#L825-L851)); the
`PRODUCTION CODE SNAPSHOT` block is absent ([qa.py:162](src/executor/agents/qa.py#L162)). Import
correctness on cycle 1 rests entirely on `topology_contract` precision.
**Note:** contract-first is intentional and `qa.md` says "when present, the PRODUCTION CODE SNAPSHOT"; the
post-Developer test-compile gate ([runner.py:991](src/executor/runner.py#L991)) catches resulting import
errors. Tracked as a known limitation, not a defect — monitor for cycle-1 import-collection failures that
trace back to thin/ambiguous topology nodes.

## 23. [P2] Abort path leaves staged changes in the run clone's index
**Symptom:** every reroute calls `git add -A` (in `build_production_snapshot`); `_abort_with_incident`
does `sys.exit(1)` with no `git reset`. The run clone is reused on `--resume`, so a resumed run starts
with a dirty index from the failed attempt. `finalize_transaction` only stages-and-commits on success.
**Fix direction:** `git reset` (or discard the worktree) in `_abort_with_incident` for clean resume hygiene.

## 24. [P3] Misleading comment on the QA-self zombie-disposal path
**Symptom:** [qa.py:231](src/executor/agents/qa.py#L231) labels the `suite.files_to_delete` disposal as
"Reviewer-routed", but that path is QA-self-identified; the Reviewer-routed disposal is the separate block
at [qa.py:126-129](src/executor/agents/qa.py#L126-L129). Both call the same idempotent guarded
`_dispose_zombie_tests`, so behavior is correct — only the comment is wrong.
**Fix direction:** relabel the [qa.py:231](src/executor/agents/qa.py#L231) comment to "QA-self-identified
obsolete files" to match the dual-path reality already documented in `qa.md`.
