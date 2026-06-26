# Iteration 25 — Installable `tbf` CLI, factory self-release (E7), and arbiter production-code oracle

> ADR: [0027-installable-cli-and-factory-self-release](../../decisions/0027-installable-cli-and-factory-self-release.md) ·
> CHANGELOG: [v0.26.0](../../../CHANGELOG.md) · Practicum: [PRACTICUM.md](../../../PRACTICUM.md)

## Problem Statement

After E1–E6 the engine drives "idea → merged build → deployable config → tagged release", but the
factory itself remained **developer-only infrastructure**: using it required cloning the repo, standing
up the WSL venv by hand, and keeping that clone in sync. There was no installable package, no release
artefact, and no CI that proved the factory's own release worked.

Three concrete problems compounded this:

- **No distribution path.** Without a `pyproject.toml` and a `tbf` console-script entry point, every
  operator was forced onto a source-clone workflow. The operator role (use `tbf`) and the contributor
  role (mutate `src/`/`prompts/`) were conflated.
- **Factory self-release was manual.** The `--release` flag (E6, ADR 0023) tags *generated*
  applications; the factory engine had no equivalent. Wheels had to be assembled by hand; there was no
  proof that the factory's own CI/CD pattern worked end-to-end.
- **Nexus roles on an unstable model tier.** PO, SA, and TPM were all on `GEMINI_3_5_FLASH`, which was
  experiencing 503 high-demand spikes in production, stalling planning phases without a clear error.

A separate recurring failure class emerged in multi-cycle arbiter runs: when the Developer produced no
net change in a cycle (a no-op edit), the arbiter had no signal showing this and classified QA compile
errors as a `test_bug` — spinning the QA agent on a root cause it could not fix.

## Implemented Solutions

### A — E7: Installable `tbf` CLI (`pyproject.toml` + entry point)

`pyproject.toml` makes the factory a standard Python package (`token-burners-factory`). The
`[project.scripts]` entry `tbf = "src.nexus.runner:_cli_main"` exposes the same async orchestrator
as `main.py`, with `PipelineHalt` mapped to `sys.exit(1)` at the boundary. Package data rules include
`src*` and `prompts**/*.md`, so the installed `tbf` command carries all system prompts and skills.
Operators install with:

```bash
pip install git+https://github.com/<org>/token-burners-factory.git
```

A new guide ([docs/guides/install.md](../../../docs/guides/install.md)) documents the short operator
path (no engine clone needed for the command itself; a clone is still required to build the Docker
sandbox images, which are not distributed).

### B — Factory self-release workflow (`.github/workflows/release-factory.yml`)

A `push: tags: v*` GitHub Actions workflow builds `wheel + sdist` (`python -m build`) and attaches
them to a GitHub Release via `softprops/action-gh-release@v2` with auto-generated release notes. No
extra secrets — `GITHUB_TOKEN` (standard Actions context) holds `contents: write`. The factory now
exercises its own release pattern: the same pipeline it generates for CLI-archetype apps under E6 now
runs for the factory engine itself on every `v*` tag.

### C — Nexus lighter tier: `GEMINI_2_5_FLASH` for PO/SA/TPM (`config.py`)

`PO_MODEL`, `SA_MODEL`, `TPM_MODEL` in `src/shared/core/config.py` switched from `GEMINI_3_5_FLASH` to
`GEMINI_2_5_FLASH` — stabler under demand spikes, lower cost, sufficient for planning roles in the
default PoC configuration. The comment documents bumping to `GEMINI_2_5_PRO` for deeper architectural
reasoning when needed.

### D — Arbiter SHA-256 production-code oracle (`models.py` + `arbiter.py`)

`GlobalPipelineContext` gains `production_code_hash` and `prev_production_code_hash` (SHA-256 of the
full production snapshot, recomputed by `build_production_snapshot` each cycle). The arbiter receives
a boolean `production_code_changed` in its context:

```
production_code_changed = not prev or hash != prev
```

A no-change cycle where QA errors persist is unambiguously a `production_bug`. Removes a systematic
misrouting class where the arbiter sent QA into a spin on errors the Developer had caused but not
touched.

### E — `initial_budget_usd` persistence (`BatchState`)

`BatchState.initial_budget_usd` stores the original `--budget` ceiling from the first invocation.
`--resume` without `--budget` restores the original ceiling; an explicit `--budget` on resume still
overrides it (re-budgeting continues to work). Eliminates the requirement for the operator to re-specify
`--budget` on every `--resume`.

### F — DevOps CI lint tooling by environment (`devops.py` + `environments.py`)

`src/deployment/agents/devops.py` now injects environment-specific CI lint commands (from
`SUPPORTED_ENVIRONMENTS`) into the devops agent context, so generated CI workflows use the correct lint
toolchain for the target runtime (e.g. `ruff check` for Python, `dotnet format --verify-no-changes` for
.NET). `src/deployment/provision/gates.py` gains a `gcloud` command-validity gate (detects malformed
`gcloud` invocations before they reach the CI runner).

### G — Prompt improvements (QA, .NET, archetype)

- **QA pre-write scan** (`prompts/skills/engineering_guide.md`, `prompts/system/qa.md`): mandatory
  domain-trap check before writing tests — prevents wrong-target tests (e.g. a .NET project getting
  Python-style assertions).
- **.NET skill expansions** (`prompts/skills/dotnet_core.md`, `prompts/skills/dotnet_qa.md`): BCL
  exception handling patterns, middleware callback conventions, mandatory JSON serialization attributes,
  and integration test constraints.
- **Fix: missing language variant** (`prompts/skills/engineering_guide.md`): archetype guidance now
  handles the case where the Nexus blueprint omits the language variant field, eliminating a
  `KeyError`/fallback-gap that produced vague diagnostic messages.

## Metrics / Logs Analysis

- **Diff footprint** (`4455ee4` → `7372d01`, src + prompts + pyproject.toml + .github/):
  **25 files, +545 / −45**. Heaviest: `prompts/skills/dotnet_qa.md` (new, +127),
  `src/deployment/provision/gates.py` (+111: gcloud validation, Cloud Run URL extraction),
  `prompts/skills/dotnet_core.md` (+58: BCL/middleware/JSON), `prompts/skills/deploy_gcp.md` (+90:
  Gen2 URL extraction fix), `.github/workflows/release-factory.yml` (new, +41), `pyproject.toml`
  (new, +34).
- **Tests:** `test_devops` +91 (new gcloud + lint-tooling cases), `test_gates` +12,
  `test_qa_agent` +16, `test_prompts` +11, `test_environments` +6. Framework suite green.
- **ADR:** 0027 — installable CLI + factory self-release + arbiter oracle.

> Validate locally via WSL (from the repo root):
> `wsl -e bash -lc "source venv/bin/activate && GEMINI_API_KEY=test-key python3 -m unittest discover -s tests"`
> · security: `wsl -e bash -lc "venv/bin/bandit -r src/"`
