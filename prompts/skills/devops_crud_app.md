---
skill_id: devops_crud_app
type: domain
triggers: [crud]
nodes: [devops]
---
ARCHETYPE: CRUD / database-backed web service — deploy to Google Cloud Run with a managed database.

## Inherits the REST API rules
- All of the REST API archetype applies: multi-stage non-root Dockerfile, `PORT`-driven server, WIF auth, `deploy-cloudrun` — plus the database concerns below.

## Database connectivity
- The service connects to Cloud SQL. The deploy step attaches the instance via the Cloud Run `--add-cloudsql-instances` connection (or the Cloud SQL Auth Proxy), referencing `${{ secrets.CLOUD_SQL_CONNECTION_NAME }}`.
- Read DB credentials/DSN from environment variables (e.g. `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `DB_HOST`/socket path) sourced from repository secrets — never inline them.

## Migrations
- If the app has a schema/migrations step, add a workflow job/step that runs migrations against the database BEFORE the new revision serves traffic (a migrate step gated on the same WIF auth).

## .env.example
- List the datastore connection variables (names + placeholders only: `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `CLOUD_SQL_CONNECTION_NAME`, …) plus `PORT`.
