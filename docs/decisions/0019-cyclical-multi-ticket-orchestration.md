# 0019 — Cyclical Multi-Ticket Orchestration: Drive Every Planned Ticket to `main` (`run_batch`, `BatchState`, `PipelineHalt`, E3)

## Status

Accepted (extends [0012](0012-virtual-separation-monorepo-planes.md) import discipline,
[0017](0017-nexus-executor-auto-dispatch.md) `run_executor`/`prepare_ticket_run` seam,
[0018](0018-auto-merge-pr-loop-closure.md) `--auto-merge` loop closure)

## Context

After E1 (auto-dispatch the first ticket) and E2 (merge it to `main`), the autonomy loop still stopped after
**one** ticket. Nexus planned the full `Epic → Blueprint → TASK-*.md` set, but the operator launched each
subsequent ticket by hand — `--idea --auto-execute` ran only `tickets[0]`
([runner.py, the old first-ticket block](../../src/executor/runner.py)). The remaining gap was to drive
*all* planned tickets in TPM order so the full application lands on `main` from a single invocation.

Two facts shaped the design:

- **Task enumeration was already solved.** `get_tasks_for_nexus_run(run_dir)` (ADR 0017) returns every
  ticket id in TPM order. The batch only needed to *loop* it.
- **The real blocker was the halt path.** `_abort_with_incident` ended in `sys.exit(1)`
  ([runner.py:697](../../src/executor/runner.py#L697)). A naïve loop in `main()` would have the **whole
  process die on the first ticket's halt** — no chance to record which tickets had merged, and therefore no
  batch-level resume. A halt had to become *catchable*.

A structural correctness constraint also forced the merge coupling: every ticket clones `main` **fresh** on
its own `feat/ticket-<id>` branch ([bootstrap_session](../../src/executor/runner.py#L183)), so `TASK-02`
sees `TASK-01`'s work **only if** `TASK-01` already merged. A multi-ticket batch is incoherent unless each
ticket lands on `main` before the next clones it — i.e. E3 depends hard on E2.

## Decision

Extend `--auto-execute` to drive **all** planned tickets in order, one merged ticket at a time, behind a
catchable halt and a resumable batch checkpoint.

- **`PipelineHalt` — a catchable FSM halt.** A new exception ([runner.py:35](../../src/executor/runner.py#L35));
  `_abort_with_incident` still logs the header, writes `incident_report.json`, and persists/prints FinOps —
  then `raise PipelineHalt(header)` instead of `sys.exit(1)` ([runner.py:714](../../src/executor/runner.py#L714)).
  The entrypoint [main.py](../../main.py) converts an uncaught `PipelineHalt` to `sys.exit(1)`, so every
  **single-ticket** path (`--run`, `--resume` of an exec run, legacy direct) exits exactly as before. Only
  FSM halts become `PipelineHalt`; the infra `sys.exit(1)`s (`_run_checked` clone/push, `finalize_pr` merge)
  stay `SystemExit`, so the batch's `except PipelineHalt` deliberately does **not** swallow them.
- **`run_batch(...)` — the batch loop** ([runner.py:765](../../src/executor/runner.py#L765)). Iterates
  `get_tasks_for_nexus_run` in TPM order: skip tickets already merged, `prepare_ticket_run` + `run_executor`
  the rest. On success it appends to `completed` and checkpoints; on `PipelineHalt` it records `failed`,
  checkpoints, and `sys.exit(1)` — **stop the batch on the first unrecoverable halt** (failure policy).
  Lives in `main()` (the entry/worker layer) — Nexus still never imports the executor (ADR 0012 held).
- **`BatchState` — the batch checkpoint** ([models.py:317](../../src/shared/core/models.py#L317),
  `kind="batch"`): `{project_slug, nexus_run, tickets, completed, failed}`. Persisted as
  `reports/batch_state.json` **beside** the Nexus planning checkpoint (sibling of the `kind="nexus"`
  `checkpoint.json`), because the batch is scoped to a Nexus run and a bare `--resume <project>` already
  resolves to the latest Nexus run. `_load_or_init_batch` loads it (resume) or mints a fresh one.
- **`--auto-execute` ⇒ all tickets, and implies `--auto-merge` (hence `--push`).** Because the batch is
  incoherent without per-ticket merge to `main`, `parse_args` turns auto-merge on for the `--idea` path
  (`auto_merge = args.auto_merge or args.auto_execute`). One flag now plans then drives the whole app to
  `main`. The single-ticket `--run … --auto-merge` path is unchanged.
- **Batch-aware resume.** A bare `--resume <project>` whose latest Nexus run has a `batch_state.json`
  sidecar **re-enters `run_batch`** (skipping merged tickets) instead of re-planning. The failed ticket is
  re-run **fresh** — a new exec run cloning the now-updated `main` (which contains all previously-merged
  tickets); resuming its stale exec checkpoint would clone an out-of-date `main`. `--resume` forces
  `auto_merge`/`push` on and runs the `require_forge` preflight.

## Consequences

- **Pros.** A single `--idea "…" --repo … --auto-execute` invocation now goes idea → plan → **every ticket
  built, reviewed, committed, PR-merged into `main` in order** — the full autonomy loop closes across the
  whole application, not one ticket. A mid-batch halt stops cleanly with a per-ticket incident, and
  `--resume <project>` continues from the failed ticket without redoing merged ones. The catchable
  `PipelineHalt` cleanly separates "the FSM halted" (a domain event the batch handles) from "the process
  must exit" (the entrypoint's concern).
- **Cons / open questions.** The financial circuit breaker is still **per-ticket** — each ticket runs
  `run_executor` with its own telemetry against `PIPELINE_BUDGET_USD`, so a batch can spend up to
  `N × PIPELINE_BUDGET_USD` before any single ticket trips. Making the budget govern the *whole application*
  (threading the remaining budget into each cycle) is its own epic — **BACKLOG E5**. Infra `sys.exit(1)`s
  (clone/push/merge) still kill the process mid-batch (resume recovers via the not-completed check);
  converting those to `PipelineHalt` is a deferred refinement. Inter-ticket ordering stays implicit via
  shared `main` (TPM order) — no explicit dependency DAG between tickets.

> Validated end-to-end on demo project `cli-python-json-csv`
> (`001_nexus_plan_…224450` → `002…005_exec_TASK-01..04`): a 4-ticket plan driven to `main` in order —
> every ticket squash-merged, **zero** incidents / breaker trips, `batch_state.json` recording
> `completed: [TASK-01..04], failed: null`. Per-ticket cost $0.42 / $0.41 / $0.65 / $0.39 = **$1.862** total
> (each measured against its own per-ticket budget — the motivation for E5).
> Archive: [iteration_19](../releases/iteration_19/iteration_19_README.md).
