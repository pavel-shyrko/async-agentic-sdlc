---
paths:
  - "src/shared/core/runs.py"
  - "src/executor/runner.py"
---

# Run layout & CLI

**Layout** (SSOT: `src/shared/core/runs.py` `Projects` + `allocate_run_dir`):
```
runs/<project>/                               # project = idea slug (Nexus) or ticket slug (direct exec)
  project.json                                # umbrella manifest: {slug, idea, repo, base_branch, created_at}
  <NNN>_nexus_plan_<YYYYMMDD-HHMMSS>_<uid6>/   # planning run → artifacts/{epic,blueprint,TASK-*}.md
  <NNN>_exec_<ticket>_<ts>_<uid6>/            # executor run → repo/ (clone on feat/ticket-<ticket>)
```
Every run dir also has `logs/sdlc_audit.log` + `reports/` (`checkpoint.json`, `finops_report.json`,
`incident_report.json` on halt). `NNN` = max existing + 1 within the project; `uid6` guarantees no
overwrite. `RUNS_BASE` (`PIPELINE_RUNS_BASE`, default `runs`) is the root.

**CLI verbs** (`parse_args` / `main` in `src/executor/runner.py`):
- `--idea "..." [--repo R]` → NEW project, runs Nexus planning (`001_nexus_plan`); `--repo` captured into project.json.
- `--run <project> -f <ticket>` → executor for that ticket; repo + base branch from project.json; ticket body resolved from the latest nexus run's `artifacts/<ticket>.md`.
- `--resume <project> <NNN>` → resume run #NNN; `--resume <project>` (no number) → continue the latest Nexus run; `--resume <path.json>` → legacy explicit checkpoint.
- Legacy direct: `--repo --ticket [-f file] [desc]` → grouped under a ticket-slug project.

**Resume routing** (no dir-name parsing): `_run_dir_from_checkpoint` = checkpoint's grandparent;
`_checkpoint_kind` peeks `kind` in the JSON — `"nexus"` → control plane (`NexusState`), else executor
(`GlobalPipelineContext`). Old `runs/run_<uuid>/` checkpoints still resume via the path form.
Related: [workspace-topology](workspace-topology.md), [debugging-protocol](debugging-protocol.md).
