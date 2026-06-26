---
skill_id: devops_python
type: domain
triggers: [python]
nodes: [devops]
---
## CI lint tooling setup (`ci_lint_setup_cmd`)

If `ci_lint_setup_cmd` is present in the canonical environment commands, add a dedicated CI step
**immediately before** the Lint step that runs the command **verbatim** — exactly as supplied, without
modification or extra flags.

This step installs the lint tooling on the CI runner's system PATH. It is intentionally separate from:
- `setup_cmd` — which installs project dependencies (potentially to a non-PATH location)
- The engine's sandbox image — which has the lint tooling pre-installed, unlike the CI runner

Without this step, the Lint step will fail with "command not found".
