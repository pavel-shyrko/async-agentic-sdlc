---
skill_id: strict_validation
type: global
nodes: [qa, reviewer]
---
Strict validation rules to enforce: {strict_type_validation_rules}

## CRITICAL RULE
* The generated/reviewed test suite must be completely deterministic. You are STRICTLY FORBIDDEN from softening boundary tests or type-validation checks — no exception-swallowing wrappers, no no-op statements, and no conditional assertions that mask a failure. If a type or value is invalid according to the contract, assert that the documented error is raised, using the framework's exception-raising assertion exclusively. (Exception fidelity — assert TYPE only, never the message — is owned by the QA system prompt's CRITICAL RULE.)
