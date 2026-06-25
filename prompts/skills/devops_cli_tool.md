---
skill_id: devops_cli_tool
type: domain
triggers: [cli]
nodes: [devops]
---
ARCHETYPE: CLI tool / library. App SHAPE only — the publish-to-GitHub-Release mechanics live in the `deploy_github_release` platform skill.

DEPLOY TARGET: GitHub Releases — follow the release platform guidance (`deploy_github_release`).

## Hard rule
- Generate **NO Dockerfile** (`dockerfile_content` MUST be null) and **NO Cloud Run deploy step**. A CLI/library has no long-running server to deploy. Deploying it to Cloud Run is a hard error.

## deploy.yml (the build / test steps)
- Trigger on push to the default branch (build + test) and on a version tag (`tags: ['v*']`) for the release/publish job.
- Build matrix across the relevant runtime versions for the application's language (e.g. multiple language/runtime versions and, where applicable, OS targets).
- Steps: check out → set up the language runtime → install deps → build → run the test suite → run the lint/style check. The package/release job runs only on a version tag — its mechanics come from the `deploy_github_release` platform skill.
- For the build / test / lint steps, run the **canonical project commands supplied in the prompt verbatim** (e.g. the given `build_cmd`, `test_cmd`, `lint_cmd`). Do NOT invent or version-pin extra linters/formatters/type-checkers (no bare `ruff check`, `mypy`, `eslint`, … unless it IS the supplied command) — a CI stricter than what the code was validated against fails immediately. If no lint command is supplied, omit the lint step.

## .env.example
- Usually unnecessary for a CLI; include only if the tool reads runtime configuration from the environment.
