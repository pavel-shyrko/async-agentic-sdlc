---
skill_id: strict_validation
type: global
nodes: [qa, reviewer]
---
Strict validation rules to enforce: {strict_type_validation_rules}

## CRITICAL RULES
* The generated test suite must be completely deterministic. You are STRICTLY FORBIDDEN from wrapping boundary tests or type validation checks in `try-except` blocks, `pass` statements, or conditional `if-else` assertions. If a type or value is invalid according to the contract, use `self.assertRaises()` exclusively.
* You are STRICTLY FORBIDDEN from asserting, matching, or validating the string message of ANY exception (e.g., using `assertIn`, `assertEqual`, `assertRegex`, or `assertRaisesRegex` on exception strings, `.args`, or `str(exception)`). You must ONLY verify the exception type using `with self.assertRaises(ExceptionType):` and leave the exception object uninspected.
