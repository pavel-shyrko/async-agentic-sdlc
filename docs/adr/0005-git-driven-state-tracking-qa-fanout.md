# Snapshot 005 — Git-Driven State Tracking & QA Concurrency

## Problem Statement

Iteration 004 exposed two hard scaling limits that prevented the pipeline from processing brownfield or multi-file tasks:

### 1. Glob-Based State Tracking Fragility

The Developer and QA nodes collected code snapshots by glob-scanning the `artifacts/` directory. This approach had three failure modes:

- **Binary pollution**: `__pycache__/` directories and `.pyc` files are created automatically by Python runtimes. On large tasks, these non-text files triggered `UnicodeDecodeError` when the pipeline tried to read them into LLM context. The orchestrator had no `.gitignore`-aware filtering.
- **Context bleed**: A glob over the artifacts directory includes all previously generated files from prior retries, not only the delta introduced by the current cycle. The Reviewer's context window received stale code artifacts from previous failed attempts.
- **No scope boundary**: The pipeline could not distinguish between "files the developer was supposed to change" and "files that happened to exist in the sandbox."

### 2. QA Monolithic Output & Max Token Ceiling

The QA node produced a single `test_modules_modules.py` file covering every function in the contract. On multi-file contracts (e.g., a 4-module geometry package), the combined test suite exceeded the LLM's `max_output_tokens` limit, producing truncated — and therefore syntactically broken — test files.

---

## Implemented Solutions

### Git Anchor Pattern (`src/utils/git_helpers.py`)

A new `git_helpers` module introduces two primitives:

```
init_sandbox_git(repo_path, base_branch)
  └── git init → commit .gitignore → branch -m <base_branch> → checkout -b agent-workspace

get_pipeline_snapshot_files(repo_path, base_branch)
  └── git add . → git diff <base_branch> --name-only → returns list[str]
```

**How it works:**

1. On first call, the sandbox directory is initialized as a Git repository. The initial commit contains only the `.gitignore` (protecting against binary noise from `__pycache__`, `.pyc`, `.pyo` files). This commit becomes the **base anchor** on the branch named after `base_branch` (default: `main`).
2. The agent branch (`agent-workspace`) is created off the anchor. All agent writes land here.
3. To capture the delta, `git diff <base_branch> --name-only` reports exactly the files that changed since the anchor — no more, no less.
4. The snapshot passed to the Reviewer is reconstructed from this file list, with each file's content wrapped in `=== FILE: <path> ===` delimiters for structured cross-file review.

This completely eliminates UnicodeDecodeError (`.gitignore` filters binary files before they reach the diff) and context bleed (only uncommitted delta is captured).

### QA Fan-Out Concurrency

The QA node was redesigned from a single monolithic call to a **fan-out** model using `asyncio.gather`:

```python
results = await asyncio.gather(*[_generate(m) for m in target_modules])
```

- One LLM call per production module — each producing an isolated `test_<module_dot_path>.py` file.
- File naming uses the full dotted module path as a slug (`test_src_geometry_shapes.py`), preventing collisions across packages.
- Facade modules (`__init__.py`) are filtered out: they hold no own logic, and generating tests for them produces duplicate coverage of every re-exported member.
- The `unittest discover` gate (replacing the single-module invocation) automatically collects all `test_*.py` files in the tests directory.

### API Retry Centralization (`src/utils/api_retry.py`)

All per-agent try/except retry boilerplate was extracted into a single `@with_api_retry` async decorator. Handles 429 quota errors (immediate exit) and general transient failures (exponential backoff, 2^attempt seconds).

### Reviewer Catch-22 Resolution

The Reviewer's system prompt was extended with an explicit authorization clause:

> *"The Developer is AUTHORIZED to create new helper/utility files (e.g., validators.py) to enforce DRY and SOLID principles. Do not reject code for adding auxiliary files."*

Without this, the Reviewer rejected the geometry package iteration because the Developer (following SOLID) extracted `validate_positive_number` into `base.py` — a file not listed in the original contract. This deadlocked the FSM: the Architect could not add utility files to the contract without a new cycle, and the Reviewer kept rejecting the output.

### Security Scan Recursive Mode

Bandit SAST was switched from per-file to recursive (`-r`) directory scanning:

```python
cmd = [sys.executable, "-m", "bandit", "-q", "-r"] + files
```

Previously, the scan targeted only the files listed in the architecture contract. Utility files created by the Developer (validators, helpers) were silently excluded. Recursive mode ensures the full generated codebase is analyzed.

### CLI Argument Parser

The orchestrator is now a proper CLI tool accepting task descriptions inline or from a file:

```bash
python3 orchestrator.py "Implement is_prime(num: int) -> bool"
python3 orchestrator.py -f tickets/003_multi_file_geometry.md --base-branch main
```

The `--base-branch` flag is forwarded into `GlobalPipelineContext` and propagated to both the Developer and QA Git Anchor initialization calls.

---

## Verified Artifacts

Three independent pipeline runs were executed against progressively complex tickets:

| Artifact | Task | Files Generated | Test Files | Result |
| :--- | :--- | :--- | :--- | :--- |
| `artifacts 001/` | `is_prime(num)` utility | 1 | 1 | ✅ Pass (1 cycle) |
| `artifacts 002/` | Fibonacci w/ memoization | 1 | 1 | ✅ Pass (1 cycle) |
| `artifacts 003/` | Geometry package (4 modules) | 4 | 3 (facade filtered) | ✅ Pass (1 cycle) |

The geometry run validated the complete fan-out path: 3 concurrent LLM calls, 3 isolated test files, `unittest discover` gate, recursive SAST scan across the 4-module tree.

---

## Token Utilization Metrics (Artifacts 003 — Geometry Package)

* **Architect Agent (`gemini-2.5-flash`)**: Input: 145 | Output: 877 | Total: 2,402
* **QA Agent (`gemini-2.5-flash`) — 3 concurrent calls**:
  * Module `base.py`: Input: 494 | Output: 663 | Total: 3,208
  * Module `shapes.py`: Input: 494 | Output: 1,835 | Total: 7,644
  * Module `volume.py`: Input: 494 | Output: 3,330 | Total: 6,214
* **Developer Agent (`Claude 4.6 Sonnet`)**: Monitored out-of-band via `npx ccusage`.
* **Reviewer Agent (`gemini-2.5-pro`)**: Input/Output logged per cycle in `sdlc_audit.log`.

---

## Architectural Status

The pipeline is now brownfield-capable. It can process multi-file packages with cross-module dependencies, correctly scoped state tracking via Git Anchor, and concurrent test generation that does not hit output token ceilings. The FSM deadlock between Architect contracts and Developer utility file creation has been resolved.
