# 0017 — Nexus → Executor Auto-Dispatch (`--auto-execute`, E1)

## Status

Accepted (extends [0012](0012-virtual-separation-monorepo-planes.md), [0015](0015-unified-project-run-topology.md))

## Context

The two planes met only by the operator's hands. `main()` (`src/executor/runner.py`) expanded an idea
(`--idea` → `run_nexus`) into `epic.md` / `blueprint.md` / `TASK-*.md` and then **returned** — to actually
build anything the operator had to issue a *second*, separate command (`--run <project> -f TASK-01`). Plan
and execute were one logical workflow split across two invocations, with the project slug copied by hand
between them.

The blocker to closing that gap was structural, not cosmetic: the entire per-ticket executor flow
(re-anchor logging → `check_environment` → `bootstrap_session` → TechLead → the ~350-line FSM self-heal
`while` loop → success/abort) was **inlined inside `main()`**, not a callable function. `bootstrap_session`
and `finalize_transaction` were already standalone, but the orchestration body was not — so chaining
plan→execute in one process meant either duplicating that body or extracting it. Two smaller latent gaps
rode along: the `--idea` branch silently **dropped `--push`** (it built a `RunConfig` without forwarding
`args.push`), and the `--run` setup block (cfg wiring + run-dir allocation) was duplicated inline with no
shared seam for a second caller.

## Decision

Add a `--auto-execute` flag that, after planning, dispatches the Executor for the **first** planned ticket
in the same invocation — implemented primarily as a **safe extraction** that turns the per-ticket flow into
a reusable callable (the foundation for E2 multi-ticket and E3 failure-policy work).

- **CLI flag** — `--auto-execute` (`store_true`), meaningful only with `--idea`; `RunConfig.auto_execute:
  bool = False`. The `--idea` branch now also forwards `push=args.push` and `auto_execute=args.auto_execute`
  (closing the dropped-`--push` gap).
- **Extract `run_executor(cfg, run_dir, resume_checkpoint=None) -> bool`** — the executor body is lifted
  **verbatim** out of `main()` into this async function. It already used only `cfg.*`, `run_dir`,
  `resume_checkpoint`, module constants, and module-level node fns, so the lift needs no new parameters.
  Returns `True` on the success path; a halt still writes an incident and `sys.exit(1)` via
  `_abort_with_incident` (unchanged). The direct `--run` / legacy / resume paths now simply *call* it, so
  their behavior is byte-identical.
- **Extract `prepare_ticket_run(projects, project, cfg, ticket_id) -> Path | None`** — the shared ticket
  setup (`cfg.repo = cfg.repo or project.repo`, base branch, ticket id, resolve the ticket markdown via
  `_resolve_ticket_file`, load its body as `cfg.description`, allocate the `exec` run dir). Returns `None`
  *without allocating* when the ticket file can't be resolved. Reused by both `--run` and `--auto-execute`.
- **Task enumeration — `get_tasks_for_nexus_run(run_dir) -> list[str]`** (`src/nexus/nexus_runner.py`).
  Returns the planned ticket ids in **true TPM order**. Primary, authoritative path: load the run's
  `reports/checkpoint.json` (`NexusState`) and map `state.tasks` **preserving list order** — the list
  already encodes TPM order, so no sorting (and arbitrary model-authored ids are handled). Fallback when no
  / unreadable checkpoint: glob `artifacts/*.md` (minus `epic`/`blueprint`) with a **natural numeric** sort
  (`TASK-2` before `TASK-10`, never lexicographic). Returns `[]` when there is nothing to run. The executor
  imports it lazily, exactly as it already imports `run_nexus` — **Nexus never imports the executor plane**
  (ADR 0012 import discipline preserved).
- **Dispatch lives in `main()`, the entry layer — not in Nexus.** After `run_nexus`, when `cfg.auto_execute`:
  enumerate tickets → `prepare_ticket_run(..., tickets[0])` → `await run_executor(cfg, run_dir)`. Only the
  **first** ticket is dispatched (E1 scope; multi-ticket is E2).
- **Exit-code discipline** — planning *succeeded*, so every auto-execute skip (no `--repo` on the project /
  no tickets planned / first ticket file missing) logs a clear `⏭️` warning and returns, exiting **0**
  (nothing to execute ≠ failure). The process exits **1** only on a genuine executor halt *inside*
  `run_executor`.
- **Fail-fast preflight** — when `cfg.auto_execute`, `check_environment()` runs **once up front**, before
  `run_nexus`, so a missing `docker` / `claude` / `bandit` aborts before any planning tokens are spent.
  `run_executor` still calls it again for the non-auto paths (idempotent).

## Consequences

- **Pros**: a single `--idea … --repo … --auto-execute` invocation now goes idea → plan → built &
  committed first ticket, with no hand-copied slug. The extraction is the larger win: the per-ticket flow is
  now a reusable `run_executor` callable, the direct seam for E2 (iterate all tickets) and E3 (failure
  policy / non-exiting halts). `--run` / resume / legacy-direct are a **pure lift** — the only logic change
  on those paths is `return` → `return True` — so existing behavior and tests are unchanged. The
  long-dropped `--push` on the `--idea` branch is fixed. Task order is taken from the authoritative
  checkpoint, not a fragile filename sort.
- **Cons / constraints**: only the **first** ticket auto-runs — the remaining tickets still need manual
  `--run` calls (E2 closes this). A halt in the auto-run `sys.exit(1)`s the whole process, which is correct
  for a single ticket but is exactly the behavior E3 must convert to a non-exiting return before
  multi-ticket dispatch is safe. Auto-execute couples planning spend to the executor's heavier preflight
  (docker/claude/bandit), accepted and mitigated by running `check_environment` up front. The
  checkpoint-first task order means a hand-deleted checkpoint silently falls back to the on-disk artifact
  glob.
