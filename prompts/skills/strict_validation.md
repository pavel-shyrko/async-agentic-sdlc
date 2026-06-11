---
skill_id: strict_validation
type: global
nodes: [qa, reviewer]
---
Strict validation rules to enforce: {strict_type_validation_rules}

## CRITICAL RULES
* The generated test suite must be completely deterministic. You are STRICTLY FORBIDDEN from softening boundary tests or type-validation checks — no exception-swallowing wrappers, no no-op statements, and no conditional assertions that mask a failure. If a type or value is invalid according to the contract, assert that the documented error is raised, using the framework's exception-raising assertion exclusively.
* You are STRICTLY FORBIDDEN from asserting, matching, or validating the message of ANY exception. Verify ONLY the exception type; never compare against the exception object, its arguments, or its string representation, and leave the exception object uninspected.
