# 0024 — Routing-Coherence Reconciler & Arbiter Channel Authority

## Status

Accepted (extends [0003](0003-dual-channel-observability.md), [0016](0016-arbiter-contract-self-healing.md); resolves BACKLOG #11, #18, #25 — pairs with the #17 validator)

## Context

The executor FSM recovers from a rejected cycle through **two physically isolated feedback channels**
(ADR 0003): `ctx.error_trace` → Developer, `ctx.qa_error_trace` → QA. The Developer cannot edit tests and
QA cannot edit production code, so *which* channel is fed each cycle decides whether the run converges or
deadlocks. That decision was governed **entirely by LLM-trust** — prompt text in `reviewer.md`/`arbiter.md`
with no code enforcement — and three live failure modes proved the trust was misplaced. They are three
symptoms of **one missing invariant**: the channel(s) driving the next cycle must be fed only on a
genuinely-rejected side, be grounded in real evidence, and agree with the authoritative diagnosis when the
Arbiter has spoken.

- **#11 — phantom production defects.** The Reviewer set `code_quality_approved=false` with a
  `dev_diagnostic_payload` citing defects that did not exist (e.g. "rename the `go.mod` module from `main`,
  fix circular imports" when the module name and imports were correct). The real fault was entirely in a
  test file. A Developer reroute was spent on a hallucination; verbatim-citation was never enforced.
- **#18 — channel isolation was prompt-only.** `reviewer.md` mandates "leave a payload empty when its
  approval is true," but the router copied **both** `dev_diagnostic_payload` and `qa_diagnostic_payload`
  unconditionally. If the Reviewer populated the wrong side (or both), the Developer and QA both acted next
  cycle and fought — one editing production while the other expected a test fix.
- **#25 — Arbiter `developer`/`qa` routes were advisory.** When the stuck-cycle Arbiter (ADR 0016)
  returned `route ∈ {developer, qa}`, the code fell through to the **Reviewer's** channel assignment — so a
  correct Arbiter verdict (observed: `route=qa, root_cause_class=test_bug`, a test mocking a function the
  streaming code never called) cost a Gemini call and changed nothing. Only `contract`/`halt` altered
  control flow.

## Decision

Introduce a **three-layer routing-coherence defense**, each at its correct seam, replacing the scattered
prompt-trust with code enforcement. Language-agnostic throughout (the engine layer operates only on
approval booleans and opaque diagnostic text — no per-language branching).

- **Layer 1 — model (structural coherence).** The `ReviewReport` validator (`src/shared/core/models.py`,
  renamed `_require_routing_coherence`) is extended from the #17 forward implication into a full
  **biconditional**: `payload non-empty ⟺ approval == false`, per side. The converse (an *approved* side
  must NOT carry a payload) is the code guard for #18. A new field `dev_evidence_citation` is **required
  non-empty when `code_quality_approved` is false** (#11) — a verbatim gate-output line or `FILE:`+excerpt.
  `instructor` re-prompts the Reviewer on any `ValueError`, so an incoherent report is corrected, not
  silently routed.
- **Layer 2 — engine reconciler (deterministic authority).** A pure SSOT
  `reconcile_feedback_routing(review_report, arbiter_verdict) → (dev_trace, qa_trace)`
  (`src/nexus/runner.py`) replaces the unconditional two-line payload copy. It (a) feeds a channel only for
  a genuinely-rejected side — the deterministic backstop for #18 even if a model-invalid report slips
  through; and (b) when an Arbiter verdict routes `developer`/`qa` and **disagrees** with which side the
  Reviewer rejected, moves the fix text (Arbiter `reasoning` + whatever payload the Reviewer wrote) into the
  Arbiter-chosen channel and clears the other (#25); on agreement the coherence-floored Reviewer payloads
  pass through unchanged. The verdict is honoured only for the cycle the Arbiter actually ran (a cycle-local
  `arbiter_verdict_this_cycle`, never the persisted `ctx.arbiter_verdict`). The FSM then **aligns
  `regenerate_tests` to the chosen channel** (`route == "qa"`) so the selected agent actually re-runs — a
  `qa` override forces test regeneration; a `developer` override suppresses it.
- **Layer 3 — prompts & observability.** `reviewer.md` gains a GROUNDED-EVIDENCE mandate (reject production
  only with a `dev_evidence_citation`; never infer an unevidenced structural defect) and a TEST-ONLY-FAILURE
  rule (every failing reference in a test file → default production to approved → route QA). `arbiter.md`
  states that `developer`/`qa` routes are now AUTHORITATIVE (so `route` must match `root_cause_class`).
  `reviewer.py` adds a **soft** grounding log (not a gate) when a production rejection's citation appears
  nowhere in the gate output or code snapshot.

## Consequences

- **Pros**: the feedback-routing invariant is now code-enforced rather than LLM-trusted — a payload can
  never drive a defect-free channel (#18), a production rejection cannot be a hallucination without a
  verbatim citation (#11), and the Arbiter's diagnosis finally changes control flow on the channels, not
  just on `contract`/`halt` (#25), so its cost is no longer wasted on a misroute. The reconciler is a single
  pure, unit-testable SSOT for channel assignment. New `ReviewReport.dev_evidence_citation` persists via the
  existing dump/load, so resume is unaffected. The engine layer stays language-agnostic.
- **Cons / constraints**: the `ReviewReport` contract is stricter, so the Reviewer can now incur an extra
  `instructor` retry when it emits an incoherent report or omits the citation (mitigated — the biconditional
  only enforces what `reviewer.md` already mandated, and the retry is far cheaper than a wasted budgeted
  cycle). The Arbiter override trusts the verdict's `route` over the Reviewer's payload placement; a
  misclassified `developer`/`qa` verdict now mis-routes deterministically (bounded by the `route` Literal,
  the `ARBITER_TRIGGER_ATTEMPT` threshold, and the financial breaker, as in ADR 0016). The grounding check
  is intentionally a soft log, not a gate, to avoid suppressing a legitimate static-review rejection whose
  evidence is a paraphrased code excerpt rather than a verbatim runtime line.
