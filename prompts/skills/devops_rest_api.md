---
skill_id: devops_rest_api
type: domain
triggers: [api]
nodes: [devops]
---
ARCHETYPE: REST API / web service. App SHAPE only — the GCP/Cloud Run deploy mechanics live in the `deploy_gcp` platform skill.

DEPLOY TARGET: Google Cloud Run — follow the GCP platform guidance (`deploy_gcp`) for the WIF auth, image build/push, the Cloud Run deploy step, and the public-invoker grant.

## Dockerfile (the container shape)
- Location & build context: the application code lives under `backend/` (the component layout), so write the Dockerfile to `backend/Dockerfile` and build it with `./backend` as the context — all `COPY` paths are relative to `backend/` (e.g. `COPY requirements.txt .`), never `COPY backend/...`.
- Multi-stage build: a build stage that installs/compiles dependencies, then a slim runtime stage that copies only the artifact + runtime deps.
- Run as a NON-root user. Before creating a new user, check whether the base image already ships a non-root user with UID 1000 (many official runtime images do — e.g. the `app` user in .NET `aspnet`, the `node` user in Node.js). If such a user already exists, reuse it (`USER <existing-user>`) rather than calling `useradd -u 1000`, which will fail with "UID 1000 is not unique" (exit 4). Only `useradd` a fresh user when the base image has no pre-existing non-root user.
- The container MUST listen on the port from the `PORT` environment variable (Cloud Run injects it; default 8080). Bind to `0.0.0.0`, not localhost.
- End with an explicit `CMD`/`ENTRYPOINT` that starts the HTTP server.

## deploy.yml (the pre-deploy build/test/lint steps)
- Trigger on push to the default branch.
- If you add a pre-deploy build/test/lint step, run the **canonical project commands supplied in the prompt verbatim** (the given `build_cmd`/`test_cmd`/`lint_cmd`) — and run them with `working-directory: backend` (the commands are calibrated to the component root, matching the engine gates), so dependency restore and tests resolve `backend/requirements.txt` and `backend/tests/`. Do NOT invent extra linters/formatters/type-checkers the project was not validated against.
- The actual GCP deploy job (auth, image, Cloud Run, public invoker, README-URL step) comes from the `deploy_gcp` platform skill — do not re-specify it here.

## .env.example
- List runtime variables the service reads (e.g. `PORT`, any datastore URL placeholder) with placeholder values only. Every such variable MUST have a safe in-code default, so an unset variable never blocks startup — the container boots with zero configuration.
