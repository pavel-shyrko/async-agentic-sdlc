---
skill_id: engineering_guide
type: global
nodes: [techlead, developer, qa, reviewer]
---
# Global Engineering Guide & Code Style

## Code Style
* **Testing**: Use the target ecosystem's native, standard testing framework. Do not introduce a third-party test framework when the standard library already provides one.
* **Type Boundaries**: Apply strict type boundaries. Reject ambiguous sub-types that could pass an implicit cast; validate the exact expected type at runtime.
* **State Preservation**: Store parameter values passed into constructors exactly as their original allowed types. No implicit coercion.
* **Error precedence under a streaming/O(1) constraint**: when one input can trigger more than one failure type (e.g. it is BOTH malformed/incomplete AND a wrong-typed/non-target structure), surface the more specific low-level fault (syntax/parse error) BEFORE the higher-level structural classification. Do NOT short-circuit on a first/partial signal — that misclassifies incomplete input. The constraint-respecting idiom: DRAIN the incremental parser to confirm well-formedness, letting its incomplete/parse error propagate (mapped to the documented syntax-error type); classify structure (e.g. "root is not the expected container") only once the document parsed cleanly. Never full-load the document to disambiguate when a streaming/O(1) constraint is in force.

## Security
* Zero tolerance for vulnerabilities. Run the ecosystem's standard SAST scanner before review.
