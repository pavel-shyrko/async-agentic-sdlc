---
skill_id: devops_fullstack_monorepo
type: domain
triggers: [fullstack, monorepo]
nodes: [devops]
---
ARCHETYPE: Fullstack Monorepo. App SHAPE only — the GCP/Cloud Run deploy mechanics live in the `deploy_gcp` platform skill.

DEPLOY TARGET: Two Google Cloud Run services (one backend, one frontend) — follow the GCP platform guidance (`deploy_gcp`) for WIF auth, image build/push, Cloud Run deploy steps, and public-invoker grants for BOTH services.

## Repository layout contract
- All backend code lives under `/backend/`; the backend Dockerfile is at `backend/Dockerfile`.
- All frontend code lives under `/frontend/`; the frontend Dockerfile is at `frontend/Dockerfile`.
- Never move source or Dockerfiles to the repo root or cross-contaminate the directories.

## Backend Dockerfile (`backend/Dockerfile`)
- Multi-stage build: install/compile in a build stage; copy only the artifact + runtime deps into a slim runtime stage.
- Run as a NON-root user (reuse the base image's pre-existing non-root user if UID 1000 is already present; only `useradd` a fresh user when the base image has none).
- Listen on `$PORT` (Cloud Run injects it; default 8080); bind `0.0.0.0`, never localhost.
- Build context path in the workflow: `./backend`.
- End with an explicit `CMD`/`ENTRYPOINT` that starts the API server.

## Frontend Dockerfile (`frontend/Dockerfile`)
- Multi-stage build: an `npm run build` stage, then an Nginx stage that copies the static output into `/usr/share/nginx/html`.
- The Nginx config MUST substitute `$PORT` for the listen port (use `envsubst` in the `CMD` or an entrypoint script, since Cloud Run injects `$PORT`).
- Run as a NON-root user where the base image supports it.
- Build context path in the workflow: `./frontend`.
- End with `CMD`/`ENTRYPOINT` that starts Nginx.

## deploy.yml (two-service Cloud Run workflow)
- Trigger on push to the default branch.
- If you add pre-deploy build/test/lint steps, run the **canonical project commands supplied in the prompt verbatim** for EACH component separately (backend commands under the backend context, frontend commands under the frontend context). Do NOT invent extra checkers the project was not validated against.
- Deploy TWO independent Cloud Run services using the GCP platform guidance:
  - Backend service: derive the service name as `${{ github.event.repository.name }}-backend`.
  - Frontend service: derive the service name as `${{ github.event.repository.name }}-frontend`.
- Both services MUST receive a public-invoker grant (unauthenticated invocations allowed).
- The README-URL publish step MUST inject BOTH live URLs into the pre-seeded `<!-- DEPLOYMENT_URL_START -->` / `<!-- DEPLOYMENT_URL_END -->` marker pair in README.md — label the backend URL as "Backend API" and the frontend URL as "Frontend UI". Author the `run:` step as a literal block (`run: |`); do NOT use `${{ format(...) }}` expressions in any `run:` step.

## .env.example
- List runtime variables for BOTH components with placeholder values. Backend variables (e.g. `PORT`, database URLs) and frontend variables (e.g. `REACT_APP_API_URL` pointing to the deployed backend URL) must each have safe in-code defaults so either service boots with zero required configuration.
