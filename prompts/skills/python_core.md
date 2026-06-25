---
skill_id: python_core
type: domain
triggers: [python]
nodes: [techlead, developer, reviewer]
---
LANGUAGE TARGET: Python — production-code rules for the Python tech stack.

## Runtime & Sandbox
- Target Python 3.12+, executed in the isolated Docker sandbox (`python:3.12-slim`).

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
- Every `pyproject.toml` MUST include a `[project]` table with `name` (kebab-case, derived from the
  application/project name) and `version` (start at `"0.1.0"`). Without it `python -m build` emits
  `unknown-0.0.0-py3-none-any.whl` and breaks GitHub Release artifact naming.

## Dependency Manifest (MANDATORY — the toolchain restores from `requirements.txt`)
- Declare EVERY third-party runtime AND test dependency (e.g. `fastapi`, `uvicorn`, `pydantic`,
  `pytest`, `httpx`), version-pinned, one per line, in a `requirements.txt` at the repository ROOT.
  Create the file if it is not already in the contract — it is required repository glue, like `__init__.py`.
- The build/test toolchain restores dependencies with `pip install -r requirements.txt` ONLY. A
  `pyproject.toml` alone is NOT installed, so any dependency present only in `[project].dependencies`
  will be MISSING at build/test and raise `ModuleNotFoundError`.
- If the project also carries a `pyproject.toml`, mirror its `[project].dependencies` (plus the test
  dependencies) into `requirements.txt`; the two MUST NOT drift. `requirements.txt` is the dependency
  source of truth for the sandbox; `pyproject.toml` carries packaging metadata.

## Security
- The Bandit SAST scanner runs before review; zero tolerance for flagged vulnerabilities.
