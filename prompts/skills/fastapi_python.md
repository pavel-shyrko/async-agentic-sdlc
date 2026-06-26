---
skill_id: fastapi_python
type: domain
triggers: [fastapi, backend]
nodes: [techlead, developer, qa]
---
LANGUAGE TARGET: Python / FastAPI — production-code rules for a FastAPI backend in a fullstack monorepo.

## Project layout
- All backend source code lives under `backend/` (relative to the repo root). Entry point: `backend/main.py` (or `backend/app/main.py` per the blueprint topology).
- Dependency manifest: `requirements.txt` at the **repository root** (NOT `backend/requirements.txt`) — declare EVERY third-party runtime AND test dependency (e.g. `fastapi`, `uvicorn[standard]`, `pydantic`, `httpx`, `pytest`, `pytest-asyncio`), version-pinned, one per line. The sandbox mounts the repo root at `/workspace` and restores with `pip install -r requirements.txt` from there; a manifest under `backend/` is never found. A `pyproject.toml` alone is NOT sufficient. `requirements.txt` MUST be in `files_to_modify` in the TechLead contract.

## FastAPI conventions
- Define the application factory in a dedicated `create_app()` function so it can be instantiated independently in tests.
- Use async route handlers (`async def`) for all I/O-bound endpoints.
- Use Pydantic v2 models for ALL request bodies and response schemas — no raw dicts or untyped returns.
- Add CORS middleware (`fastapi.middleware.cors.CORSMiddleware`) configured to allow the frontend origin. The allowed origins MUST be sourced from an environment variable with a safe default (e.g. `*` in development) so the service boots with zero required configuration.
- Expose a lightweight health endpoint (e.g. `GET /health` → `{"status": "ok"}`) for Cloud Run liveness probes.
- Server entry point: `uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}`. The port MUST be sourced from the `PORT` environment variable; never hardcode it.

## Type safety
- Enforce strict `isinstance` checks. A `bool` MUST NOT pass where an `int` is expected: guard with `isinstance(n, int) and not isinstance(n, bool)`.
- Store constructor parameters as their original allowed types — no implicit coercion.
- Raise explicit, specific exceptions (`HTTPException` with appropriate status codes; `ValueError` / `TypeError` for internal guard failures). Never silently swallow errors.

## Testing
- Use `pytest` with `pytest-asyncio` and `httpx.AsyncClient` (with `ASGITransport`) for integration tests against the running application instance — no mocking of internal business logic.
- Test files MUST live under `backend/tests/` with `test_` prefix. This overrides the generic Python test placement rule — do NOT place tests under the root `tests/` directory.
- Every endpoint MUST have at least one integration test covering the happy path and one covering a key error path (e.g. 404, 422 validation failure).
- **Test runner context**: `pytest` runs from the REPOSITORY ROOT (`/workspace`), NOT from `backend/`. All imports MUST use the full repo-root-relative module path — `from backend.app.main import app`, never `from app.main import app`. Ensure `backend/__init__.py` exists so the `backend` package is discoverable from the root.
- **Separate test execution**: backend tests (`pytest backend/tests/`) run independently of frontend tests; do not mix test frameworks or import cross-boundary between them.

## Repository hygiene
- Generate `backend/.gitignore` with Python-specific patterns: `__pycache__/`, `*.pyc`, `*.pyo`, `.env`, `venv/`, `.venv/`, `.pytest_cache/`, `*.egg-info/`, `dist/`, `build/`, `.mypy_cache/`.

## Security
- The Bandit SAST scanner runs before review; zero tolerance for flagged vulnerabilities.
- Never log or expose secrets; never embed credentials in source code.
