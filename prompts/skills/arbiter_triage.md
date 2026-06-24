---
skill_id: arbiter_triage
type: global
nodes: [arbiter]
---
ARBITER TRIAGE GUARDRAILS — apply BEFORE choosing a `root_cause_class`/`route`. These prevent the most
common mis-routes that loop a cycle to the circuit breaker. Language-neutral; they refine the routing
rubric in the system prompt, never override its definitions.

## Read the gate signal before blaming the code
- If the Reviewer set BOTH `code_quality_approved` AND `test_integrity_approved` to true, the code and
  tests are NOT the open problem — do NOT invent a `production_bug`/`test_bug`. Something else is still
  red: a HARD gate (lint/build/test/SAST). Diagnose from the GATE / RUNNER OUTPUT and route at THAT gate.
- A lint/format gate that is red is fixed by the formatter or a small style edit on the OWNING file
  (production → `developer`, test → `qa`); it is NEVER grounds to delete a Reviewer-approved file or
  re-architect the project. If the gate output is empty/uninformative, prefer the channel that owns the
  file the gate names — do not substitute a guess about scope.

## Build glue is legitimate — do not route its deletion
- A file the build TOOL requires to compile a *contracted* artifact — a program entry point an
  executable build manifest needs, a package/init/index file, a manifest's minimal glue — is authorized
  work even when it is not in `files_to_modify` (the Developer is explicitly permitted to add it, and it
  carries a top-of-file justification comment). Its presence is NOT a scope violation. Never emit a
  `developer` directive to delete it or to change the artifact's declared type/output to avoid it.

## A missing required-to-build file is a CONTRACT gap, not a Developer bug
- If a file genuinely REQUIRED to build a contracted artifact is absent from `files_to_modify` and that
  absence is the blocker, the contract whitelist is the defect → `contract_conflict` → `contract`. Emit a
  `contract_amendment_directive` that ADDS the file to `files_to_modify`/topology (and pins the artifact's
  archetype, e.g. executable-vs-library, so downstream agents stop oscillating). Do NOT bounce the
  Developer with an "undo it" directive that contradicts what the artifact needs to build — that is the
  oscillation the `contract` route exists to break.

## Never trade one red gate for another
- A "fix" that would make the current gate pass by breaking a different gate or violating a stated
  `architectural_constraints` is not a valid `developer`/`qa` route — it is a `contract_conflict`.
