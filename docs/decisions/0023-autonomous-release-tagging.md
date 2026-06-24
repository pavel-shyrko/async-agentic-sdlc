# 0023 — Autonomous Release-Tagging (`--release`): closing the loop to a published artifact

## Status

Accepted (depends on [0020](0020-deploy-scaffolding-and-lint-gate.md) the tag-gated deploy/release workflow,
[0019](0019-cyclical-multi-ticket-orchestration.md) `run_batch` batch-completion; extends
[0018](0018-auto-merge-pr-loop-closure.md) the forge seam, [0021](0021-physical-three-plane-split.md) the
three-plane split; implements **E6** in `docs/BACKLOG.md` — the first open epic since E1–E5 all shipped)

## Context

After E1–E5 the autonomy loop runs "idea in → all tickets merged on `main` → (optional) deploy config
merged." The **last** step is still manual. The E4 deploy-scaffold (ADR 0020) generates a release workflow
that is **tag-gated** — the CLI archetype's release job is `if: startsWith(github.ref, 'refs/tags/v')`, and
every archetype's publish step triggers on `tags: ['v*']`. A merge to `main` runs tests but **skips** the
release job (observed in the `write-a-python-cli-utility-…` run: the `release` job rendered "This job was
skipped"). So the engine builds and merges a deployable application, then waits for a human to push a `v*`
tag by hand before anything ships.

No part of the engine pushed tags: `src/shared/utils/forge.py` covered PR open/approve/merge only, and
there was no version policy anywhere in `src/` (a grep for `semver`/`bump`/`git tag` found nothing).

## Decision

Behind an opt-in **`--release`** flag, `run_batch` pushes a `v*` tag as the **final step** of a completed
build — after all tickets merge and after the optional deploy-scaffold — which trips the tag-gated workflow
the DevOps plane already generates. The engine pushes only a *tag*; the user's Actions performs the actual
publish with the user's credentials (consistent with E4's "the engine never holds cloud creds").

### A — nexus owns the decision + trigger; deployment is unchanged
Versioning is a control-plane lifecycle decision. `run_batch` (the terminal orchestrator that knows the
whole build finished) calls a new **`finalize_release`** as its last step, gated on `cfg.release` **only** —
**decoupled from `--scaffold-deploy`** (a release is "the build finished", not "we regenerated CI"). This
needs **no reverse import** (nexus → shared `forge` is a free forward import, unlike E4's lazy seam), and the
deployment plane stays a pure config generator — it does not version or tag.

### B — the version is repo-derived, never invented or persisted
**`compute_next_tag(existing_tags, bump)`** (pure, in `runner.py`) parses the strict `vMAJOR.MINOR.PATCH`
tags read from the target repo (`forge.list_remote_tags` → `git ls-remote --tags origin`, so it works on a
shallow clone that fetched no tags), takes the highest, and bumps it. **`RELEASE_VERSION_BUMP`**
(env-overridable, default `minor`) is the bump policy; a tagless/greenfield repo yields `v0.1.0`. Repo-derived
+ deterministic → independent builds never collide and a `--resume` re-derives the identical value. The
version **number** is never persisted.

### C — the tag-push op is a boundary-safe forge seam
`forge.py` gains **`list_remote_tags`** and **`push_tag`** (an **annotated** tag `git tag -a … -m`, then
`git push origin <tag>`), beside `open_pr`/`merge_pr`. Because `forge` is in `shared` it cannot import
`runner._run_checked`, so it gets a private git runner (`_run_git`) mirroring `_run_gh` — every argv through
`sanitize_for_argv`, a `GH_NETWORK_TIMEOUT` wall-clock ceiling, `GIT_TERMINAL_PROMPT=0` (ADR 0018's boundary
invariants). `push_tag` is **best-effort**: a release runs only after the whole build already merged, so a
push hiccup logs and returns `False` rather than `sys.exit`-ing (unlike `merge_pr`, the loop-closing step).

### D — idempotency on re-run / resume
`finalize_release` clones `main` fresh into a `NNN_release_tag_…` run dir (reusing `bootstrap_session` onto a
throwaway `chore/release-tag` branch), tags the base-branch tip, and pushes. A **`BatchState.released_tag`**
marker (persisted by `run_batch`'s `finally`, sibling of `nexus_merged`/`budget_marker`) short-circuits a
complete-batch `--resume`; `push_tag` additionally treats an already-present remote tag as success. So
re-runs / `--resume` neither duplicate nor collide a tag. The version number stays repo-derived (not
persisted) — only the "release cut" fact is recorded.

### E — opt-in, never default; no LLM spend
A release is a deliberate, outward-facing, low-reversibility act, so `--release` is off by default (normal
runs keep best-practice tag-driven releases). It is consumed only by the `--auto-execute` batch (or its
`--resume`) — inert with a warning elsewhere, exactly like `--scaffold-deploy`. The phase makes no agent
call, so there is no budget threading; it reuses the batch's existing git-push credentials (the batch already
runs `check_environment(require_forge=True)`).

## Consequences

- `--idea "…" --auto-execute --scaffold-deploy --release` ends with a `v*` tag on `main` and the release
  workflow running automatically — zero human touches from idea to published artifact.
- An inert tag is acceptable: if no tag-triggered workflow exists (deploy-scaffold never run), the tag does
  nothing — logged, not an error. The two flags are independent.
- The engine still never holds cloud credentials — it pushes a tag; the user's Actions publishes.
- A new run-dir plane label `release` (`NNN_release_tag_…`) joins `nexus`/`exec`/`devops`.
- Assumes one app/version per repo (monorepo multi-app versioning is out of scope; revisit if needed).

## Touch points

`src/shared/core/config.py` (`RELEASE_VERSION_BUMP`), `src/shared/utils/forge.py` (`_run_git`,
`list_remote_tags`, `push_tag`), `src/shared/core/models.py` (`BatchState.released_tag`),
`src/nexus/runner.py` (`compute_next_tag`, `finalize_release`, the `run_batch` `--release` trigger, the
`--release` flag in `RunConfig`/`parse_args`). Rules: `run-layout-and-cli`, `pipeline-fsm-loops`,
`config-constant-convention`, `subprocess-and-external-call-safety`, `repo-module-map`,
`deploy-scaffolding-and-ci-parity`. Archive:
[iteration_22](../releases/iteration_22/iteration_22_README.md).
