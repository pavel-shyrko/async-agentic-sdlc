# Iteration 15 — Unified Project & Run Topology (Nexus⇄Executor Sync Bridge)

> ADR: [0015-unified-project-run-topology](../../adr/0015-unified-project-run-topology.md) ·
> CHANGELOG: [v0.15.0](../../../CHANGELOG.md) · Practicum:
> [PRACTICUM.md](../../../PRACTICUM.md)

## Problem Statement

ADR 0012 separated the control plane (`src/nexus/`, PO→SA→TPM planning) from the worker plane
(`src/executor/`, one ticket execution) *logically*, but on disk they lived in two incompatible
worlds. The executor allocated runs under a flat `runs/run_<uuid>/` — git-anchored and resumable but
UUID-keyed and unaware of any owning project. Nexus wrote its `epic.md`/`blueprint.md`/`TASK-*.md` to
a hardcoded shared directory **outside `runs/`** — with no run dir, no checkpoint, and therefore no
resume: a failure mid-planning meant re-running from the raw idea and re-paying PO.

The result was no cross-plane lineage ("which planning run produced this ticket?"), no Nexus
resumption, no project aggregation, and a `--resume` path that understood only one checkpoint shape.
A single project's planning and execution could not be reasoned about as one history.

Alongside this, a set of executor-loop fragilities surfaced on real multi-language runs — transient
package-feed outages mis-routed as code bugs, unused-import bounce cycles, contract paths that escaped
the sandbox, `.gitignore` patterns that swallowed source dirs — each capable of burning the retry
budget into a circuit-breaker halt.

## Implemented Solutions

### Headline — the sync bridge (ADR 0015)
- **One run-layout SSOT** (`src/shared/core/runs.py`): a `Projects` store + `allocate_run_dir` naming
  every run `runs/<slug>/<NNN>_<plane>_<label>_<YYYYMMDD-HHMMSS>_<uid6>/`, shared verbatim by both
  planes. The base is injected (`Projects(base)`) so the layer is hermetic under test.
- **Project umbrella** (`project.json`): `{slug, idea, repo, base_branch, created_at}` captured once;
  `get_or_create` stacks later runs under one umbrella so repeated runs share lineage.
- **Nexus checkpoint + resume** (`src/nexus/state.py` `NexusState`): mirrors the executor's
  `GlobalPipelineContext` dump/load, persists phase outputs + a `completed_phase` cursor over
  `("PO","SA","TPM")`, and resumes by skipping finished phases and reusing their artifacts.
- **Checkpoint as a routing discriminator**: `NexusState.kind = "nexus"`; `main()` peeks the
  checkpoint's `kind` (`_checkpoint_kind`) to route `--resume` to the right plane without parsing
  directory names. Legacy `runs/run_<uuid>/` checkpoints still resume via the explicit path form.
- **Project-centric CLI**: `--idea` (new project + Nexus planning), `--run <project> -f <ticket>`
  (execute a ticket, repo/base-branch + ticket body resolved from the project), `--resume <project>
  [NNN]`.
- **Telemetry-first shared observability** (`src/shared/core/observability.py`): `log_finops_summary`
  / `log_token_usage` take a `PipelineTelemetry` arg (no module-constant coupling), so both planes
  record FinOps into one object; `describe_finish_reason` surfaces *why* a Gemini structured call
  failed. Secret redaction (`src/shared/utils/redaction.py`) scrubs PATs/bearer/basic-auth from
  console, audit log, and persisted JSON across both planes.

### Supporting — executor-loop hardening
- **Environmental build-failure classification** (`build_failure_is_environmental`, `gates.py`): a
  network/feed-unreachable signature (`NU1301`, "Unable to load the service index", DNS/`dial tcp`,
  npm errno) is no longer mis-routed to the Developer to "fix the network" (which dropped mandated
  deps and deadlocked against the Reviewer). One cheap retry absorbs a blip; a persistent outage
  fails fast as an ENVIRONMENT/NETWORK incident.
