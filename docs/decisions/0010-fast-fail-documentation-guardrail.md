# 0010 — Fast-Fail Documentation Guardrail & Smart Triage

## Status

Accepted

## Context

Iteration 009 left a destructive failure mode in the Developer ↔ Reviewer loop, observed as
**State Cascade Destruction** on brownfield repositories:

1. **Glue-file wipe** — the Developer, mounting contract paths blindly, overwrote module glue
   files and package indexes (e.g. `__init__.py`) instead of merging into them, erasing the
   imports accumulated by previous iterations.
2. **Eradication Directive misfire** — the Reviewer's binary triage classified anything outside
   the immediate `ArchitectureContract.files_to_modify` as a "Ghost File" and issued the
   Eradication Directive (`You MUST delete it`). The directive could not distinguish a mangled
   *legacy* file or a *justified* new helper module from genuine hallucinated garbage, so it
   ordered the deletion of working code from prior iterations.
3. **Token-draining loop** — each eradication broke imports, which failed the next gate run,
   which re-entered the Developer with destructive feedback, burning the entire functional
   circuit-breaker retry budget (3 expensive Developer + Reviewer + QA cycles) without forward
   progress and with permanent legacy-code loss.

The root defect: the only enforcement boundary for uncontracted files was a **probabilistic LLM
gate** (the Reviewer) armed with a blunt, binary policy — the cheapest violations were detected at
the most expensive point in the FSM.

## Decision

Three coordinated mechanisms replace the binary eradication policy:

- **Architectural justification mandate (`prompts/system/developer.md`)** — the Developer
  retains explicit IMPLEMENTATION AUTONOMY to create uncontracted infrastructure files
  (package-initialization files, shared DRY utility modules), but any uncontracted new file
  MUST carry a brief architectural justification — a comment block at the top of the file
  explaining why it is required for the production solution.

- **Smart Triage protocol (`prompts/system/reviewer.md`)** — the Eradication Directive is
  replaced with a 3-bucket triage for uncontracted or modified files:
  1. **JUSTIFIED ADDITIONS** — logically necessary new production files (separated abstractions,
     helper modules), especially when a justification is present: APPROVE as part of the solution.
  2. **HALLUCINATED GARBAGE** — files unrelated to the ticket scope, unjustified, or debugging
     scripts: classify as Ghost Files and order eradication.
  3. **LEGACY VICTIMS** — pre-existing functional code that was modified, broken, or deleted:
     NEVER order eradication; order the Developer to REVERT the destructive change and integrate
     safely. The Reviewer additionally receives the `GIT DIFF (SCOPE OF CHANGES)` and is bound to
     review only the diff, using full file contents strictly for architectural context — so legacy
     code can no longer be flagged merely for being absent from the current contract.

- **Fast-Fail Documentation Guardrail middleware (`orchestrator.py`)** — a deterministic,
  zero-LLM-cost Python check (`enforce_documentation_guardrail`) runs immediately after the
  Developer phase, BEFORE the Reviewer/QA gates:
  - **Candidate set** — the production snapshot delta is intersected with the git-ADDED set
    (`get_pipeline_snapshot_files(..., diff_filter="A")`), so only genuinely *newly-created*
    uncontracted files are scanned — edits to pre-existing files are never flagged.
  - **Language-agnostic lexical check** — the first 15 lines (`GUARDRAIL_TOP_LINES`) of each
    candidate are scanned for common comment lead-ins: `#`, `//`, `/*`, `*`, `"""`, plus `'''`
    (added beyond the original spec so Python single-quote module docstrings pass). Binary,
    non-UTF-8, empty, or unreadable files are ignored safely (no false violations, no raises).
  - **Budget protection (free reroute)** — a violation routes a focused diagnostic
    (`SYSTEM GUARDRAIL: File … was created without an architectural justification …`) directly
    back to the Developer, bypassing the expensive Reviewer/QA nodes and consuming **none** of
    the functional circuit-breaker retry budget.
  - **Hard Halt** — local reroutes are capped at `GUARDRAIL_MAX_REROUTES = 2`. Exceeding the cap
    triggers a deterministic abort: the full pipeline context is dumped to
    `runs/run_<uuid>/reports/incident_report.json` and the process exits non-zero
    (`_abort_with_incident`), guaranteeing the FSM can never loop indefinitely on the guardrail.

## Consequences

- **Pros**: the cheapest violation class is now caught by a deterministic lexical scan costing
  zero tokens, instead of a full Reviewer round-trip — fast-fail reroutes spend only one extra
  Developer call; legacy code is structurally protected (LEGACY VICTIMS bucket + diff-scoped
  review forbid eradication of pre-existing files); the functional retry budget is reserved for
  functional failures; loop termination is deterministic — the reroute cap plus Hard Halt convert
  a previously unbounded token drain into a bounded, auditable incident with a full state dump.
- **Cons / constraints**: the lexical check is a heuristic — *any* leading comment passes, so
  justification quality is still only assessed downstream by the Reviewer; the comment-prefix
  list is finite, so files in languages with exotic comment syntax (or comment-free formats)
  are skipped or could in principle false-positive; the Hard Halt is a new hard-failure surface —
  a Developer that persistently refuses to emit a top-of-file comment now terminates the run
  rather than degrading gracefully; the guardrail only protects *new* files, relying entirely on
  Smart Triage for destructive edits to existing ones.
