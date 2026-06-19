# Iteration 16 — Arbiter: Autonomous Contract Self-Healing & Recitation Resilience

> ADR: [0016-arbiter-contract-self-healing](../../adr/0016-arbiter-contract-self-healing.md) ·
> CHANGELOG: [v0.16.0](../../../CHANGELOG.md) · Practicum:
> [PRACTICUM.md](../../../PRACTICUM.md)

## Problem Statement

Running the JSON→CSV demo project end-to-end surfaced two failure classes that the engine could not
recover from — each burning the budget into a halt rather than self-healing.

1. **Gemini RECITATION halted the Nexus TPM phase.** The control-plane planning run died at the TPM
   phase: Gemini's recitation filter blocked the output 3× and the run aborted. Two compounding causes —
   (a) the retry layer treated the block as transient and retried the identical, identically-blocked
   prompt 3× with exponential backoff; (b) the TPM prompt told the model to reproduce the **full literal
   MIT `LICENSE`** and the **verbatim `.gitignore`** into `TASK-01` — exactly the canonical training-data
   text the recitation filter flags.

2. **A flawed TechLead contract looped the executor to the circuit breaker.** `TASK-03` (`analyze_headers`,
   streaming `ijson`) hit `CIRCUIT BREAKER OPEN: Retries exhausted`. The defect was *structural*: the
   contract `instruction` mandated raising `MalformedStructureError` on the first parse event, but `{` /
   `{"a": 1` are **both** a non-array root AND invalid JSON, with **no error precedence** declared — so no
   implementation could satisfy both the structure and the syntax-error expectations. The FSM has only two
   feedback channels (`error_trace`→Developer, `qa_error_trace`→QA) and the TechLead runs **once** before
   the loop, so a flawed contract is unreachable: every cycle re-looped Developer/QA until the breaker.

The deeper gap behind #2: the FSM had no path to say "the **spec** is wrong." Every rejection was assumed
agent-fixable, so a contract-level contradiction was an invisible infinite loop.

## Implemented Solutions

### Headline — the Arbiter, a third FSM route (ADR 0016)
- **Arbiter agent** (`src/executor/agents/arbiter.py`, role `arbiter` in `ROLE_MODELS`,
  `prompts/system/arbiter.md`): on a STUCK cycle (`attempt ≥ ARBITER_TRIGGER_ATTEMPT`, default 2) it returns
  a structured `ArbiterVerdict{root_cause_class, route, reasoning, contract_amendment_directive}` and adds a
  **third routing target — the contract**. `developer`/`qa` fall through to the existing channels; `halt`
  aborts with an incident; `contract` re-derives (AMENDS) the TechLead spec via
  `run_techlead_node(amendment_feedback=…)`.
- **Conservative bounds**: `environment_id` is **pinned** across an amendment (the platform — sandbox image,
  gates, QA layout — never thrashes); `MAX_CONTRACT_AMENDMENTS` (default 1) caps autonomous rewrites, else
  `halt`. Each amendment grants `AMENDMENT_RETRY_BONUS` extra cycles via a dynamic `while`-loop ceiling, so
  the re-derived contract gets a fair shot; the financial breaker stays the absolute ceiling.
- **Retry budget hoisted**: the bare `max_retries = 3` local became `MAX_FUNCTIONAL_RETRIES`
  (env `PIPELINE_MAX_RETRIES`) — closing the long-standing config-convention outlier — and the cycle is now
  a `while` over `MAX_FUNCTIONAL_RETRIES + contract_amendments * AMENDMENT_RETRY_BONUS` (resume-safe,
  recomputed from persisted state). New ctx fields `arbiter_verdict` / `contract_amendments` auto-persist.

### Recitation resilience (root cause + safety net)
- **Fail-fast on content-filter blocks** (`src/shared/utils/api_retry.py`,
  `src/shared/core/observability.py`): `finish_reason_name` + `NON_RETRYABLE_FINISH_REASONS`
  (`RECITATION`/`SAFETY`/`BLOCKLIST`/`PROHIBITED_CONTENT`/`SPII`) make `with_api_retry` raise immediately
  instead of burning the backoff budget on a deterministic block.
