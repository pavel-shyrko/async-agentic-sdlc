---
skill_id: python_core
type: domain
triggers: [python]
nodes: [techlead, developer, reviewer]
---
LANGUAGE TARGET: Python — production-code rules for the Python tech stack.

## Runtime & Sandbox
- Target Python 3.11+, executed in the isolated Docker sandbox (`python:3.11-slim`).

## Type Guards
- Enforce strict `isinstance` checks. A `bool` MUST NOT pass where an `int` is expected:
  guard with `isinstance(n, int) and not isinstance(n, bool)`.
- Store constructor parameters as their original allowed types — no implicit coercion
  (e.g. do not force `int` to `float`).

## Exception Handling
- Raise explicit, specific exceptions (e.g. `TypeError`, `ValueError`) for invalid inputs.
  Never silently swallow errors or use a bare `except` / `pass`.

## Package Glue
- Create necessary Python infrastructure files not listed in the contract (e.g. `__init__.py`,
  a shared `utils.py`) so the module imports and compiles.

## Security
- The Bandit SAST scanner runs before review; zero tolerance for flagged vulnerabilities.
