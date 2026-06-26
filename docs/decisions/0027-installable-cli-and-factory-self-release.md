# 0027 — Installable `tbf` CLI and Factory Self-Release Workflow (E7)

## Status

Accepted (extends [0019](0019-cyclical-multi-ticket-orchestration.md) — E3 batch;
[0023](0023-autonomous-release-tagging.md) — E6 generated-app release;
sibling of the runtime registry from [0008](0008-git-anchored-sessions-atomic-commit.md))

## Context

Through E1–E6 the factory drove an idea to a deployed, tagged application — but the factory itself
could only be operated by a developer who had **cloned the engine repo and set up the WSL venv by
hand**. That friction conflated two roles: the engine *contributor* (who needs the source tree, tests,
and the ability to mutate `src/`/`prompts/`) and the pipeline *operator* (who just needs the `tbf`
command and the toolchain dependencies).

Three concrete gaps made the situation worse:

- **No distribution artefact.** There was no `pyproject.toml`, so the factory could not be installed via
  `pip install`. Every operator was forced to work from a source clone and keep it in sync manually.
- **Self-release was manual.** The `--release` flag (E6, ADR 0023) tags *generated* applications; the
  factory itself had no equivalent — a human had to assemble the wheel and upload it. The factory had no
  way to prove its own release workflow.
- **Nexus control-plane roles were on the wrong model tier.** PO/SA/TPM had been left on
  `GEMINI_3_5_FLASH`, a model that was experiencing 503 high-demand spikes in production. The lighter
  `GEMINI_2_5_FLASH` tier is stabler and cheaper for these planning roles.

Separate from distribution, a recurring arbiter-routing failure revealed itself in multi-cycle runs:
when the Developer produced no net change in a cycle (a no-op edit), the arbiter saw only "QA compile
errors" and classified it as a test bug — sending the QA agent into a spin on a problem the Developer
caused. There was no signal in the arbiter's context showing whether production code actually changed.

## Decision

**E7 — Installable CLI + factory self-release:**

1. **`pyproject.toml` with a `tbf` console script.** `[project.scripts] tbf = "src.nexus.runner:_cli_main"`.
   `_cli_main()` is a thin async wrapper around `main()` that maps a bare `PipelineHalt` escape to
   `sys.exit(1)` — identical semantics to `main.py` but callable from an installed entry point. The
   package includes `src*` and `prompts*` (with `**.md` data), so the installed CLI carries the system
   prompts and skills with it.

2. **Factory self-release workflow** (`.github/workflows/release-factory.yml`). A `push: tags: v*` event
   builds `wheel + sdist` with the standard `python -m build` toolchain and attaches them to a GitHub
   Release via `softprops/action-gh-release@v2` with auto-generated release notes. No extra secrets:
   `GITHUB_TOKEN` (provided by Actions) holds `contents: write`. This is the factory exercising its own
   release workflow — the same pattern it generates for CLI-archetype apps under E6.

3. **Nexus model tier downgrade** (`src/shared/core/config.py`). PO/SA/TPM constants changed from
   `GEMINI_3_5_FLASH` to `GEMINI_2_5_FLASH` — stabler under demand spikes, lower cost, still sufficient
   for planning roles that do not need deep architectural reasoning in the default PoC configuration.

**Arbiter production-code oracle:**

4. **SHA-256 cycle snapshot** (`GlobalPipelineContext.production_code_hash` /
   `prev_production_code_hash` in `src/shared/core/models.py`). `build_production_snapshot` recomputes
   the hash each cycle; the previous cycle's hash is preserved in `prev_production_code_hash`. The
   arbiter receives `production_code_changed = (not prev or hash != prev)` — a boolean in its prompt
   context (`src/development/agents/arbiter.py`). A no-change cycle where QA errors persist is therefore
   unambiguously a `production_bug`, not a `test_bug`.

5. **`initial_budget_usd` persistence** (`BatchState.initial_budget_usd` in `src/shared/core/models.py`).
   The original `--budget` ceiling is now stored in `BatchState` on first invocation.
   `--resume` without a `--budget` argument restores the original ceiling; an explicit `--budget` on
   resume still overrides it (re-budgeting continues to work).

## Consequences

**Positive:**
- Operators can install `tbf` with a single `pip install git+…` without touching the source tree.
- The factory self-validates its own distribution: every `v*` tag triggers the same release machinery
  the factory prescribes for CLI-archetype generated apps, proving the pattern works end-to-end.
- Nexus planning is cheaper and more reliable on `GEMINI_2_5_FLASH` (fewer 503 spikes, lower cost per
  planning run).
- The arbiter correctly routes a no-op-developer cycle to `production_bug`, eliminating the QA spin
  class caused by silent Developer no-change cycles.
- Budget intent survives `--resume` without the operator having to re-specify `--budget`.

**Trade-offs / constraints:**
- The `tbf` pip install still requires a source clone to build the sandbox Docker images
  (`scripts/build_sandbox_images.sh`); the images are not distributed. This is documented explicitly in
  `docs/guides/install.md`.
- `GEMINI_2_5_FLASH` for SA/TPM may produce shallower architectural reasoning on complex ideas; the
  comment in `config.py` documents bumping to `GEMINI_2_5_PRO` for deeper work.
- SHA-256 hashing adds a negligible per-cycle cost; the hash is recomputed over the full production
  snapshot, which is bounded by the `MAX_SNAPSHOT_CHARS` cap already in place.
