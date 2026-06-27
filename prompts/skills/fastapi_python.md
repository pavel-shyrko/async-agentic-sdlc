---
skill_id: fastapi_python
type: domain
triggers: [fastapi, backend]
nodes: [techlead, developer, qa]
---
LANGUAGE TARGET: Python / FastAPI — production-code rules for a FastAPI backend component in a monorepo.

## Project layout (the backend is a self-contained component)
- ALL backend code lives under `backend/` — the component's OWN root. The engine pins `working_directory`
  to `backend` from the ticket's `## Component: BACKEND` tag, so every gate (dependency restore, build,
  tests, lint, security) executes INSIDE `backend/` and ALL paths/imports below are relative to `backend/`
  — never prefixed with `backend/`. This mirrors how the React `frontend/` component works. Do NOT set or
  override `working_directory` in the contract — it is engine-owned.
- Entry point: `backend/app/main.py` (or `backend/main.py` per the blueprint topology).
- Dependency manifest: `backend/requirements.txt` — declare EVERY third-party runtime AND test dependency
  (e.g. `fastapi`, `uvicorn[standard]`, `pydantic`, `httpx`, `pytest`, `pytest-asyncio`), version-pinned,
  one per line. A `pyproject.toml` alone is NOT sufficient. The toolchain restores it automatically by
  running `pip install -r requirements.txt` inside `backend/`; it MUST be in `files_to_modify`.
- Dockerfile: `backend/Dockerfile`, built with the **`backend/` directory as the build context** (exactly
  like `frontend/Dockerfile`). Use `COPY requirements.txt .` (relative to `backend/`); never
  `COPY backend/requirements.txt .`.

## FastAPI conventions
- Define the application factory in a dedicated `create_app()` function so it can be instantiated independently in tests.
- Use async route handlers (`async def`) for all I/O-bound endpoints.
- Use Pydantic v2 models for ALL request bodies and response schemas — no raw dicts or untyped returns.
- CORS is OPTIONAL and contract-driven: add CORS middleware (`fastapi.middleware.cors.CORSMiddleware`) ONLY
  when the contract requires cross-origin browser access (e.g. a separate frontend origin). When you do,
  source the allowed origins from an environment variable with a safe default so the service still boots
  with zero required configuration. Do NOT add CORS to a service whose contract does not call for it.
- Expose the contracted health endpoint (e.g. `GET /healthz` → `{"status": "ok"}`) for Cloud Run liveness probes.
- Server entry point: `uvicorn <module>:app --host 0.0.0.0 --port ${PORT:-8080}`, where `<module>` is the
  dotted path to your entry module RELATIVE to `backend/` (e.g. `app.main` for `backend/app/main.py`, or
  `main` for `backend/main.py`) — never a `backend.` prefix. The port MUST be sourced from the `PORT`
  environment variable; never hardcode it.

## Type safety
- Enforce strict `isinstance` checks. A `bool` MUST NOT pass where an `int` is expected: guard with `isinstance(n, int) and not isinstance(n, bool)`.
- Store constructor parameters as their original allowed types — no implicit coercion.
- Raise explicit, specific exceptions (`HTTPException` with appropriate status codes; `ValueError` / `TypeError` for internal guard failures). Never silently swallow errors.

## Testing
- Use `pytest` with `pytest-asyncio` and `httpx.AsyncClient` (with `ASGITransport`) for integration tests against the running application instance — no mocking of internal business logic.
- Test files live under `backend/tests/` with a `test_` prefix (the engine places them there from `working_directory`).
- **Test runner context**: `pytest` runs from INSIDE `backend/`, so import the app SUBDIR-RELATIVE —
  `from app.main import app`, NEVER `from backend.app.main import app` and never a `backend/` prefix (the
  same no-`frontend/`-prefix rule the React component follows). `backend/app/__init__.py` must exist so
  `app` is an importable package.
- **Test ONLY contracted behavior (scope discipline):** cover exactly the endpoints, status codes, and
  behaviors the contract / acceptance examples specify — never framework features the contract does not add.
  Do NOT test CORS/preflight unless the contract adds CORS middleware; do NOT test auth unless contracted.
- **Endpoint scope pre-flight (MANDATORY before writing any test class):** Extract every path listed in
  `function_signatures`. A test class that targets a path NOT in that list is a hallucination — delete it.
  Never write tests for an endpoint absent from `function_signatures`, regardless of what you infer from
  the blueprint or general REST conventions.
- **Trailing-slash rule:** FastAPI's default `redirect_slashes=True` makes a trailing-slash variant of any
  contracted path 307-redirect to the canonical route and return **the contracted status code for that
  route** (e.g. a trailing-slash `DELETE` that returns `204`, not `200`). Therefore: **NEVER assert `404`
  for a trailing-slash variant of a contracted path.** If the trailing-slash behaviour is not explicitly
  stated in the contract, **omit the trailing-slash test entirely** — do not guess or invent the expected
  status code.
- Every contracted endpoint MUST have at least one happy-path test and one key-error-path test (e.g. 404, 422 validation failure).
- **Separate test execution**: backend tests run independently of frontend tests; do not mix test frameworks or import across the `backend/` ↔ `frontend/` boundary.

## Repository hygiene
- Generate `backend/.gitignore` with Python-specific patterns: `__pycache__/`, `*.pyc`, `*.pyo`, `.env`, `venv/`, `.venv/`, `.pytest_cache/`, `*.egg-info/`, `dist/`, `build/`, `.mypy_cache/`.

## Security
- The Bandit SAST scanner runs before review; zero tolerance for flagged vulnerabilities.
- Never log or expose secrets; never embed credentials in source code.
