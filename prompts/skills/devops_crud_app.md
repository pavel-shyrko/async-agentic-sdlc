---
skill_id: devops_crud_app
type: domain
triggers: [crud]
nodes: [devops]
---
ARCHETYPE: CRUD / database-backed web service. App SHAPE only — the GCP/Cloud Run + Cloud SQL deploy mechanics live in the `deploy_gcp` platform skill.

DEPLOY TARGET: Google Cloud Run with a managed database — follow the GCP platform guidance (`deploy_gcp`), including the Cloud SQL attachment and the pre-serve migration step.

## Inherits the REST API shape
- All of the REST API archetype's container shape applies: multi-stage non-root Dockerfile, `PORT`-driven server bound to `0.0.0.0`, the canonical CI build/test/lint steps — plus the database concerns below.

## Database connectivity (app shape)
- Read DB credentials/DSN from environment variables (e.g. `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `DB_HOST`/socket path) sourced from repository secrets — never inline them. The Cloud SQL instance attachment itself is a GCP deploy concern (see `deploy_gcp`).

## .env.example
- List the datastore connection variables (names + placeholders only: `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `CLOUD_SQL_CONNECTION_NAME`, …) plus `PORT`.
