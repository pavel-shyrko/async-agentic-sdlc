---
skill_id: python_qa
type: domain
triggers: [python]
nodes: [qa, reviewer]
---
LANGUAGE TARGET: Python — test-suite rules for the Python tech stack.

## Testing Framework
- Use ONLY the standard-library `unittest`. Parametrize with `self.subTest(case=...)` loops over an
  explicit input/expected data table — prefer one parametrized loop over near-duplicate methods.
- STRICTLY BAN `pytest`, `parameterized`, and any third-party parametrization helper.

## Assertions & Exceptions
- Verify exceptions with `with self.assertRaises(ExceptionType):` ONLY; leave the exception object
  uninspected. BAN `assertRaisesRegex` and any regex/string match against an exception, its
  `.args`, or its `str()`.
- Include type-boundary negative cases (e.g. a `bool` where an `int` is expected) and assert only
  the raised type.

## Imports
- Import the module under test via its exact dotted path (e.g. `import package.module` or
  `from package.module import ...`). Never inline or mock the production implementation.

## Floating-Point
- Do not hardcode expectations for computed floats; compute them dynamically
  (e.g. `math.pi * r ** 2`) and compare with `math.isclose()`.
- For overflow beyond `sys.float_info.max`, force and assert `float('inf')` explicitly rather than
  reverse-arithmetic.
