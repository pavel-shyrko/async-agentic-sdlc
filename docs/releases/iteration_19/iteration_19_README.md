# Iteration 19 — Cyclical Multi-Ticket Orchestration: Drive Every Ticket to `main` (`--auto-execute`, E3)

> ADR: [0019-cyclical-multi-ticket-orchestration](../../decisions/0019-cyclical-multi-ticket-orchestration.md) ·
> CHANGELOG: [v0.19.0](../../../CHANGELOG.md) · Practicum:
> [PRACTICUM.md](../../../PRACTICUM.md)

## Problem Statement

After E1 (auto-dispatch the first ticket, ADR 0017) and E2 (merge it to `main`, ADR 0018), the autonomy
loop still stopped after **one** ticket. Nexus planned the full `Epic → Blueprint → TASK-*.md` set, but the
operator launched every subsequent ticket by hand — `--idea --auto-execute` ran only `tickets[0]`. The goal
of E3 was to drive *all* planned tickets in TPM order so the full application lands on `main` from a single
invocation.

Two facts framed the work:

- **Task enumeration was already solved** — `get_tasks_for_nexus_run` (ADR 0017) returns every ticket id in
  TPM order; the batch only needed to *loop* it.
- **The real blocker was the halt path** — `_abort_with_incident` ended in `sys.exit(1)`, so a naïve loop in
  `main()` would have the **whole process die on the first ticket's halt**, with no chance to record which
  tickets had merged and therefore no batch-level resume. A halt had to become *catchable*.

A structural correctness constraint forced the merge coupling: each ticket clones `main` **fresh** on its
own `feat/ticket-<id>` branch, so `TASK-02` sees `TASK-01`'s work **only if** `TASK-01` already merged. A
multi-ticket batch is incoherent unless each ticket lands on `main` before the next clones it — E3 depends
hard on E2.

## Implemented Solutions

### Headline — `--auto-execute` drives ALL tickets to `main`, one merged ticket at a time (ADR 0019)
- **`PipelineHalt` — a catchable FSM halt** ([runner.py](../../../src/executor/runner.py)). `_abort_with_incident`
  still logs the header, writes `incident_report.json`, and persists/prints FinOps — then `raise
  PipelineHalt(header)` instead of `sys.exit(1)`. The entrypoint [main.py](../../../main.py) converts an
  uncaught `PipelineHalt` to `sys.exit(1)`, so every **single-ticket** path (`--run`, `--resume` of an exec
  run, legacy direct) exits exactly as before. Only FSM halts become `PipelineHalt`; the infra `sys.exit(1)`s
  (`_run_checked` clone/push, `finalize_pr` merge) stay `SystemExit`, so the batch's `except PipelineHalt`
  deliberately does **not** swallow them.
- **`run_batch(...)` — the batch loop** in `main()` (the entry/worker layer — Nexus still never imports the
  executor, ADR 0012 held). Iterates the tickets in TPM order: skip ones already merged, `prepare_ticket_run`
  + `run_executor` the rest. On success it appends to `completed` and checkpoints; on `PipelineHalt` it
  records `failed`, checkpoints, and `sys.exit(1)` — **stop the batch on the first unrecoverable halt**.
- **`BatchState` — the batch checkpoint** (`src/shared/core/models.py`, `kind="batch"`):
  `{project_slug, nexus_run, tickets, completed, failed}`, persisted as `reports/batch_state.json` **beside**
  the Nexus planning checkpoint (the batch is scoped to a Nexus run, and a bare `--resume <project>` already
  resolves to the latest Nexus run). `_load_or_init_batch` loads it (resume) or mints a fresh one.
- **`--auto-execute` ⇒ all tickets, and implies `--auto-merge` (hence `--push`).** Because the batch is
  incoherent without per-ticket merge to `main`, `parse_args` turns auto-merge on for the `--idea` path
  (`auto_merge = args.auto_merge or args.auto_execute`). One flag now plans then drives the whole app to
  `main`. The single-ticket `--run … --auto-merge` path is unchanged.
- **Batch-aware resume.** A bare `--resume <project>` whose latest Nexus run has a `batch_state.json` sidecar
  **re-enters `run_batch`** (skipping merged tickets) instead of re-planning. The failed ticket is re-run
  **fresh** — a new exec run cloning the now-updated `main` (containing all previously-merged tickets);
  resuming its stale exec checkpoint would clone an out-of-date `main`.

### Docs & Claude operating-context synced to the release
- `docs/ARCHITECTURE.md` — the end-to-end sequence now shows the batch loop over all tickets; the run-layout
  notes the `batch_state.json` sidecar.
- `.claude/rules/{run-layout-and-cli,pipeline-fsm-loops,repo-module-map}.md` — record `--auto-execute`'s new
  batch semantics + the resume path, `PipelineHalt` replacing the abort `sys.exit`, and `run_batch` /
  `BatchState` / `_load_or_init_batch`.
- `docs/BACKLOG.md` — E3 marked **DONE**; new epic **E5** (application-wide FinOps budget) added from the
  validation run.

## Metrics / Logs Analysis

- **Diff footprint** (`v0.18.0` → HEAD, commit `5e7cefe`): **5 files, 346 insertions / 64 deletions**. Engine:
  `src/executor/runner.py` (+108/−20 — `PipelineHalt`, `run_batch`, `_load_or_init_batch`, `_batch_state_path`,
  the batch dispatch + batch-resume routing, `parse_args` auto-merge implication), `src/shared/core/models.py`
  (+25 — the `BatchState` model), `main.py` (+8/−2 — the `PipelineHalt → exit 1` guard). Tests:
  `test_orchestrator.py` (+178/−42 — `RunBatchTests`, `BatchResumeRoutingTests`, the reworked
  `IdeaAutoExecuteDispatchTests`, and the 6 FSM-halt tests converted from `SystemExit` to `PipelineHalt`),
  `test_models.py` (+27 — `BatchStateCheckpointTests`).
- **Test suite:** **366** tests green via WSL (359 → 366, +7 net). Bandit clean (`bandit -r src/`,
  no issues).
- **Validation run (real API + Docker + GitHub), demo project `cli-python-json-csv`**
  (`001_nexus_plan_…224450` → `002…005_exec_TASK-01..04`): a **4-ticket plan driven to `main` in order** —
  every ticket built, reviewed, committed, pushed, PR-opened, **approved via `GITHUB_REVIEWER_TOKEN`**, and
  **squash-merged** into `main`. `batch_state.json` recorded `completed: [TASK-01..04], failed: null`;
  **zero** incident reports / circuit-breaker trips. Per-ticket cycle counts 3 / 3 / 2 / 3 (all within the
  base retry budget, no contract amendments). Per-ticket cost **$0.4202 / $0.4100 / $0.6450 / $0.3864 =
  $1.862 total** — each measured against its own *per-ticket* $10 budget, which is precisely why a single
  application-wide budget (threading the remaining budget per cycle) is now tracked as **BACKLOG E5**.

> Validate locally via WSL:
> `wsl -e bash -lc "cd /mnt/c/code/async-agentic-sdlc && source venv/bin/activate && GEMINI_API_KEY=test-key python3 -m unittest discover -s tests"`
