---
skill_id: devops_rest_api
type: domain
triggers: [api]
nodes: [devops]
---
ARCHETYPE: REST API / web service — deploy to Google Cloud Run.

## Dockerfile
- Multi-stage build: a build stage that installs/compiles dependencies, then a slim runtime stage that copies only the artifact + runtime deps.
- Run as a NON-root user (create one and `USER` it before the entry point).
- The container MUST listen on the port from the `PORT` environment variable (Cloud Run injects it; default 8080). Bind to `0.0.0.0`, not localhost.
- End with an explicit `CMD`/`ENTRYPOINT` that starts the HTTP server.

## deploy.yml (GitHub Actions → Cloud Run)
- Trigger on push to the default branch.
- `permissions: { id-token: write, contents: read }` (required for WIF).
- Authenticate with `google-github-actions/auth` using `workload_identity_provider: ${{ secrets.GCP_WIF_PROVIDER }}` and `service_account: ${{ secrets.GCP_SERVICE_ACCOUNT }}` — NO key JSON.
- Build + deploy with `google-github-actions/deploy-cloudrun` (source or image deploy), passing the service name, `${{ vars.GCP_PROJECT_ID }}`, and `${{ vars.GCP_REGION }}`. For an image deploy, build the Artifact Registry path from `${{ vars.GCP_REGION }}`, `${{ vars.GCP_PROJECT_ID }}`, and `${{ vars.GCP_REGISTRY_NAME }}`.
- Secrets vs variables (the org is pre-provisioned this way — see docs/guides/devops_setup.md): `GCP_WIF_PROVIDER` + `GCP_SERVICE_ACCOUNT` are repository **secrets** (`${{ secrets.* }}`); `GCP_PROJECT_ID`, `GCP_REGION`, `GCP_REGISTRY_NAME` are repository **variables** (`${{ vars.* }}`). Never inline a key, project id, or region.

## .env.example
- List runtime variables the service reads (e.g. `PORT`, any datastore URL placeholder) with placeholder values only.
