# Iteration 24 — Deployment & tooling hardening: reachable/isolated services, environment-not-agent failures, autonomous URL publish

> ADRs: [0026-deploy-target-registry-and-reachability-gates](../../decisions/0026-deploy-target-registry-and-reachability-gates.md)
> · [0025-tooling-failures-are-environment-not-agent](../../decisions/0025-tooling-failures-are-environment-not-agent.md)
> (both extend [0020](../../decisions/0020-deploy-scaffolding-and-lint-gate.md)) ·
> CHANGELOG: [v0.25.0](../../../CHANGELOG.md) · Practicum: [PRACTICUM.md](../../../PRACTICUM.md)

## Problem Statement

After E1–E6 the engine drives "idea → merged build → deployable config → published artifact", but live runs
surfaced failures *downstream* of the gates the engine already had — the generated app deployed, then broke
where no engine gate had looked:

- **Deploy mechanics were tangled into app-shape skills**, with no SSOT for WHERE an archetype deploys. Two
  silent post-merge failures survived a parse-only manifest gate: a Cloud Run service that never granted
  public invocation (HTTP **403** on every anonymous request — the "reachability" class), and a **hardcoded**
  service name that lets one app's deploy overwrite another's live URL (the "isolation/overwrite" class).
- **The README-URL publish broke the autonomy loop.** The post-deploy/post-release step that stamps the live
  URL into `README.md` did a bare `git push` from `actions/checkout`'s **detached HEAD** (and a tag-gated
  release run has no branch at all) → `fatal: You are not currently on a branch`, then a protected default
  branch rejected it anyway. The deploy succeeded but never closed its own loop.
- **The engine misclassified tooling faults as agent defects.** A malformed `lint_cmd` (a `ruff format`
  `--extend-exclude` typo) and MSBuild parenthesis-form diagnostics (which the colon-only `_FILE_REF_RE`
  could not parse) were fed into the budgeted agent self-heal loop instead of failing fast — burning
  Developer/QA budget on errors they are structurally incapable of fixing (0/3 tickets merged on a one-flag
  typo).
- **A Claude Developer-CLI session/usage-limit block looked like a silent no-op** — the CLI emitted one
  "hit your session limit" line, edited nothing, billed 0 tokens, and the FSM had no honest halt for it.
- **The finished app shipped without a usage guide**, and dependency conventions (the manifest the toolchain
  restores from) were invisible to the planning agents.

## Implemented Solutions

### A — Deployment-target registry & reachability/isolation gates (ADR 0026)
A new **`SUPPORTED_DEPLOY_TARGETS`** registry ([environments.py](../../../src/shared/core/environments.py)) —
the WHERE-to-deploy SSOT, sibling to `SUPPORTED_ENVIRONMENTS` — carries each target's `archetypes`, `skill`,
`runtime_constraints`, and an optional `requires_public_invoker` flag, consumed via
`deploy_target_for_archetype` / `deploy_skill_for_target` / `deploy_target_skills`. Deploy *mechanics* move
into **platform skills** `prompts/skills/deploy_{gcp,github_release}.md`, split from app *shape* in the
archetype skills; the DevOps node force-loads both sets. `run_devops_gate(repo_dir, archetype)`
([provision/gates.py](../../../src/deployment/provision/gates.py)) gains two deterministic, deploy-mode-aware
assertions for a public target: **public invocation granted** (403 class) and **service name derived from the
repo context** (overwrite class) — misses feed the existing `DEVOPS_MAX_RETRIES` self-heal loop. The SA
records the target in the Blueprint; the TPM propagates its `runtime_constraints` into tickets; the building
agents satisfy them.

### B — Autonomous README-URL publish (ADR 0026)
The platform skills' post-deploy/post-release step pushes with
`git push origin HEAD:"${{ github.event.repository.default_branch }}"` — the refspec form sends the
detached-HEAD commit straight to the default-branch ref (never a hardcoded `main`), with a `[skip ci]` commit
to avoid a re-trigger loop. Branch protection is handled by a one-time `github-actions` **"Allow bypass"**
grant ([docs/guides/devops_setup.md](../../../docs/guides/devops_setup.md) §2.4). The `DEPLOYMENT_URL` /
`RELEASE_URL` markers are pre-seeded into `README.md` by the Technical Writer so the URL survives later
per-ticket regeneration.

