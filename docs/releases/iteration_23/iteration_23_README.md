# Iteration 23 — Convergence hardening: behavioral oracle, raw-runner feedback, repo-aware test topology, routing-coherence reconciler

> ADR: [0024-routing-coherence-reconciler](../../decisions/0024-routing-coherence-reconciler.md)
> (extends [0003](../../decisions/0003-dual-channel-observability.md),
> [0016](../../decisions/0016-arbiter-contract-self-healing.md)) ·
> CHANGELOG: [v0.24.0](../../../CHANGELOG.md) · Practicum: [PRACTICUM.md](../../../PRACTICUM.md)

> **Archive note:** this archive was reconstructed during the iteration-24 release (the iteration_23 folder
> was not created when v0.24.0 shipped on 2026-06-24). Its authoritative record is the
> [v0.24.0 CHANGELOG entry](../../../CHANGELOG.md) and ADR 0024.

## Problem Statement

Two real `json-to-csv` runs (python + .NET) exposed a cluster of **convergence** failures — the engine
either looped, rerouted the wrong agent, or accepted weak tests — all rooted in the dual-channel feedback
contract (ADR [0003](../../decisions/0003-dual-channel-observability.md)) being **prompt-trusted rather than
code-enforced**:

- A Reviewer could **hallucinate a production defect** (e.g. "rename the go.mod module") with no evidence and
  burn a Developer reroute on a phantom (#11).
- The two isolated feedback channels were isolated **only by prompt**: an *approved* side could still carry a
  payload, so the router fed a defect-free channel and the Developer + QA fought each other (#18).
- The Arbiter's `developer`/`qa` verdicts were **advisory** — they cost a Gemini call and changed nothing,
  falling through to a Reviewer misroute (#25).
- A rejection could arrive **without guidance** (empty diagnostic payload) and silently burn the whole retry
  budget to "Retries exhausted" (#17).
- QA was **rerouted blind**: when the suite failed at runtime, the channel relied on the LLM's re-derivation
  of the failure instead of the authoritative runner output, which looped the run when that payload was thin.
- Tests were independently *guessing* the expected answer (drifting from the code), and on TASK-02+ of a
  multi-ticket .NET batch the test project was **orphaned** (→ `ran_zero_tests` halt) because a follow-on
  ticket didn't re-list the manifest.

## Implemented Solutions

### A — Routing-coherence reconciler & evidence citation (#11/#18/#25) — ADR 0024
A single engine SSOT **`reconcile_feedback_routing`** ([src/nexus/runner.py](../../../src/nexus/runner.py))
assigns the two feedback channels: it feeds a channel ONLY for a genuinely-rejected side (#18) and lets an
Arbiter `developer`/`qa` verdict **override** a Reviewer misroute (#25). A new
`ReviewReport.dev_evidence_citation` (verbatim gate line or code excerpt) is REQUIRED to reject production
code, closing the phantom-defect reroute (#11). The `ReviewReport` validator is now a full **biconditional**
(`payload non-empty ⟺ approval false`).

### B — Behavioral oracle in the contract
`TechLeadContract.acceptance_examples: list[BehaviorExample]` (`{input, expected, raises}`) — the TechLead
pins the few decisive golden cases (empty/degenerate inputs, library-defined output, boundaries). QA asserts
them **verbatim** (the expected value is fixed ONCE, not independently guessed by tests and code); the
Reviewer adjudicates against them (a test contradicting an example → Developer; an altered example → QA; a
wrong example → contract amendment). QA keeps full freedom to add its own BVA/equivalence cases on top
(oracle floor + creative coverage). Language-neutral DATA — no stack assumptions. Prompts: `techlead.md`,
`qa.md`, `reviewer.md`; injected in `qa.py`.

### C — Repo-aware test-project resolution
`resolve_test_project_dir` resolves a `layout=="project"` (.NET) test project from the **existing clone**
when a follow-on ticket doesn't re-list the manifest — the root cause of orphaned tests on TASK-02+. The
manifest pattern is registry-driven (`test_manifest_suffix`; `None`/no-op for python/go/node), so the engine
stays language-agnostic; multiple matches disambiguate **by name** with a deterministic
shallowest-then-lexical tie-break.

### D — QA is never rerouted blind
When the suite fails at runtime, the QA channel now carries the authoritative runner output (verbatim
expected-vs-actual) **appended** to the Reviewer's transcription, instead of relying on the LLM's
re-derivation alone ([src/nexus/runner.py](../../../src/nexus/runner.py)).

### E — Guidance-or-fail (#17)
A new `ReviewReport` model validator fails fast (instructor re-prompts the Reviewer) when a side is rejected
with an empty diagnostic payload — the code-enforced half of the long-standing prompt-only invariant.

## Metrics / Logs Analysis

- **Diff footprint** (`ab35819` v0.23.0 boundary → `v0.24.0`): engine + prompts **21 files, +752 / −159** —
  chiefly `src/nexus/runner.py` (+177: `reconcile_feedback_routing`, the raw-runner feedback append),
  `src/shared/core/environments.py` (+244: `test_manifest_suffix` + registry hardening),
  `src/shared/core/models.py` (+84: `BehaviorExample`, the `ReviewReport` biconditional + citation),
  `src/development/gates.py` (+94: repo-aware test resolution). Plus **+933** test insertions across 11
  framework suites (`test_models`, `test_orchestrator`, `test_qa_agent`, `test_gates`, …).
- **Resolved BACKLOG items:** #11, #17, #18, #25 (pairs with #17).

> Validate locally via WSL (from the repo root):
> `wsl -e bash -lc "source venv/bin/activate && GEMINI_API_KEY=test-key python3 -m unittest discover -s tests"`
