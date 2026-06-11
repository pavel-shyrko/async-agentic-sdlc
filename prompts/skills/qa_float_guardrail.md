---
skill_id: qa_ieee754_guardrail
type: global
nodes: [qa]
---
CRITICAL IEEE 754 MANDATE (LANGUAGE AGNOSTIC):
When testing numeric boundaries near the environment's maximum float capacity (e.g., MAX_FLOAT, Double.MaxValue), you are STRICTLY FORBIDDEN from using reverse-arithmetic (e.g., sqrt(MAX_FLOAT / N)) to dynamically calculate inputs that perfectly target the boundary.
Machine precision loss makes reverse-engineered boundary tests non-deterministic across platforms.
Rule 1 (Finite Range): Test large finite boundaries using safe exponential literals (e.g., `1e100`).
Rule 2 (Overflow Range): Force infinity explicitly (e.g., `MAX_FLOAT * 2`) and assert against the language's native Infinity representation.
Rule 3 (Tolerance): Never use strict equality (`==` or `assertEqual`) for computed floating-point results. Always apply the language's standard relative/absolute tolerance assertion (e.g., `isclose`, epsilon comparisons).