### C — Tooling failures are environment misconfigurations, not agent defects (ADR 0025)
`_FILE_REF_RE` ([development/gates.py](../../../src/development/gates.py)) now accepts both the colon
(`file:line:col`) and MSBuild parenthesis (`file(line,col):`) diagnostic forms — repairing
`build_failure_is_test_only` and `classify_lint_findings` for every MSBuild-format stack via one
registry-derived regex. A new **`lint_failure_is_tooling`** fast-fails a malformed `lint_cmd` with an
`ENVIRONMENT/LINT-TOOLING HALT` incident instead of folding it into the budgeted cycle. A
**`missing_dependency_manifest`** backstop (registry-driven via `dependency_manifest`) banners a
restore-installed-nothing failure (a `🚨 MISSING DEPENDENCY MANIFEST` halt) so a missing
`requirements.txt`/`go.mod`/`package.json`/`.csproj` is not mislabelled a code defect.

### D — Honest halt on a Claude CLI provider-quota block
`ClaudeCliQuotaExhausted` + `detect_claude_quota_block` ([subprocess_helpers.py](../../../src/shared/utils/subprocess_helpers.py))
recognize a subscription session/usage-limit line (word-boundary markers, so an agent merely *discussing*
rate limits in output never trips it) and fail fast with a `🚨 PROVIDER QUOTA HALT` — an infrastructure
condition, distinct from an agent that produced wrong work. A new `tbf-analyze-run` root-cause class covers it.

### E — Usage guide, authoring contracts, dependency vendoring
The Technical Writer authors `docs/USAGE.md` **only on the batch's final ticket** (when the app is
functionally complete) and folds it into the final release ([techwriter.py](../../../src/development/agents/techwriter.py)).
Each environment gains an `authoring_contract` (language-neutral bullets, chiefly the dependency-manifest
convention) + a `dependency_manifest` scalar, surfaced to the SA/TPM via `_format_supported_deploy_targets`
and the platform-awareness injection ([prompts.py](../../../src/shared/core/prompts.py)). Apache-2.0 license
boilerplate (`render_apache_license`) and a per-env `.gitignore` baseline (`build_gitignore_baseline_block`,
including the `.sdlc_deps` vendor dir) round out the scaffold ([boilerplate.py](../../../src/shared/core/boilerplate.py)).

### F — Governance: protected paths, doc-sync skills, portable paths
A **PreToolUse hook** (`.claude/hooks/protect-paths.sh`, wired in `.claude/settings.json`) blocks accidental
edits to critical paths (runtime `prompts/system/`, run clones). New Claude Code skills `/tbf-code-quality`
(audit a generated app) plus the documentation/context-sync skills, and a new `relative-paths-in-docs` rule
forbidding machine-absolute paths in checked-in governance.

## Metrics / Logs Analysis

- **Diff footprint** (`v0.24.0` → working tree, src + prompts): **30 files, +1093 / −148**. Heaviest:
  `src/shared/core/boilerplate.py` (+254: license + gitignore baseline), `src/shared/core/environments.py`
  (+154: deploy-target registry + authoring contracts), `src/development/gates.py` (+123: diagnostic-parse +
  missing-manifest backstop), `src/development/agents/techwriter.py` (+83: usage guide),
  `src/nexus/runner.py` (+72), `src/shared/core/prompts.py` (+63: deploy-target awareness),
  `src/shared/utils/subprocess_helpers.py` (+60: quota detection). Plus deploy platform skills
  `deploy_gcp.md` (+83) / `deploy_github_release.md` (+49).
- **Tests:** **+811 / −82 across 11 framework suites** (`test_prompts` +189, `test_gates` +139,
  `test_techwriter` +125, `test_devops` +93, `test_environments` +88, `test_subprocess_helpers` +67,
  `test_orchestrator` +79, …). Suite green + bandit clean (validated via WSL — see below).
- **ADRs:** 0025 (tooling-not-agent) + 0026 (deploy-target registry & reachability gates), both extending 0020.

> Validate locally via WSL (from the repo root):
> `wsl -e bash -lc "source venv/bin/activate && GEMINI_API_KEY=test-key python3 -m unittest discover -s tests"`
> · security: `wsl -e bash -lc "venv/bin/bandit -r src/"`
