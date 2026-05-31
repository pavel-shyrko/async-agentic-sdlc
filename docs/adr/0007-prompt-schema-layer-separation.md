# 7. Prompt/Schema Layer Separation

## Status
Accepted

## Context
Behavioral LLM instructions had leaked into the infrastructure layer. Pydantic `Field(description=...)` strings in `src/core/models.py` carried prompt-engineering directives (e.g. bool-cast type guards, try-except "Test Softening" prohibitions, release-readiness gating). This coupled agent behavior to the schema definitions: tuning an agent required editing Python, redeploying the core package, and risked diverging from the system prompts that already governed the same agents. The Task #3 (Geometry) FSM audit confirmed these behaviors are load-bearing — the Reviewer's DRY rejection and the Uncontracted-Files Triage both depend on precise, evolvable directives — making their entanglement with the data layer a maintenance and correctness risk.

## Decision
Establish a strict boundary between the infrastructure schema layer and the prompt-engineering layer:
1. **Schema reduction**: `Field(description=...)` in `ArchitectureContract` and `ReviewReport` is reduced to dry, structural descriptions of each key. The Pydantic classes and fields are unchanged; only the descriptive text is sanitized.
2. **Semantic relocation**: The excised behavioral rules are restored under an `### Output JSON Schema Semantics` section in `prompts/system/architect.md` and `prompts/system/reviewer.md`, bound per JSON key (e.g. `strict_type_validation_rules`, `test_integrity_approved`).
3. **Externalized prompt loader**: `src/core/prompts.py` loads system prompts from `prompts/system/*.md` (env-overridable `PROMPTS_BASE`, `lru_cache`d), so agent behavior is editable without touching application code.

## Verification

Three FSM pipeline runs validated the behavioral rules relocated in this ADR:

| Task | Cycles | Critical Event |
| :--- | :---: | :--- |
| Prime Number Checker | 2 | Reviewer distinguished Developer code correctness from QA test failure — `ValueError` contract honored, tests rejected with exact fix payload. |
| Fibonacci Calculator | 1 | `bool`-subclass type guard fired correctly; `isinstance(n, bool)` checked before `isinstance(n, int)`. Zero false positives. |
| Geometry Package | 2 | Reviewer detected DRY violation (`_validate_numeric` duplicated across `shapes.py` / `volume.py`), issued refactor directive; Triage classified `validators.py` as Valid Utility on cycle 2. |

**Key finding:** The Reviewer's ability to distinguish code correctness from test correctness (Task 1) and to apply the Phantom vs. Utility Triage (Task 3) both depend on prompt-level behavioral directives that were previously embedded in `Field(description=...)`. Relocating them to `### Output JSON Schema Semantics` in `reviewer.md` confirmed these rules are load-bearing and must be co-located with the agent's reasoning context, not the data schema.

## Consequences
* **Pros**: Single source of truth for agent behavior (system prompts); prompt tuning requires no Python edits or core redeploy; schema layer carries pure structural intent; semantics are bound explicitly to output keys.
* **Cons**: Behavior is now split across two artifacts (markdown prompt + Pydantic schema) that must be kept key-aligned; a renamed schema field silently desyncs from its semantic block.
* **Neutral**: Prompts are resolved from disk at runtime via `PROMPTS_BASE`, adding a filesystem dependency to agent initialization.
