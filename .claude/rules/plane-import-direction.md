---
paths:
  - "src/nexus/runner.py"
  - "src/deployment/provision/scaffold.py"
---

# Plane import direction & cycle-break invariant

The 3-plane split (ADR [0021](../../docs/decisions/0021-physical-three-plane-split.md)) introduces one unavoidable back-edge: the **Deployment** plane's `run_devops_scaffold` reuses the **Nexus** plane's transaction/forge/FinOps/incident SSOTs (`RunConfig`, `bootstrap_session`, `finalize_transaction`, `finalize_pr`, `_abort_with_incident`, `write_finops_report`, `log_finops_summary`). The dependency direction is correct (`deployment → nexus`), but it creates a module-load cycle: `scaffold.py` imports from `runner.py`, and `run_batch` in `runner.py` calls `run_devops_scaffold`.

This rule enforces the **one breaking seam** that makes the cycle safe: a **lazy, call-time import** at the single use site.

## Invariant

`run_batch` (in `src/nexus/runner.py`, the only call site of `run_devops_scaffold`) imports `run_devops_scaffold` **locally inside the function** at call time, NOT at module import time:

```python
if cfg.scaffold_deploy:
    from src.deployment.provision.scaffold import run_devops_scaffold
    await run_devops_scaffold(projects, project, cfg, nexus_run_dir)
```

**Why:** at module import time, `src/nexus/runner.py` is still being loaded; a top-level `from src.deployment.provision.scaffold import run_devops_scaffold` would trigger `scaffold.py`'s imports (including `from src.nexus.runner import …`), creating a cycle that Python's import system blocks with a stale `ModuleNotFoundError` or incomplete module object. A call-time import defers the resolution until *after* `src/nexus/runner` is fully initialized, breaking the cycle. This is the **same pattern** `main()` already uses to import `nexus_runner` — a documented seam, not a workaround.

## How to apply

- **Do NOT** add a top-level `from src.deployment.provision.scaffold import run_devops_scaffold` to `runner.py`. If you need that function elsewhere, use a call-time import there too.
- **Do NOT** move the import out of the `if cfg.scaffold_deploy:` block into a module-level constant or a separate helper.
- If you extract a new SSOT from `runner.py` that `scaffold.py` depends on (e.g. a new helper or model), keep it in `runner.py` (do NOT move it to `shared/`). The lazy import remains sufficient.
- If you add a *new* function to `scaffold.py` that `runner.py` needs to call, wrap that call in a lazy import too (follow the same pattern).

## Cross-link

Related: [[workspace-topology]] (the overall plane boundaries), [[agent-role-registration]] (new roles may live in any plane), [[deploy-scaffolding-and-ci-parity]] (the post-batch phase and its SSOTs).
