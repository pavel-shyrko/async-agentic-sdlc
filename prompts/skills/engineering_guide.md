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

## Security
* Zero tolerance for vulnerabilities. Run the ecosystem's standard SAST scanner before review.
