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

| Task | Cycles | Tests | SAST | Critical Event |
| :--- | :---: | :---: | :---: | :--- |
| Prime Number Checker | 1 | 32 | 0 | Reference run, approved on the first cycle (`checkpoint_1.json`). Architect mandated the `isinstance(n, int) and not isinstance(n, bool)` TypeError guard; QA emitted 32 deterministic `assertRaises` tests with zero Test Softening. |
| Fibonacci Calculator | 1 | 16 | 0 | Iterative O(n)/O(1) contract enforced (no recursion); negative index → `ValueError`, `bool`/`float` → `TypeError`, with the `bool`-subclass guard checked before `int`. |
| Geometry Package | 3 | 70 | 0 | DI enforced for `Cylinder`/`Cuboid` (constructor-injected `Circle`/`Rectangle`); self-heal survived cross-file import defects and path-conflict Triage before converging (`current_attempt: 4` in `checkpoint_3.json`). QA Fan-Out produced 70 cross-module tests. |

**Key finding:** The relocated directives stayed load-bearing under load. The Geometry run (Task 3) exercised the Phantom-vs-Utility Triage and the DI invariant across three self-heal cycles, while the domain-isolation audit confirmed **zero system-prompt leakage into the sandbox** (`artifacts/code/`) — agent judgment now resolves from `prompts/system/*.md` plus the shared `prompts/skills/engineering_guide.md`, contaminating neither the Pydantic schema nor the generated output. Co-locating these rules with the agent's reasoning context, not the data schema, is what makes them both evolvable and traceable.

## Consequences
* **Pros**: Single source of truth for agent behavior (system prompts); prompt tuning requires no Python edits or core redeploy; schema layer carries pure structural intent; semantics are bound explicitly to output keys.
* **Cons**: Behavior is now split across two artifacts (markdown prompt + Pydantic schema) that must be kept key-aligned; a renamed schema field silently desyncs from its semantic block.
* **Neutral**: Prompts are resolved from disk at runtime via `PROMPTS_BASE`, adding a filesystem dependency to agent initialization.
