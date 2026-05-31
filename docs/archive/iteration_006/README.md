# Snapshot 006 — FSM State Serialization & Resume Mechanism

## Problem Statement

Iterations 001–005 produced a hermetic, self-healing pipeline, but its runtime state was **fully ephemeral**. Every executed agent call, every approved gate, every restored test snapshot lived only inside the orchestrator process. Three concrete failure modes accumulated:

### 1. Token Loss on Crash

A typical multi-file run consumes thousands of input/output tokens across Architect → Developer → QA → Reviewer. A single OOM event, a Gemini 5xx transient, a Docker daemon hiccup, or an accidental `Ctrl+C` invalidated the entire investment. The next run started from cycle 1, re-paying for Architect contract design and QA test fan-out that had already succeeded.

### 2. No Macro-Orchestrator Integration

The pipeline could not be wrapped by GitLab CI, n8n, or any external scheduler that expects job idempotency and restart-from-failure semantics. Without serialized state, a CI retry policy was equivalent to a cold start.

### 3. Circuit Breaker Amnesia

The retry counter (`current_attempt`) lived only in a local Python loop variable. After a process restart the Circuit Breaker budget silently reset to zero, defeating the safety guarantee that pathological prompts cannot loop indefinitely.

---

## Implemented Solutions

### FSM Serialization API (`src/core/models.py`)

`GlobalPipelineContext` received two synchronous methods:

```python
def save_checkpoint(self, path: Path) -> None
def load_checkpoint(cls, path: Path) -> "GlobalPipelineContext"
```

`save_checkpoint` creates parent directories as needed and writes the full context (contract, snapshots, review report, attempt counter, workspace paths) via `model_dump_json(indent=2)`. `load_checkpoint` round-trips through `model_validate_json`, restoring all `Path` fields to native `WindowsPath`/`PosixPath` instances.

A **single rolling file** at `artifacts/reports/checkpoint.json` is used — overwritten after every critical node. This avoids I/O bloat and snapshot directory churn while still providing a consistent "last known good" state.

Checkpoint write points:
1. After Architect contract approval.
2. After QA test generation / approval.
3. At the end of every self-heal cycle (before the next attempt increments).

### Resume CLI & Skip Logic (`orchestrator.py`)

New CLI flag:

```bash
python3 orchestrator.py --resume artifacts/reports/checkpoint.json
```

On startup the orchestrator loads the checkpoint inside `try/except`. A corrupt or unreadable file produces a clear log line and `sys.exit(1)` — the run is never silently degraded.

After successful load, the FSM **bypasses** any node whose output already exists in the restored context:

| Restored Field | Skipped Node | Routing Behavior |
| :--- | :--- | :--- |
| `ctx.contract` is set | Architect | Skip — log message, route to Developer |
| `ctx.test_code_snapshot` is set AND `review_report.test_integrity_approved == True` | QA generation | Skip — log message, route to Functional Test gate |
| `review_report.test_integrity_approved == False` | (none — fall through) | Route to QA **regeneration** branch |

The regeneration branch is critical: a checkpoint taken after the Reviewer rejected the test suite must, on resume, route directly into QA test regeneration — not into a blind re-use of the rejected tests. This is derived purely from `ctx.review_report` so no ephemeral "first_cycle" flag is needed.

### Circuit Breaker Persistence

`current_attempt: int = 1` is now a first-class Pydantic field. The orchestration loop runs `range(ctx.current_attempt, max_retries + 1)` and persists `ctx.current_attempt = attempt + 1` before each checkpoint write. The retry budget survives process restarts exactly as the contract and snapshots do.

For deliberate fresh restarts (e.g., after a prompt fix), a companion flag was added:

```bash
python3 orchestrator.py --resume artifacts/reports/checkpoint.json --reset-attempts
```

This restores the full retry budget while preserving the contract and prior snapshots — the canonical workflow when iterating on agent prompts mid-pipeline.

### Agent Scope Isolation — Confirmation Bias Removal

Two prompt-level hardening passes were applied to enforce strict separation of concerns at the LLM boundary:

* **Developer (`src/agents/developer.py`)** — explicit prohibition added: `CRITICAL: DO NOT write any unit tests or test files. The QA node handles testing. Write ONLY production code.` Previously the Claude CLI agent would helpfully append tests next to production modules, polluting the `production_code_snapshot` and creating a confirmation-bias loop where the Developer effectively graded its own work.
* **QA (`src/agents/qa.py`)** — dual-channel rule (system prompt + shared rules) forbids any form of exception-string inspection: `assertIn` / `assertEqual` / `assertRegex` / `assertRaisesRegex` over an exception, `.args` access, `str(exc)` matching. Brittle string-coupled tests are the most common false-positive source in autonomous QA.

### Architectural Integrity — Dependency Injection Mandate

The Architect system prompt (`src/agents/architect.py`) now contains:

> *CRITICAL ARCHITECTURE RULES:*
> *1. Enforce strict Dependency Injection (DI) for class composition. Classes must receive their dependencies via the constructor (e.g., `def __init__(self, base_shape: Shape, ...)`). They are STRICTLY FORBIDDEN from instantiating their dependencies internally.*

This blocks the Tight Coupling antipattern at the contract level — the source of an earlier defect where a `Cylinder` hardcoded `Circle()` inside its body, bypassing both Reviewer scrutiny and test substitutability.

---

## Verification

The framework test suite (`tests/framework/`) was extended with 45 unit tests covering:

* Checkpoint round-trip (fields, `Path` types, malformed JSON rejection).
* `parse_args` with `--resume` and `--reset-attempts` flag combinations.
* Main loop skip behavior for Architect and QA nodes.
* Self-heal recovery from a persisted rejected-test state.
* Circuit Breaker budget restoration via `--reset-attempts`.

Full suite: **45 / 45 OK**.

---

## Architectural Status

The pipeline is now **transactionally restartable**. Any failure — process crash, API outage, Docker restart, deliberate `Ctrl+C` — leaves a recoverable checkpoint. Macro-orchestrators (GitLab CI, n8n, Airflow) can wrap the pipeline with standard "retry on failure" semantics without duplicating token spend. Agent scope is enforced hermetically at the prompt boundary, and architectural quality (DI) is mandated at the contract layer rather than detected post-hoc by the Reviewer.
