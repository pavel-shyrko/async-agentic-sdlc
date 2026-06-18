---
skill_id: python_qa
type: domain
triggers: [python]
nodes: [qa, reviewer]
---
LANGUAGE TARGET: Python — concrete syntax for the Python tech stack. The language-neutral rules
(exception fidelity, import/packaging fidelity, whole-file assembly, BVA strategy) live in the QA
system prompt; this skill only maps them to Python idioms.

## Testing Framework
- Use ONLY the standard-library `unittest`. Parametrize with `self.subTest(case=...)` loops over an
  explicit input/expected data table — prefer one parametrized loop over near-duplicate methods.
- STRICTLY BAN `pytest`, `parameterized`, and any third-party parametrization helper.

## Assertions & Exceptions (concrete API for the system-prompt CRITICAL RULE)
- Verify exceptions with `with self.assertRaises(ExceptionType):` ONLY. BAN `assertRaisesRegex` and any
  regex/string match against an exception, its `.args`, or its `str()`.
- Include type-boundary negative cases (e.g. a `bool` where an `int` is expected) and assert only
  the raised type.
- CSV / NEWLINES (CRITICAL): Python's stdlib `csv` writer emits `\r\n` line terminators (RFC 4180),
  NOT `\n`. NEVER hard-code a bare-`\n` expectation for CSV output — it fails as `'a\r\n1' != 'a\n1'`.
  Either expect `\r\n` explicitly, or normalize both sides before comparing (e.g.
  `actual.replace("\r\n", "\n")`, or compare `actual.splitlines() == expected.splitlines()`). The same
  applies to any code path that goes through `csv.writer`/`csv.DictWriter`.

## File Placement & Module Identity
- Tests live in the dedicated `tests/` directory (the engine derives the exact path) — NEVER colocated
  next to the source file. Emit only the suite body for the assigned module.
- Import the module under test by its exact dotted path (e.g. `import package.module` or
  `from package.module import ...`).
- A thin entrypoint (a module whose only top-level executable code is an `if __name__ == "__main__":`
  guard delegating elsewhere) has no independently testable logic — emit at most a faithful minimal
  check (it imports cleanly / the wired callables exist) in its OWN module.

## Floating-Point
- Compute expected floats dynamically (e.g. `math.pi * r ** 2`) and compare with `math.isclose()`.
- For overflow beyond `sys.float_info.max`, force and assert `float('inf')` explicitly.
