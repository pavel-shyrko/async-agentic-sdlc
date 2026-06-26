---
skill_id: react_frontend
type: domain
triggers: [frontend, react]
nodes: [developer, qa]
---
LANGUAGE TARGET: React / Node.js — production-code rules for a React frontend in a fullstack monorepo.

## Project layout
- All frontend source code lives under `frontend/` (relative to the repo root). Created with Create React App or Vite per the blueprint; entry point: `frontend/src/index.tsx` (or `.jsx`).
- Dependency manifest: `frontend/package.json` — declare ALL runtime AND dev dependencies with pinned versions. The toolchain restores from `npm install` inside the `frontend/` directory.
- The `frontend/Dockerfile` uses a multi-stage build: `npm run build` in a Node build stage, then copies the output (`build/` or `dist/`) into an Nginx runtime stage.

## React conventions
- Use **functional components and hooks exclusively** — no class components.
- Manage component state with `useState`; side effects with `useEffect`; shared state with Context API or a lightweight state manager per the blueprint.
- All API communication MUST go through the backend REST API — never access a database or external service directly from the frontend.
- The backend API base URL MUST be sourced from the `REACT_APP_API_URL` (CRA) or `VITE_API_URL` (Vite) environment variable, with a safe default pointing to the local development backend (e.g. `http://localhost:8000`). Never hardcode a deployed URL in source code.

## API integration
- Use `fetch` or `axios` for HTTP calls; centralize API calls in a dedicated service module (e.g. `frontend/src/api/client.ts`).
- Handle loading and error states explicitly in every component that fetches data — never leave the UI in an undefined state on network failure.
- Validate or type-guard every API response before rendering (TypeScript interfaces or PropTypes aligned to the backend Pydantic schemas).

## Testing
- Use `npm test` (Jest + `@testing-library/react`) for component and integration tests.
- Test files live alongside their components with `.test.tsx` / `.test.jsx` suffix, OR under `frontend/src/__tests__/`.
- Every component that fetches data or renders user-facing state MUST have at least one test covering the happy-path render and one covering an error/loading state.
- Mock `fetch`/`axios` at the module boundary in tests — never make real HTTP calls in the test suite.
- **Test runner context**: `npm test` runs from the `frontend/` directory. All imports are relative to `frontend/src/` — do NOT use `frontend/src/` as a prefix in import paths inside test files.
- **Separate test execution**: frontend tests (`cd frontend && npm test`) run independently of backend tests; do not import from `backend/` or mix test frameworks.

## Repository hygiene
- Generate `frontend/.gitignore` with Node/React-specific patterns: `node_modules/`, `dist/`, `build/`, `.env.local`, `.env.development.local`, `.env.test.local`, `.env.production.local`, `.DS_Store`, `coverage/`, `.eslintcache`.

## Nginx runtime (frontend/Dockerfile)
- The Nginx stage MUST listen on `$PORT` (injected by Cloud Run). Use an `envsubst`-based entrypoint or a template config to substitute `$PORT` into the Nginx `listen` directive at container startup; never hardcode port 80 or 3000.
- Serve the React build output from `/usr/share/nginx/html`; configure a catch-all `try_files $uri /index.html` rule for single-page app routing.
