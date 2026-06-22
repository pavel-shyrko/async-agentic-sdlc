# Repo module map (where to find things)

Entrypoint: `main.py` → `src/executor/runner.py` `main()` (CLI parsing in `parse_args`); `main()` is a thin
dispatcher that resolves the run and calls `run_executor` (with `--idea --auto-execute` it dispatches the
first ticket, ADR 0017). Three planes under `src/` (ADR 0012 virtual separation):

**`src/shared/core/`** — engine SSOTs:
- `models.py` — `RUNS_BASE`, `WorkspacePaths`, `PipelineTelemetry`, `GlobalPipelineContext` (`save_checkpoint`/`load_checkpoint`), `BatchState` (E3 batch checkpoint, `kind="batch"` → `reports/batch_state.json`).
- `config.py` — `ROLE_MODELS` (role→(model, label)), `PIPELINE_BUDGET_USD/TOKENS`, `MODEL_PRICING_MATRIX`, `estimate_gemini_cost_usd`, `instructor_client` (built with a `GEMINI_REQUEST_TIMEOUT` `http_options` ceiling — every structured call is wall-clock-bounded), `check_environment(require_forge=…)` (with `--auto-merge` also requires `gh` + `GITHUB_TOKEN`).
- `observability.py` — `log`, `reconfigure_logging`, `log_token_usage` (telemetry-first), `log_finops_summary`, `describe_finish_reason`.
- `runs.py` — `Projects` store + `allocate_run_dir` + `slugify` (run-layout SSOT; see [run-layout-and-cli](run-layout-and-cli.md)).
- `docker_adapter.py` — `run_in_image` / `execute_in_sandbox` (sandbox least-privilege; see [qa-sandbox-hardening](qa-sandbox-hardening.md)).
- `environments.py` — `SUPPORTED_ENVIRONMENTS` registry (per-language image + build/test/setup cmds + cache_volume).
- `prompts.py` — `build_agent_context`, `get_system_prompt*`, `generate_repo_map` (skill routing: [skill-routing-frontmatter](skill-routing-frontmatter.md)).

**`src/shared/utils/`** — `subprocess_helpers.py` (`parse_claude_usage`, streaming, `sanitize_for_argv` — strips C0/NUL from every subprocess argv, the SSOT both `forge` and `runner._run_checked` call), `git_helpers.py`,
`llm.py` (`run_structured_llm`), `api_retry.py` (`with_api_retry`), `redaction.py` (`redact`),
`forge.py` (`open_pr`/`approve_pr`/`merge_pr` — gh-backed PR auto-merge seam, E2 / `--auto-merge`).

**`src/executor/`** (worker plane) — `runner.py` (`main()` dispatcher + `run_executor` per-ticket FSM +
`prepare_ticket_run` cfg-wiring/allocation, shared by `--run`/`--auto-execute` + `finalize_pr` — the E2
success-path PR step (open→approve→merge via `forge`, behind `--auto-merge`) + `run_batch` /
`_load_or_init_batch` — the E3 multi-ticket loop driving ALL tickets to `main` (with `--auto-execute`,
which now implies `--auto-merge`) + `PipelineHalt` — the catchable FSM-halt exception `_abort_with_incident`
raises (so the batch records `failed` and stops; `main.py` maps an uncaught one to exit 1)), `nodes/gates.py`
(build/test/SAST gates + `build_failure_is_environmental`),
`agents/{techlead,developer,qa,reviewer,techwriter,arbiter}.py`.

**`src/nexus/`** (control plane) — `{po,sa,tpm}.py` (PO/SA/TPM agents), `nexus_runner.py` (`run_nexus` +
`get_tasks_for_nexus_run` — planned ticket ids in TPM order, consumed by `--auto-execute`),
`state.py` (`NexusState` checkpoint). See [agent-provider-model-map](agent-provider-model-map.md).

Other: `prompts/system/` (per-role prompts) + `prompts/skills/` (gated fragments); `docker/*.Dockerfile`
(sandbox images, built by `scripts/build_sandbox_images.sh`); tests in `tests/` (WSL-only — see
[run-tests-via-wsl](run-tests-via-wsl.md)). Runtime control flow: [pipeline-fsm-loops](pipeline-fsm-loops.md);
agent contracts: [agent-contracts](agent-contracts.md). Related: [workspace-topology](workspace-topology.md).
