# Snapshot 001 — Technical Report

* **Timestamp**: May 25, 2026, 18:00 CEST
* **Target Requirement**: Implement `factorial(n)` in `math_lib.py` with `ValueError` for negative inputs.
* **Final Status**: ✅ PASSED (Resolved in 2 orchestration cycles)

---

## 1. Execution Flow & Internal Iterations

### Cycle 1 (Internal Failure)
* **Architect (`gemini-3.5-flash`)**: Locked JSON schema and signature contracts.
* **QA-Generator (`gemini-3.5-flash`)**: Authored physical `test_math_lib.py` containing type edge-cases.
* **Developer (`claude-3.5-sonnet`)**: Generated initial `math_lib.py` with standard iterative calculation.
* **Validation Fork**:
  * `SAST-SECURITY` (Bandit): Passed.
  * `DOCKER-QA` (Unittest): **Failed**. Trapped a type regression where boolean inputs (`True`/`False`) were accepted as valid integers.

### Cycle 2 (Internal Self-Healing)
* **Orchestrator**: Captured the unit test `AssertionError` trace and appended it back to the Developer's context window.
* **Developer (`claude-3.5-sonnet`)**: Synthesized the failure log, diagnosed that `bool` is an implicit subclass of `int` in Python, and injected an explicit type guard (`isinstance(n, bool)`).
* **Validation Fork**: Both functional tests and security scans returned exit code 0. Pipeline execution halted successfully.

---

## 2. Discovered Edge Cases

The dedicated QA Node effectively prevented a critical runtime silent failure by enforcing the following constraint:

```python
def test_factorial_invalid_types_raise_type_error(self):
    invalid_inputs = [5.5, "5", [5], True, False]
    for val in invalid_inputs:
        with self.assertRaises(TypeError):
            factorial(val)
```

Without the strict type checking added in Cycle 2, booleans bypassed the logic and produced mathematically invalid outputs (`factorial(True) -> 1`).
