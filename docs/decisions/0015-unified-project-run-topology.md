# 0015 — Unified Project & Run Topology: the Nexus⇄Executor Sync Bridge

## Status

Accepted (extends [0012](0012-virtual-separation-monorepo-planes.md), [0006](0006-fsm-state-serialization-resume.md))

## Context

ADR 0012 drew the control/worker/shared plane boundary *logically* (`src/nexus/` vs
`src/executor/` vs `src/shared/`), but the two planes still lived in **incompatible run-location
worlds** on disk:

- The **executor** allocated each run under a flat `runs/run_<uuid>/` — git-anchored and resumable
  (ADR 0006), but UUID-keyed (not human-readable) and unaware of any owning project; re-running the
  same ticket spawned a new top-level folder with no relationship to the prior one.
- The **Nexus control plane** (PO→SA→TPM) wrote its generated `epic.md`/`blueprint.md`/`TASK-*.md`
  to a hardcoded shared directory — **outside `runs/`**, with no run dir, no checkpoint, and therefore
  no resume: a planning failure halfway through SA meant re-running from the raw idea, re-paying PO.

Consequences of the split: no cross-plane lineage ("which planning run produced this ticket?"), no
Nexus resumption, no project aggregation, and a `--resume` path that only understood one checkpoint
shape. Planning and execution could not be reasoned about as one project's history.

## Decision

Make a **single run-layout SSOT** that both planes name runs through, give Nexus the same
checkpoint/resume contract the executor already had, and route `--resume` by reading the checkpoint
rather than parsing paths.

- **One run-layout SSOT** — `src/shared/core/runs.py` introduces a `Projects` filesystem store +
  `allocate_run_dir(project_dir, plane, label)`. Every run (planning OR execution) is a numbered,
  human-readable sub-dir of a per-project umbrella:
  `runs/<slug>/<NNN>_<plane>_<label>_<YYYYMMDD-HHMMSS>_<uid6>/`. `<NNN>` is `max existing + 1` within
  the project (sortable, visible order); `<plane>` is `nexus`/`exec`; `<label>` is the ticket id or
  `plan`; the `ts`+`uid6` suffix guarantees no overwrite even for two same-second runs. `slugify`
  keys the project folder; `_safe_label` preserves ticket-id case. The base (`Projects(base)`) is
  **injected**, not a module global, so tests stay hermetic against a temp dir.
- **Project umbrella manifest** — `Project` (`project.json`) captures `{slug, idea, repo,
  base_branch, created_at}` **once**; `get_or_create` reuses an existing umbrella (stacking another
  numbered run under it) so repeated runs of the same ticket share lineage, and a later run can
  back-fill a `repo` the first omitted.
- **Nexus gets a checkpoint** — `src/nexus/state.py` `NexusState` mirrors the executor's
  `GlobalPipelineContext` dump/load pattern (`save_checkpoint`/`load_checkpoint` via
  `model_validate_json`) and recomputes its `logs/`, `reports/`, `artifacts/` meta-dirs from
  `run_dir` (never persisted — like `WorkspacePaths.for_run`). It persists the phase outputs
  (`epic_text`, `blueprint_text`, `tasks`) and a `completed_phase` cursor over the ordered
  `PHASES = ("PO","SA","TPM")`, so resume **skips finished phases and reuses their artifacts** instead
  of re-invoking the agent.
- **Checkpoint as a routing discriminator** — `NexusState` carries `kind: Literal["nexus"]`.
  `main()` resolves the run dir from a checkpoint's grandparent and `_checkpoint_kind` peeks the
  `kind` field: `"nexus"` → control plane (`run_nexus(resume=…)`), absent → executor
  (`GlobalPipelineContext`). No directory-name parsing; legacy `runs/run_<uuid>/` checkpoints still
  resume via the explicit path form.
- **Project-centric CLI verbs** (`parse_args`/`main`, `src/executor/runner.py`):
  `--idea "…" [--repo R]` mints a new project + runs Nexus planning (`001_nexus_plan`);
  `--run <project> -f <ticket>` executes that ticket, loading repo + base branch from `project.json`
  and resolving the ticket body from the latest Nexus run's `artifacts/<ticket>.md`;
  `--resume <project> [NNN]` resumes run #NNN (or the latest Nexus run), with `--resume <path.json>`
  retained as the legacy explicit form.
- **Telemetry-first shared observability** — the convergence is paid for by extracting plane-agnostic
  helpers into `src/shared/core/observability.py`: `log_finops_summary(telemetry, budget_usd,
  budget_tokens)` and `log_token_usage(telemetry, …)` now take a `PipelineTelemetry` argument instead
  of reading executor module constants, so **both** planes record FinOps into one telemetry object;
  `describe_finish_reason` surfaces *why* a structured Gemini call failed (e.g. `RECITATION`).
  `src/shared/utils/redaction.py` adds a `redact()` + logger-level `RedactionFilter` so PATs /
  basic-auth URLs / bearer tokens are scrubbed from console + audit log + persisted JSON across both
  planes.

## Consequences

- **Pros**: planning and execution are one project's history — `runs/<slug>/` shows the task, the
  plane, and the order at a glance; Nexus is now resumable (a mid-plan failure restarts from the next
  phase, not the raw idea); the executor inherits human-readable, lineage-aware run dirs; one
  checkpoint contract + a `kind` discriminator means `--resume <project>` routes itself with no
  path-name parsing; the injected `Projects(base)` keeps the whole layer hermetic under test; FinOps
  and secret-redaction are uniform across both planes.
- **Cons / constraints**: the run-dir name is now load-bearing metadata (the `<NNN>_<plane>_<label>`
  contract is parsed by tooling and humans), so its grammar must stay stable; `slugify` collisions
  are resolved by suffixing (`-2`, `-3`), which can detach a later run from the umbrella a user
  expected; the SSOT only standardizes *location* — the two planes still keep separate state models
  (`NexusState` is idea/phase-shaped; `GlobalPipelineContext` is git/contract-shaped) deliberately,
  bridged only by the shared `kind`-tagged checkpoint envelope; and old `runs/run_<uuid>/`
  checkpoints resume only via the explicit-path form, never the new project verbs.
