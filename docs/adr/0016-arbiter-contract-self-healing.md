# 0016 — Arbiter Agent: Autonomous Contract Self-Healing (3rd FSM Route)

## Status

Accepted (extends [0001](0001-baseline-sequential-loop.md), [0003](0003-dual-channel-observability.md), [0006](0006-fsm-state-serialization-resume.md))

## Context

The executor FSM (`src/executor/runner.py` `main()`) recovers from a rejected cycle through exactly
**two isolated feedback channels** (ADR 0003): `error_trace` → Developer, `qa_error_trace` → QA. The
**TechLead runs once** before the retry loop and is skipped whenever `ctx.contract` already exists — so
the contract is, in practice, **immutable for the life of a run**.

A real ticket (JSON→CSV `analyze_headers`, streaming `ijson`) exposed the structural gap behind a
`CIRCUIT BREAKER OPEN: Retries exhausted` halt:

- The **contract itself encoded a flawed algorithm** — `instruction`: "read the first `ijson.parse`
  event; if not an array, raise `MalformedStructureError`". For incomplete input (`{`, `{"a": 1`) the
  first event is `start_map`, so the code raised `MalformedStructureError` while the QA test (correctly)
  expected `JSONDecodeError`.
- The contract listed **overlapping `Raises`** (`MalformedStructureError` *and* `JSONDecodeError`) with
  **no precedence** for an input that is both non-array and syntactically invalid.
- The Reviewer's only repair suggestion (`json.loads` the whole file) **violated the O(1)/streaming
  `architectural_constraints`** — trading one gate failure for another.

No agent could fix this: the Developer is bound by the contract, QA's tests were already correct, and
the contract is unreachable mid-run. Every cycle re-ran identically until the breaker. The existing
deadlock guard only catches the *opposite* shape (gate fails but Reviewer approved both).

## Decision

Add an **Arbiter agent** that triages a *stuck* cycle and introduces a **third routing target — the
contract** — autonomously amending the TechLead spec, bounded conservatively, with the existing cascade
machinery re-validating the result. Pair it with upfront prompt hardening so the first contract is
better and the amendment converges to working code instead of merely escalating.

- **Arbiter agent** (`src/executor/agents/arbiter.py`, role `arbiter` in `ROLE_MODELS`,
  `prompts/system/arbiter.md`). It returns a structured `ArbiterVerdict{root_cause_class, route,
  reasoning, contract_amendment_directive}` (`src/shared/core/models.py`). `route ∈
  {developer, qa, contract, halt}`: `developer`/`qa` fall through to the existing channels; `contract`
  triggers a TechLead amendment; `halt` aborts with an incident.
- **Conditional trigger (cost-bounded)** — the Arbiter runs only on a failed cycle at
  `attempt ≥ ARBITER_TRIGGER_ATTEMPT` (default 2). Cycle-1 failures still route through the cheap
  Developer/QA channels (as a normal self-heal), so the extra agent call is paid only once the loop is
  demonstrably stuck.
- **Contract amendment via TechLead** — `run_techlead_node(ctx, amendment_feedback=…)` gains an
  amendment mode: given the failing contract + the Arbiter directive + the evidence, it re-emits a
  REVISED `TechLeadContract`. The runner then **pins `environment_id`** to its pre-amendment value.
- **Conservative bounds** — `MAX_CONTRACT_AMENDMENTS` (default **1**) caps autonomous rewrites per run;
  a further `contract` verdict downgrades to `halt`. `environment_id` is **never mutated** (the
  Blueprint fixes the platform), which keeps the highest-cascade field — sandbox image, build/test
  gates, QA layout — frozen. Each amendment grants `AMENDMENT_RETRY_BONUS` (default 2) extra cycles so
  the re-derived contract gets a fair shot; the financial breaker remains the absolute ceiling.
- **Cascade re-validation reuses existing safeguards** — after an amendment the runner sets
  `regenerate_tests = True`, clears both feedback channels, and resets `review_report`, then `continue`s
  to a fresh cycle. QA regenerates tests against the amended signatures (re-checked by the QA
  signature-lint loop), the Developer re-runs (re-checked by the missing-files / compile guardrail
  loop), and the `TechLeadContract` field validators re-run on the amended contract.
- **Loop budget hoisted** — the outer `for attempt in range(…, max_retries+1)` (a bare
  `max_retries = 3` literal — the long-standing config-convention outlier) becomes a `while` over a
  **dynamic ceiling** `MAX_FUNCTIONAL_RETRIES + contract_amendments * AMENDMENT_RETRY_BONUS`, recomputed
  from persisted state so `--resume` is identical. `MAX_FUNCTIONAL_RETRIES` is now an env-overridable
  module constant.
- **Upfront prompt hardening** (so amendment fixes the spec, not just escalates):
  `techlead.md` gains an **ERROR PRECEDENCE** rule (overlapping `Raises` must declare precedence; never
  short-circuit before the parser surfaces a more specific error) + an **AMENDMENT MODE** section;
  `reviewer.md` gains a **CONSTRAINT-RESPECTING REPAIR** rule (a fix that breaks a stated NFR is invalid
  — name the contract conflict instead, so it routes to an amendment); `engineering_guide.md` adds the
  language-neutral drain-the-incremental-parser idiom for error precedence under a streaming/O(1)
  constraint.

## Consequences

- **Pros**: a flawed contract is no longer a guaranteed breaker — the pipeline can repair its own spec
  once, autonomously, and converge (closes the `analyze_headers` class of failure end-to-end); the
  third route makes "the spec is wrong" a first-class outcome instead of an invisible infinite loop;
  pinning `environment_id` + a 1-amendment cap bounds both blast radius and cost; the FSM gains the
  long-overdue tunable retry budget. New `GlobalPipelineContext` fields (`arbiter_verdict`,
  `contract_amendments`) persist via the existing dump/load, so resume is unaffected.
- **Cons / constraints**: the contract is now **mutable mid-run**, so checkpoints from before vs. after
  an amendment describe different specs (the `contract_amendments` counter disambiguates); an amendment
  re-runs QA + Developer, so it is not free (mitigated by the cap, the trigger threshold, and the
  financial breaker); the Arbiter's classification is prompt-governed (a misclassification could amend a
  contract that was actually fine, or halt one that was fixable) — bounded but not eliminated by the
  `route` Literal + the single-amendment cap; and the cascade re-validation is *defensive* (relies on
  the QA-lint and guardrail loops to catch downstream drift) rather than a formal contract-diff, since
  `environment_id` pinning removes the only change that would otherwise require re-selecting the sandbox.
