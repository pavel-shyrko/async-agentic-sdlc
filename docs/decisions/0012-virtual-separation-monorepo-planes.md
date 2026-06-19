# 0012 — Virtual Separation: Control / Worker / Shared Plane Topology (Monorepo PoC)

## Status

Accepted

## Context

Iteration 011 left the entire engine under a single flat `src/` namespace —
`src/agents/`, `src/nodes/`, `src/core/`, `src/utils/` — with the FSM driver living
at the repository root as `orchestrator.py`. This layout conflated three
fundamentally different responsibilities under one undifferentiated tree:

1. **No boundary between control and execution.** The code that *decides what work
   to do* (future planning/deployment orchestration) and the code that *executes a
   single SDLC run* (the techlead → developer → qa → reviewer FSM) were peers in the
   same namespace. Nothing in the structure signalled where a future **control plane**
   — a planner that schedules runs, a deployer that ships approved branches — would
   live, so that expansion had no home to grow into.

2. **Shared primitives were indistinguishable from worker logic.** Cross-cutting
   building blocks (Pydantic models, env/config, observability, prompt loader, git and
   subprocess helpers) sat beside agent-specific runtime logic, so a reader could not
   tell, from the path alone, whether a module was a reusable foundation or a worker
   detail. This made the eventual cost of physically splitting the planes (separate
   packages, services, or repos) unbounded — every consumer would have to be re-traced
   by hand.

3. **The entrypoint was the FSM, not a thin shell.** `orchestrator.py` was both the
   CLI entrypoint *and* the full FSM implementation, so "where does the program start"
   and "where does a run execute" were the same 700-line file.

No business logic, FSM/DAG transition, or LLM system prompt was wrong — the problem was
purely topological: the namespace did not encode the architecture.

## Decision

Introduce a **Virtual Separation (Monorepo PoC)**: establish the plane boundaries
logically, via package topology and import discipline, *before* paying the cost of any
physical service split. This is a pure lift-and-shift — zero changes to FSM transitions,
agent behaviour, gates, or prompts.

- **Three planes under `src/`.**
  - `src/nexus/` — **Control Plane.** Scaffolded now with empty `planner.py` and
    `deployer.py` placeholders that mark the seam where run-scheduling and
    deployment orchestration will grow. It owns no runtime behaviour yet.
  - `src/executor/` — **Worker Plane.** Everything that runs one SDLC session:
    `agents/` (techlead, developer, qa, reviewer), `nodes/` (validation gates), and
    `runner.py` (the former root `orchestrator.py`, the FSM driver + testing gates).
  - `src/shared/` — **Shared Plane.** Common foundations reused across planes:
    `core/` (models, config, observability, prompts) and `utils/` (git, subprocess,
    llm, api-retry helpers).
- **A thin root entrypoint.** A new root `main.py` is the sole CLI entry point; it
  imports `main` from `src.executor.runner` and runs it under `asyncio`, replicating the
  former `if __name__ == "__main__"` tail. "Where the program starts" is now separate
  from "where a run executes."
- **Import discipline as the boundary.** All `import` statements across `src/` and
  `tests/` were rewritten to the new plane paths (`src.core → src.shared.core`,
  `src.utils → src.shared.utils`, `src.agents → src.executor.agents`,
  `src.nodes → src.executor.nodes`). Moves were performed with history-preserving
  `git mv`. The only non-import change was re-basing one `__file__`-relative anchor:
  `src/shared/core/prompts.py` `_REPO_ROOT` gained one `.parent` because the module
  moved one directory deeper, so it still resolves the repository-root `prompts/` tree.

## Consequences

- **Pros**: the architecture is now legible from the namespace — control, worker, and
  shared concerns each have an unambiguous home, and `src/nexus/` explicitly marks the
  control-plane expansion seam without committing any code to it yet; a future physical
  split (separate packages or services) becomes a mechanical extraction along an
  already-drawn line rather than an open-ended re-trace; the single `main.py` entrypoint
  decouples program start from FSM execution, so the worker plane can later be invoked by
  the control plane as a library; behaviour is provably unchanged — the full suite
  (142 tests) stays green and the entrypoint imports clean.
- **Cons / constraints**: import paths are deeper and more verbose, and the move surface
  was large (18 files relocated, repo-wide import rewrite) — a one-time churn cost paid
  against future clarity; `__file__`-relative anchors are now more fragile, as the
  `prompts.py` `_REPO_ROOT` adjustment demonstrates — any module that resolves paths by
  walking up from its own location must be re-based when it changes depth (a latent hazard
  for future moves); the separation is still *virtual* — all three planes share one
  process, one `sys.path` (repo-root-on-path, no `pyproject.toml`/packaging introduced),
  and one dependency set, so this buys structure and intent, not yet runtime isolation or
  independent deployability; and the `nexus` placeholders are inert, so the control plane
  is a promise the topology makes but the code has not yet kept.