- **Persistent package cache** (`environments.py` `cache_volume` + `docker_adapter.py`): a named
  Docker volume per environment, mounted RW only on the network-on restore phase and RO on
  build/test, so packages restored once survive container teardown and are reused across runs.
- **Deterministic post-QA cleanup** (`run_format_pass`, network-off, non-fatal): the env's
  `format_cmd` (`ruff --fix`, `goimports`, `dotnet format`, eslint) strips unused imports before the
  compile gate, killing the trivial Go "unused import = hard error" bounce cycle.
- **Contract path normalization** (`models.py`): leading-slash / `..` blueprint paths are normalized
  to safe repo-relative POSIX paths at the contract boundary, so a path can no longer escape the
  sandbox and loop the Developer on a perpetually "missing" file.
- **Canonical `.gitignore` templates** (`environments.py`): engine-curated, extension/anchored-only
  patterns injected verbatim by the TPM into `TASK-01`, so an agent-invented bare project-name pattern
  can no longer swallow a source directory out of the snapshot.
- **Repository preparation folded into `TASK-01`** (`tpm.md`): the mandatory baseline (`.gitignore` /
  `README.md` / `LICENSE`, idempotent verify-or-reconcile) leads the first business ticket instead of
  a standalone `TASK-00` iteration — removing a full extra orchestrator pass per project. The
  now-purposeless infra-only scope-discipline guardrail was retired.

### Prompt / constraint changes
- `developer.md`: authority order (Directives > context); an uncontracted file MUST carry a
  top-of-file justification (scanned by the deterministic guardrail); SCOPE DISCIPLINE rewritten to
  authorize the minimal language-required entry-point/glue a contracted build manifest needs.
- `techlead.md`: CURRENT TASK scope vs Blueprint reference; testability seams; `environment_id` stack
  declaration.
- `tpm.md`: `TASK-01` two-phase prep block; verbatim gitignore/README templates; HARD GATE on
  baseline-file placement; "never ignore a build artifact by its bare project NAME — only by
  EXTENSION or ANCHORED directory."

## Metrics / Logs Analysis

- **Diff footprint** (`v0.14.0`/`ff6fa8f` → HEAD): 109 files, ~3,958 insertions / ~1,049 deletions.
  New engine modules: `src/shared/core/runs.py` (+118), `src/nexus/state.py` (+71),
  `src/shared/utils/redaction.py` (+69). Heaviest refactor: `src/executor/runner.py` (+488) for the
  Nexus⇄executor bridge and resume routing. New tests: `test_runs.py`, `test_nexus_runner.py`,
  `test_nexus_sa.py`, `test_redaction.py`, `test_agent_context_injection.py`,
  `test_environments.py`, plus expansions to `test_orchestrator.py` (+401) and `test_gates.py` (+167).
- **Incident lineage that drove the loop-hardening** (from prior run audit logs):
  - .NET `JSON-to-CSV2` (`run_b3b85070…`): a transient NuGet `NU1301` was mis-routed to the Developer,
    which dropped mandated deps to compile offline → Reviewer rejection → circuit breaker. Fixed by
    `build_failure_is_environmental` (fail-fast) + the persistent `cache_volume`.
  - Go `json2csv` `.gitignore` swallow (`run_410195801a…`): a bare project-name ignore pattern
    dropped source files from `git add -A`. Fixed by engine-curated extension/anchored templates.
- **Hermetic e2e speedup carried in this window**: `test_pipeline_e2e.py` ~42× faster (124.7s → 2.9s)
  after mocking the per-skill `SkillRelevance` gate that had been silently absorbing ~120s of
  `with_api_retry` backoff.

> Validate locally via WSL:
> `wsl -e bash -lc "cd /mnt/c/code/async-agentic-sdlc && source venv/bin/activate && python3 -m unittest discover -s tests"`
