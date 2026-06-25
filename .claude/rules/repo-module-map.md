---
paths:
  - "src/**"
---

# Repo module map (where to find things)

Entrypoint: `main.py` → `src/nexus/runner.py` `main()` (CLI parsing in `parse_args`); `main()` is a thin
dispatcher that resolves the run and calls `run_executor` (with `--idea --auto-execute` it dispatches the
first ticket, ADR 0017). Four planes under `src/` (ADR 0021 physical split — control / worker / infra +
shared; supersedes ADR 0012's virtual separation):

**`src/shared/core/`** — engine SSOTs:
- `models.py` — `RUNS_BASE`, `WorkspacePaths`, `PipelineTelemetry` (per-agent tokens/cost/**plane**/**duration** + `by_plane()`/`merge()`/money-only `finops_report()`), `GlobalPipelineContext` (`save_checkpoint`/`load_checkpoint`), `BatchState` (E3 batch checkpoint, `kind="batch"` → `reports/batch_state.json`; E5 adds `app_telemetry`/`nexus_merged`/`budget_marker`; E6 adds `released_tag`), `DevOpsManifests` (E4 deploy config: `archetype`/`dockerfile_content`/`workflow_content`/`env_scaffold_content`).
- `config.py` — `ROLE_MODELS` (role→(model, label)), `AGENT_PLANE` (label→plane, E5 FinOps rollup), `PIPELINE_APP_BUDGET_USD`/`PIPELINE_APP_BUDGET_FLOOR_USD` (the money-only application budget — ADR 0022; `PIPELINE_BUDGET_TOKENS` is report-only since E5), `RELEASE_VERSION_BUMP` (E6 release tag bump level, default minor), `MODEL_PRICING_MATRIX`, `estimate_gemini_cost_usd`, `instructor_client` (built with a `GEMINI_REQUEST_TIMEOUT` `http_options` ceiling — every structured call is wall-clock-bounded), `check_environment(require_forge=…)` (with `--auto-merge` also requires `gh` + `GITHUB_TOKEN`).
- `observability.py` — `log`, `reconfigure_logging`, `log_token_usage` (telemetry-first), `log_finops_summary`, `describe_finish_reason`.
- `runs.py` — `Projects` store + `allocate_run_dir` + `slugify` (run-layout SSOT; see [run-layout-and-cli](run-layout-and-cli.md)).
- `docker_adapter.py` — `run_in_image` / `execute_in_sandbox` (sandbox least-privilege; see [qa-sandbox-hardening](qa-sandbox-hardening.md)).
- `environments.py` — `SUPPORTED_ENVIRONMENTS` registry (per-language image + build/test/setup/`lint_cmd`/format cmds + cache_volume). `lint_cmd` (verify-only) is the SSOT the `--scaffold-deploy` CI runs verbatim (engine-green ⇒ CI-green); the paired `format_cmd` autofixes what `lint_cmd` verifies. Each env also carries an `authoring_contract` (language-neutral bullets the SA/TPM surface to the building agents — chiefly the dependency-manifest convention) + a `dependency_manifest` scalar (the manifest `setup_cmd` restores from), exposed via `dependency_manifest(env_id)` — the runtime-axis twin of the deploy `runtime_constraints`; see [agent-contracts](agent-contracts.md) (the `## Runtime Contract` prose chain) and [engine-language-agnostic](engine-language-agnostic.md). ALSO `SUPPORTED_DEPLOY_TARGETS` (the WHERE-it-deploys SSOT, sibling to the runtime registry — `archetypes`/`skill`/`runtime_constraints`/`requires_public_invoker`) + `deploy_target_for_archetype`/`deploy_skill_for_target`/`deploy_target_skills`; see [deploy-scaffolding-and-ci-parity](deploy-scaffolding-and-ci-parity.md) §5.
- `prompts.py` — `build_agent_context`, `get_system_prompt*`, `generate_repo_map` (skill routing: [skill-routing-frontmatter](skill-routing-frontmatter.md)).

**`src/shared/utils/`** — `subprocess_helpers.py` (`parse_claude_usage`, streaming, `sanitize_for_argv` — strips C0/NUL from every subprocess argv, the SSOT both `forge` and `runner._run_checked` call; + `detect_claude_quota_block`/`ClaudeCliQuotaExhausted` — recognize a Claude Developer-CLI subscription session/usage-limit block (word-boundary markers) and fail fast with a `🚨 PROVIDER QUOTA HALT`, an infra condition distinct from a wrong-work agent), `git_helpers.py`,
`llm.py` (`run_structured_llm` + `_relocate_jinja_system_messages` — demotes a `{{ }}`/`{% %}`-bearing system message to a user turn so instructor's GenAI guard doesn't reject a config-teaching prompt, e.g. DevOps `${{ secrets.* }}`), `api_retry.py` (`with_api_retry`), `redaction.py` (`redact`),
`forge.py` (`open_pr`/`approve_pr`/`merge_pr` — gh-backed PR auto-merge seam, E2 / `--auto-merge`; plus `list_remote_tags`/`push_tag` — the E6 `--release` annotated-tag seam, via a private `_run_git` that mirrors `_run_gh`'s sanitize + `GH_NETWORK_TIMEOUT` boundary).

**`src/nexus/`** (control plane — orchestration + FSM + planning) — `runner.py` (`main()` dispatcher +
`run_executor` per-ticket FSM + `prepare_ticket_run` cfg-wiring/allocation, shared by `--run`/`--auto-execute`
+ `finalize_pr` — the E2 success-path PR step (open→approve→merge via `forge`, behind `--auto-merge`) +
`run_batch` / `_load_or_init_batch` — the E3 multi-ticket loop driving ALL tickets to `main` (with
`--auto-execute`, which now implies `--auto-merge`) + `enforce_financial_circuit_breaker(ctx, budget_usd)` —
the **money-only** breaker (ADR 0022 / E5), gated on the *remaining* application budget threaded into
`run_executor(budget_usd_ceiling=…)`; `run_batch` accumulates spend in `BatchState.app_telemetry`, stops
cleanly at `PIPELINE_APP_BUDGET_FLOOR_USD`, and `write_app_finops_report` writes `app_finops_report.json`
(per-role/plane/time) in a `finally` + `PipelineHalt` — the catchable FSM-halt exception
`_abort_with_incident` raises (so the batch records `failed` and stops; `main.py` maps an uncaught one to
exit 1) + the step-3.6 lint loop (`LINT_GATE_MAX_REROUTES`, `_LINT_FEEDBACK_PREAMBLE`) + `reconcile_feedback_routing(review_report, arbiter_verdict)` —
the routing-coherence SSOT (ADR 0024) that assigns the two isolated feedback channels: a coherence floor
(feed a channel only for a rejected side, #18) + Arbiter `developer`/`qa` authority over a Reviewer misroute
(#25); `run_batch` lazily
imports `run_devops_scaffold` to break the `deployment → nexus` cycle, ADR 0021. + `finalize_release` /
`compute_next_tag` — the E6 `--release` terminal phase (after the optional deploy-scaffold): clone `main`,
resolve the next `v*` (`compute_next_tag`, repo-derived via `forge.list_remote_tags`), push an annotated tag
(`forge.push_tag`); idempotent via `BatchState.released_tag`, ADR 0023), `agents/{po,sa,tpm}.py`
(PO/SA/TPM agents), `nexus_runner.py` (`run_nexus` + `get_tasks_for_nexus_run` — planned ticket ids in TPM
order, consumed by `--auto-execute`), `state.py` (`NexusState` checkpoint).

**`src/development/`** (worker plane — code generation + quality gates) — `gates.py`
(build/test/**lint** (`run_lint_gate` + `classify_lint_findings`)/SAST gates + `run_format_pass` autofix +
`build_failure_is_environmental` + `build_failure_is_test_only` + `lint_failure_is_tooling` (a malformed
`lint_cmd` → `ENVIRONMENT/LINT-TOOLING HALT`, ADR 0025) + `_FILE_REF_RE` (parses both colon and MSBuild
parenthesis diagnostic forms, ADR 0025) + `missing_dependency_manifest`/`annotate_missing_manifest` — the
registry-keyed missing-manifest backstop that banners a restore-installed-nothing failure so it isn't
mislabelled a code defect), `agents/{techlead,developer,qa,reviewer,techwriter,arbiter}.py`.

**`src/deployment/`** (infra plane — CI/CD scaffolding) — `agents/devops.py` (the DevOps agent),
`provision/scaffold.py` (`run_devops_scaffold` / `_env_ci_commands` / `_repo_has_source` /
`_nexus_environment_ids` / `DEVOPS_MAX_RETRIES` — the E4 post-batch deploy-scaffolding terminal phase, behind
`--scaffold-deploy`, clones `main` onto `chore/devops-scaffold`, merges via `finalize_pr`), `provision/gates.py`
(`run_devops_gate(repo_dir, archetype)` deploy-manifest static lint — YAML + Dockerfile directives + the
archetype-aware public-invoker (403-class) and repo-derived-service-name (overwrite-class) checks for a
`requires_public_invoker` target, ADR 0026). The `devops` node force-loads the
archetype skills (`devops_{rest_api,crud_app,cli_tool}.md`, app shape) PLUS the deploy-target platform skills
(`deploy_{gcp,github_release}.md`, deploy mechanics) via `_archetype_guidance` + `deploy_target_skills()`. See
[agent-provider-model-map](agent-provider-model-map.md), [deploy-scaffolding-and-ci-parity](deploy-scaffolding-and-ci-parity.md).

Other: `prompts/system/` (per-role prompts) + `prompts/skills/` (gated fragments); `docker/*.Dockerfile`
(sandbox images, built by `scripts/build_sandbox_images.sh`); tests in `tests/` (WSL-only — see
[run-tests-via-wsl](run-tests-via-wsl.md)). Runtime control flow: [pipeline-fsm-loops](pipeline-fsm-loops.md);
agent contracts: [agent-contracts](agent-contracts.md). Related: [workspace-topology](workspace-topology.md).