- **One paraphrase-guarded retry** for RECITATION (`src/shared/utils/llm.py`): `run_structured_llm` appends
  `RECITATION_GUARD` ("don't reproduce text verbatim") and retries once — following the finish-reason hint
  rather than repeating the blocked prompt.
- **Engine-injected baseline files** (`src/shared/core/boilerplate.py` + `src/nexus/nexus_runner.py`): the
  canonical MIT `LICENSE` and per-environment `.gitignore` are now assembled and appended to `TASK-01`
  deterministically — the LLM never reproduces them. `prompts/system/tpm.md` stops emitting them;
  `prompts.py` drops the `{injected_gitignore_templates}` injection.

### Prompt hardening (so an amendment converges, not just escalates)
- `prompts/system/techlead.md`: **ERROR PRECEDENCE** rule (overlapping `Raises` must declare precedence;
  never short-circuit before the parser surfaces a more specific error) + an **AMENDMENT MODE** section.
- `prompts/system/reviewer.md`: **CONSTRAINT-RESPECTING REPAIR** — a fix that clears a gate by violating a
  stated NFR is invalid; name the contract conflict so it routes to an amendment.
- `prompts/skills/engineering_guide.md`: the drain-the-incremental-parser idiom for error precedence under
  an O(1)/streaming constraint.

### Meta-tooling
- `/analyze-run` Claude Code skill (evidence-first run diagnosis), a path-scoped `agent-role-registration`
  rule (full checklist for adding a structured agent role), and `run-layout-and-cli` / `run-tests-via-wsl`
  rule extensions (non-interactive git auth for `--run`; Git-Bash↔WSL path translation).

## Metrics / Logs Analysis

- **Diff footprint** (`169842b` → HEAD): 31 files, ~1,143 insertions / ~76 deletions. New engine modules:
  `src/shared/core/boilerplate.py` (+62), `src/executor/agents/arbiter.py` (+56); heaviest edits
  `src/executor/runner.py` (+59, FSM Arbiter route + `while`-ceiling) and `src/executor/agents/techlead.py`
  (+46, amendment mode). New tests: `test_arbiter.py`, `test_boilerplate.py`, `test_llm.py`, plus expansions
  to `test_orchestrator.py` (+152, Arbiter routing), `test_api_retry.py`, `test_observability.py`,
  `test_prompts.py`, `test_nexus_runner.py` — full suite green (326 tests).
- **Validation runs (real API + Docker), demo project `cli-python-json-csv`:**
  - Nexus planning: previously halted at TPM on RECITATION; now completes (the boilerplate trigger is gone).
  - `TASK-01`/`TASK-02`/`TASK-03` implemented, committed, pushed (`TASK-01`/`02` merged to `main` via PRs).
  - `TASK-03` (`005_exec_TASK-03_…`): the formerly breaker-bound ticket now PASSES on cycle 3. The Arbiter
    fired once on cycle 2 and correctly classified the failure as a **test defect** (`route=qa` — a test
    mocked `json.load` while the production code streams `ijson`, so the mock was inert), declining to amend
    the contract (`contract_amendments=0`); recovery was carried by the prompt hardening (Developer adopted
    verify-syntax-before-classifying-structure). Arbiter cost: ~$0.013; total run $0.92 (9.2% of budget).
- **Follow-ups filed** (`docs/BACKLOG.md` #25/#26): the Arbiter's `developer`/`qa` routes are advisory
  (don't yet override a Reviewer mis-route), and a non-amending verdict grants no extra cycle budget (the
  `TASK-03` run succeeded on the last allowed cycle). The contract-amendment path is unit-tested but not yet
  exercised end-to-end.

> Validate locally via WSL:
> `wsl -e bash -lc "cd /mnt/c/code/async-agentic-sdlc && source venv/bin/activate && GEMINI_API_KEY=test-key python3 -m unittest discover -s tests"`
