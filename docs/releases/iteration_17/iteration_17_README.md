# Iteration 17 — Nexus → Executor Auto-Dispatch (`--auto-execute`)

> ADR: [0017-nexus-executor-auto-dispatch](../../decisions/0017-nexus-executor-auto-dispatch.md) ·
> CHANGELOG: [v0.17.0](../../../CHANGELOG.md) · Practicum:
> [PRACTICUM.md](../../../PRACTICUM.md)

## Problem Statement

The two planes were joined only by the operator. `--idea` ran Nexus planning (`epic.md` / `blueprint.md` /
`TASK-*.md`) and then **returned**; building anything required a *second*, separate command
(`--run <project> -f TASK-01`), with the project slug copied by hand between the two. Idea → working code was
one workflow artificially split across two invocations.

The reason it couldn't be chained was structural: the entire per-ticket executor flow (re-anchor logging →
`check_environment` → `bootstrap_session` → TechLead → the ~350-line FSM self-heal loop → success/abort) was
**inlined inside `main()`** rather than being a callable function — so chaining plan→execute meant either
duplicating that body or extracting it. Two latent gaps rode along: the `--idea` branch silently **dropped
`--push`** (it never forwarded `args.push`), and the `--run` setup block was duplicated inline with no seam
a second caller could reuse.

## Implemented Solutions

### Headline — one-command plan→execute (ADR 0017)
- **`--auto-execute` flag** (`RunConfig.auto_execute`), meaningful only with `--idea`: after planning, the
  engine dispatches the Executor for the **first** planned ticket in the same process. The `--idea` branch
  now also forwards `push=args.push` (fixing the dropped-`--push` gap).
- **`run_executor(cfg, run_dir, resume_checkpoint=None) -> bool`** — the executor body lifted **verbatim**
  out of `main()` into a reusable async function (returns `True` on success; a halt still writes an incident
  + `sys.exit(1)`). The `--run` / legacy / resume paths now just *call* it — byte-identical behavior; the
  only logic change on those paths is `return` → `return True`.
- **`prepare_ticket_run(projects, project, cfg, ticket_id) -> Path | None`** — the shared cfg-wiring +
  run-dir allocation (repo, base branch, ticket id, resolve ticket markdown → body, allocate `exec` dir);
  returns `None` without allocating when the ticket file can't be resolved. Reused by `--run` and
  `--auto-execute`.
- **`get_tasks_for_nexus_run(run_dir)`** (`src/nexus/nexus_runner.py`) — planned ticket ids in **true TPM
  order**: authoritative from the run's `checkpoint.json` (`NexusState.tasks`, list order preserved, no
  sort), fallback to a **natural numeric** `artifacts/*.md` glob (`TASK-2` before `TASK-10`). Imported lazily
  by the executor; **Nexus never imports the executor plane** (ADR 0012 discipline held).

### Dispatch & safety (entry layer, not Nexus)
- The dispatch lives in `main()`. Planning **succeeded**, so every auto-execute skip — no `--repo` on the
  project, no tickets planned, first ticket file missing — logs an `⏭️` warning and exits **0** (nothing to
  execute ≠ failure). The process exits **1** only on a real executor halt *inside* `run_executor`.
- **Fail-fast preflight**: when `--auto-execute`, `check_environment()` runs once **up front**, before
  planning, so a missing `docker`/`claude`/`bandit` aborts before any planning tokens are spent.

### Scope boundary
- Only the **first** ticket auto-runs (E1). Iterating all tickets is **E2**; converting a halt from
  `sys.exit(1)` to a non-exiting return (the precondition for safe multi-ticket dispatch) is **E3**. The
  extraction is deliberately the foundation for both.

### Meta-tooling (rules synced to the release)
- `.claude/rules/pipeline-fsm-loops.md` re-pinned the FSM SSOT from `main()` to `run_executor` and
  corrected the outer loop (`for … max_retries=3` → the `while` dynamic ceiling — a drift carried since
  ADR 0016). `.claude/rules/config-constant-convention.md` now records the `max_retries` outlier as
  **resolved** (`MAX_FUNCTIONAL_RETRIES`) and lists the Arbiter knobs. `.claude/rules/repo-module-map.md`
  names `run_executor`/`prepare_ticket_run`/`get_tasks_for_nexus_run` (and the previously-missing `arbiter`
  agent). `CLAUDE.md` adds `--auto-execute` to the dev commands.

### Git-auth hardening (docs)
- Documented the **env-backed git credential helper** recipe (token in `GITHUB_TOKEN`, never on disk; pass a
  clean `--repo` URL) across `docs/guides/setup.md` and `.claude/rules/run-layout-and-cli.md`, with a warning
  that a token embedded in the URL persists verbatim into `project.json` + the clone's `.git/config`.

## Metrics / Logs Analysis

- **Diff footprint** (`main` → HEAD): **7 files, 300 insertions / 27 deletions**. Engine: `src/executor/
  runner.py` (+87, the extraction + dispatch), `src/nexus/nexus_runner.py` (+32, `get_tasks_for_nexus_run` +
  `_natural_sort_key`). Tests: `tests/framework/test_orchestrator.py` (+122, dispatch + skip-path coverage),
  `tests/framework/test_nexus_runner.py` (+31, task-order: checkpoint-order vs natural-sort fallback). Docs:
  `README.md` (+23), `docs/guides/setup.md` (+26), `.claude/rules/run-layout-and-cli.md` (+6).
- **Validation run (real API + Docker), demo project `cli-python-json-csv`** (`001_nexus_plan_…172014` →
  `002_exec_TASK-01_…172119`): a single `--idea … --repo … --auto-execute --push` invocation planned **4
  tickets**, then auto-dispatched the Executor for `TASK-01`, which passed both gates on **cycle 1**,
  committed atomically on `feat/ticket-TASK-01`, and **pushed to origin** — end to end in one command.
  Cost **$0.2249 / $10.00** budget (Claude $0.1869 actual, Gemini $0.0380 est.), 16,528 tokens
  (cache-excluded). The remaining 3 tickets correctly did **not** run (E1 single-ticket scope).

> Validate locally via WSL:
> `wsl -e bash -lc "cd /mnt/c/code/token-burners-factory && source venv/bin/activate && GEMINI_API_KEY=test-key python3 -m unittest discover -s tests"`
