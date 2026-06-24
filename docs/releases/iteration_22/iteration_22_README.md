# Iteration 22 — Autonomous Release-Tagging (`--release`): close the loop to a published artifact

> ADR: [0023-autonomous-release-tagging](../../decisions/0023-autonomous-release-tagging.md) ·
> CHANGELOG: [v0.23.0](../../../CHANGELOG.md) · Practicum: [PRACTICUM.md](../../../PRACTICUM.md)

## Problem Statement

After E1–E5 the engine drives "idea in → all tickets merged on `main` → (optional) deploy config merged,"
but the **last** step stayed manual. The E4 deploy-scaffold (ADR
[0020](../../decisions/0020-deploy-scaffolding-and-lint-gate.md)) generates a release workflow that is
**tag-gated** — every archetype's publish step triggers on `tags: ['v*']` (the CLI archetype gates its
release job with `if: startsWith(github.ref, 'refs/tags/v')`). A merge to `main` runs tests but **skips** the
release job (observed in the `write-a-python-cli-utility-…` run — the `release` job rendered "This job was
skipped"). So the engine built a *deployable* application and then waited for a human to push a `v*` tag by
hand. No part of the engine pushed tags ([forge.py](../../../src/shared/utils/forge.py) covered PR
open/approve/merge only) and there was no version policy anywhere in `src/`. E6 was the first open epic since
E1–E5 all shipped.

## Implemented Solutions

Behind an opt-in **`--release`** flag, `run_batch` pushes a `v*` tag as the **final step** of a completed
build — after every ticket merges and after the optional deploy-scaffold — tripping the tag-gated workflow
the DevOps plane already generated. The engine pushes only a *tag*; the user's Actions runs the actual
publish (consistent with E4's "engine never holds cloud creds").

### A — nexus owns the decision + trigger (deployment unchanged)
[run_batch](../../../src/nexus/runner.py) calls a new **`finalize_release`** as its last step, gated on
`cfg.release` **only** — decoupled from `--scaffold-deploy` (a release is "the build finished", not "we
regenerated CI"). nexus → shared `forge` is a free forward import (no lazy seam like E4 needs). The
deployment plane stays a pure config generator.

### B — repo-derived version policy (`compute_next_tag`)
A pure, unit-tested **`compute_next_tag(existing_tags, bump)`** parses the strict `vMAJOR.MINOR.PATCH` tags
(non-conforming — `v1.2`, `latest`, `v1.0.0-rc1` — ignored), takes the numeric max, and bumps it per
**`RELEASE_VERSION_BUMP`** (env, default `minor`); a tagless repo → `v0.1.0`. Deterministic + repo-derived,
so independent builds never collide and a `--resume` re-derives the identical value. The version **number**
is never persisted.

### C — boundary-safe forge tag seam
[forge.py](../../../src/shared/utils/forge.py) gains **`list_remote_tags`** (`git ls-remote --tags origin`,
so it works on a shallow clone) and **`push_tag`** (annotated `git tag -a … -m`, then `git push origin
<tag>`), beside `open_pr`/`merge_pr`. Since `forge` lives in `shared` (cannot import `runner._run_checked`),
it gets a private `_run_git` mirroring `_run_gh` — every argv through `sanitize_for_argv`, a
`GH_NETWORK_TIMEOUT` ceiling, `GIT_TERMINAL_PROMPT=0` (ADR 0018 boundary invariants). `push_tag` is
**best-effort** (logs + returns `False` on a genuine failure; never `sys.exit`s — the build already merged).

### D — idempotency on re-run / `--resume`
`finalize_release` clones `main` fresh into a `NNN_release_tag_…` run dir (`bootstrap_session` onto a
throwaway `chore/release-tag` branch), tags the base-branch tip, pushes. A new
**`BatchState.released_tag`** marker (persisted by `run_batch`'s `finally`, sibling of
`nexus_merged`/`budget_marker`) short-circuits a complete-batch resume; `push_tag` also treats an
already-present remote tag as success. So re-runs / `--resume` neither duplicate nor collide a tag.

### E — opt-in, no LLM spend
`--release` is off by default (a release is a deliberate, outward-facing act). It is consumed only by the
`--auto-execute` batch (or its `--resume`) — inert with a warning elsewhere, like `--scaffold-deploy`. The
phase makes no agent call (no budget threading) and reuses the batch's existing git-push credentials (the
batch already runs `check_environment(require_forge=True)`).

### Docs & Claude operating-context synced to the release
- `CHANGELOG.md` (v0.23.0), `README.md` (the `--release` CLI example + FinOps note), `docs/ARCHITECTURE.md`
  (the human edge, the `--release` sequence-diagram `opt`, the forge component-table row).
- `.claude/rules/*` — `run-layout-and-cli` (`--release` verb + `NNN_release_tag_…` run dir),
  `pipeline-fsm-loops` (the post-batch release terminal phase), `repo-module-map`
  (`finalize_release`/`compute_next_tag`/`push_tag`/`list_remote_tags`), `config-constant-convention`
  (`RELEASE_VERSION_BUMP`), `subprocess-and-external-call-safety` (the forge `_run_git` seam),
  `deploy-scaffolding-and-ci-parity` (release decoupled from scaffold). `analyze-run` SKILL + `CLAUDE.md`
  Development Commands gained the `--release` verb.

## Metrics / Logs Analysis

- **Diff footprint** (working tree vs `v0.22.0` merge `8526487`): **7 files, +384 / −9**. Engine:
  `src/nexus/runner.py` (+107: `compute_next_tag`, `finalize_release`, the trigger, the flag),
  `src/shared/utils/forge.py` (+79: `_run_git`, `list_remote_tags`, `push_tag`),
  `src/shared/core/config.py` (+6: `RELEASE_VERSION_BUMP`), `src/shared/core/models.py` (+1:
  `BatchState.released_tag`). Tests: `test_orchestrator.py` (+137), `test_forge.py` (+58),
  `test_models.py` (+5). (Docs/ADR/rules excluded from the code footprint.)
- **Test suite:** **435** tests green via WSL — **+16** new for E6: `ComputeNextTagTests` (4),
  `FinalizeReleaseTests` (3), forge `PushTagTests` (4) + `ListRemoteTagsTests` (2), the `run_batch`
  release-trigger pair (2), the `--release` parse-args threading (1); plus the `BatchState.released_tag`
  round-trip assertion folded into the existing `BatchStateCheckpointTests`. Bandit clean
  (`bandit -r src/`, no issues).

> Validate locally via WSL:
> `wsl -e bash -lc "cd /mnt/c/code/token-burners-factory && source venv/bin/activate && GEMINI_API_KEY=test-key python3 -m unittest discover -s tests"`
