# Iteration 16.1 — Documentation, Licensing & Onboarding

> CHANGELOG: [v0.16.1](../../../CHANGELOG.md) · Practicum: [PRACTICUM.md](../../../PRACTICUM.md) ·
> Architecture: [ARCHITECTURE.md](../../ARCHITECTURE.md)
>
> **No ADR** — this iteration changed documentation, licensing, and meta-tooling only; there was no
> architectural/engine decision to record (the per-release ADR convention applies to feature iterations).

## Problem Statement

The engine had rich, accurate documentation but it was hard to *navigate* and beginning to *drift*:

1. **No architecture diagram of any kind.** The only pipeline picture was an aspirational ASCII line in
   `README.md` (`Product ──> Planner ──> …`) that did not match the implemented two-plane FSM. A newcomer
   could not see the real system shape at a glance.
2. **`docs/` was a flat pile with no front door.** `adr/`, `archive/`, `setup.md`, `docker-on-windows.md`,
   and `BACKLOG.md` sat side-by-side with ad-hoc cross-linking and no index — you had to already know what
   you were looking for.
3. **The onboarding guide bounced between files and omitted what the engine actually enforces.** `setup.md`
   forward-referenced `docker-on-windows.md` mid-sequence, and nothing told a new developer that startup
   `check_environment()` hard-requires `docker`/`claude`/`bandit` on PATH + `GEMINI_API_KEY` — so you could
   "finish setup" and still hit a `🚨 CRITICAL` exit with no map, and nothing described what a successful
   run looks like.
4. **No license on the engine repository.**
5. **A stale, broken root `Dockerfile`.** It `COPY`/`ENTRYPOINT`-ed the long-deleted `orchestrator.py`
   (broken since the ADR 0012 plane split) and was referenced by no build/compose/CI.

## Implemented Solutions

### Architecture documentation (C4 + Mermaid)
- **`docs/ARCHITECTURE.md`** — the C4 model in GitHub-native Mermaid: **L1** System Context (Human, engine,
  Gemini, Claude CLI, Docker, Git/GitHub), **L2** Containers (Nexus / Executor / Shared planes, prompt store,
  sandbox images, run store), **L3** Executor FSM, plus an end-to-end `sequenceDiagram` and a
  component-reference table. Plain `flowchart`/`sequenceDiagram` only (no C4-plugin syntax, which GitHub
  won't render); grounded strictly in the real code.

### docs/ restructured for navigability (history-preserving `git mv`)
- `docs/adr/` → `docs/decisions/`, `docs/archive/` → `docs/releases/`,
  `docs/{setup,docker-on-windows}.md` → `docs/guides/`; every cross-link rewritten (0 stale `docs/adr`/
  `docs/archive` tokens remain).
- New index pages: **`docs/README.md`** (front door) and **`docs/decisions/README.md`** (ADR index grouped
  by theme).

### Onboarding rewrite
- **`docs/guides/setup.md`** is now a single zero-to-first-run spine: prerequisites-at-a-glance table,
  ordered steps with per-step *verify* commands, a **pre-flight self-check that mirrors
  `check_environment()`**, a first-run golden-path walkthrough (plan → execute → resume + success/failure
  signals), an environment-variable reference table, and an expanded troubleshooting matrix.
  `docker-on-windows.md` stays the Docker deep-dive, referenced at exactly one point.

### Licensing
- **Apache License 2.0** for the engine repository (`LICENSE` + a README License section) — chosen over MIT
  for the explicit patent grant and change-notice requirement that fit a code-generating tool. Distinct from
  the **MIT** baseline the engine still injects into *generated apps* (`boilerplate.py`) — a deliberate
  engine-vs-output boundary.

### Meta-tooling & cleanup
- **`/docs-sync` and `/iteration-release` skills extended** to also synchronize the `docs/ARCHITECTURE.md`
  C4 diagrams + component table when an iteration changes *structure* (new/removed agent role, FSM route,
  external system, plane/container) — closing the same drift gap the README roster once had.
- **Removed the stale root `Dockerfile`**; corrected the `python3 orchestrator.py` example in the setup
  guide to `main.py`.

## Metrics

- **Footprint** (`git diff --stat v0.16.0..HEAD`): **42 files changed, +1047 / −332**. The bulk of "files
  changed" are the history-preserving ADR/asset renames into `docs/decisions/` (0-byte content delta); the
  real new content is `docs/guides/setup.md` (+298), `docs/decisions/README.md` (+54), `docs/README.md`
  (+43), `docs/ARCHITECTURE.md`, and `LICENSE`.
- **4 commits**: `b9459f8` (C4 + restructure), `2e6d9e4` (license + Dockerfile removal + skill extensions),
  `b49c75f` (onboarding rewrite), `a9c6949` (CHANGELOG/README sync + broken-link fix).
- **Link validation**: exhaustive sweep of every relative Markdown link across the repo → 1 broken link
  found and fixed (`analyze-run/SKILL.md` ADR-0016 path); final state 0 broken, 0 stale `docs/adr`/
  `docs/archive` tokens.
- **No engine/test impact** — documentation, licensing, and `.claude/` tooling only.
