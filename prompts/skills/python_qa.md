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
- **Domain-skill override:** if a framework-specific domain skill (e.g. `fastapi_python`) is also
  loaded, its **Testing** section governs the test runner and framework choice — follow that skill's
  instructions instead of the `unittest`-only rule above.

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

## HTTP Endpoint Tests (FastAPI / Starlette `TestClient`)
- Address an endpoint by the EXACT path the contract specifies (e.g. `self.client.get("/echo")`).
  NEVER discover the path dynamically by iterating `app.routes` and filtering a hand-maintained
  denylist — FastAPI auto-registers framework routes (`/openapi.json`, `/docs`,
  `/docs/oauth2-redirect`, `/redoc`) and `/docs/oauth2-redirect` sorts BEFORE your app's routes, so a
  denylist that forgets it silently returns the Swagger redirect HTML page. The test then exercises the
  wrong endpoint and fails with a misleading `JSONDecodeError` (HTML where JSON was expected), a `405`,
  or an unexpected `200` — never the route under test. The contract gives the path; use the literal.
- When a `TestClient` response is expected to be JSON, assert `response.headers["content-type"]` starts
  with `application/json` (or that the path actually hit is the contracted one) BEFORE `response.json()`,
  so a wrong-endpoint hit fails with a clear signal instead of an opaque decode error.

## File Placement & Module Identity
- Tests live in the dedicated `tests/` directory by default (the engine derives the exact path) — NEVER colocated next to the source file. For monorepo layouts a domain skill may specify a subdirectory (e.g. `backend/tests/`); that instruction takes precedence over this default. Emit only the suite body for the assigned module.
- **Test runner working directory**: `pytest` runs from the gate's working directory — the repository root for a single flat package, or the COMPONENT root (e.g. `backend/`) when the ticket carries a component (the engine pins `working_directory` and `/workspace` to that dir). Import using the dotted module path RELATIVE to that working directory: for a flat repo, the full repo-root path (e.g. `from src.module import ...`); for a component, the SUBDIR-RELATIVE path per the domain skill (e.g. inside `backend/`, `from app.main import ...` — NEVER a `backend.` prefix). Read the source path and the domain skill to pick the right root.
- Import the module under test by its exact dotted path (e.g. `import package.module` or `from package.module import ...`). Read the source file to confirm the exact path before writing the import.
- A thin entrypoint (a module whose only top-level executable code is an `if __name__ == "__main__":`
  guard delegating elsewhere) has no independently testable logic — emit at most a faithful minimal
  check (it imports cleanly / the wired callables exist) in its OWN module.

## Floating-Point
- Compute expected floats dynamically (e.g. `math.pi * r ** 2`) and compare with `math.isclose()`.
- For overflow beyond `sys.float_info.max`, force and assert `float('inf')` explicitly.
