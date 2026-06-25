---
paths:
  - "src/development/gates.py"
  - "src/development/agents/*.py"
  - "src/nexus/runner.py"
  - "src/nexus/nexus_runner.py"
  - "src/shared/core/prompts.py"
  - "src/deployment/provision/scaffold.py"
  - "src/deployment/provision/gates.py"
---

# Engine must stay language-agnostic

Language-specific knowledge belongs ONLY in the env registry (`SUPPORTED_ENVIRONMENTS` +
`QA_LANGUAGE_PROFILES` in `src/shared/core/environments.py`), Docker images, and skills whose
frontmatter declares a language `triggers:`. **Zero `if lang == "..."` branches or per-language dicts
anywhere else.**

## Rule

When editing any file covered by this rule, **never** introduce:
- A dict keyed by a language/stack identifier (e.g. `{"dotnet": ..., "python": ...}`).
- An `if env_language(...) == "node"` (or `"python"`, `"dotnet"`, `"go"`) conditional.
- A hard-coded list of file extensions (`".cs"`, `".py"`, `".ts"`, …).
- A host-side function that inspects the repo for language-specific artefacts (e.g. `eslint.config.js`,
  `*.csproj`) — that logic belongs in the env's `lint_cmd` / `build_cmd` as a shell self-guard.
- A per-language error/traceback marker tuple (e.g. `("Traceback (most recent call",`)) — use
  `failure_origin_markers(environment_id)` from the registry.
- A hard-coded build-artefact directory name to prune from the repo map (e.g. `"__pycache__"`) — use
  `repo_map_ignore_dirs(environment_id)` from the registry.

## Correct pattern

Add a field to the relevant env entry in `SUPPORTED_ENVIRONMENTS` / `QA_LANGUAGE_PROFILES`, expose it
via a small helper in `environments.py`, and call that helper generically. The engine has NO idea which
language it is handling.

| Need | Wrong (in engine) | Right (in registry + helper) |
|---|---|---|
| File extensions for regex | hardcoded `".cs\|.py\|.ts"` | `all_source_extensions()` |
| Language routing | `_EXT_LANG = {".cs": "dotnet", …}` | `extension_language_map()` |
| Orphan-test detection | `_ZERO_TEST_SIGNALS = {"dotnet": …}` | per-env `empty_test_markers` / `ran_test_markers` |
| Failure-origin slice | `_TRACEBACK_MARKERS = ("Traceback",…)` | `failure_origin_markers(env_id)` |
| Repo-map pruning | `if name == "__pycache__"` | `repo_map_ignore_dirs(env_id)` |
| Lint no-op guard | `if not _has_eslint_config(repo_root)` | shell self-guard inside env's `lint_cmd` |
| Dependency-manifest name | `if lang == "python": "requirements.txt"` | `dependency_manifest(env_id)` (per-env scalar; surfaced to the agents as `authoring_contract` prose) |

## Why

A multi-stack factory must be extensible by adding ONLY a registry entry + Docker image + a
language-`triggers` skill. Any hardcoded language table in `src/` is an invisible edit the developer
must remember on each new stack, and silently breaks non-target-language runs in the meantime.

The same registry-driven discipline governs **deployment targets**: `SUPPORTED_DEPLOY_TARGETS`
(`environments.py`) is the SSOT for *where* an app deploys, consumed via `deploy_target_for_archetype` /
`deploy_skill_for_target` / `deploy_target_skills`. A deploy target is a deployment classification, not a
programming language — adding a future cloud is one registry entry + one `prompts/skills/deploy_<cloud>.md`,
never a hardcoded branch. See [deploy-scaffolding-and-ci-parity](deploy-scaffolding-and-ci-parity.md) §5.

See also: [prompt-language-independence](prompt-language-independence.md) (same constraint for prompts).
