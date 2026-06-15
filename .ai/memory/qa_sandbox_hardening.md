---
name: qa-sandbox-hardening
description: QA Docker gate runs LLM-generated tests under-isolated (whole-repo :rw, root, host net, no limits) — least-privilege when touching gates.py
metadata:
  type: constraint
---

# CONSTRAINT: QA RUNTIME GATE IS UNDER-HARDENED

`run_qa_unit_tests` in `src/nodes/gates.py` executes **LLM-generated** test code with weak isolation:
`docker run --rm -v {repo_root}:/workspace/repo:rw python:3.11-slim …` — the **entire clone is mounted
read-write**, the container runs as **root**, **host networking is enabled**, and there are **no
resource limits** (`--memory` / `--pids-limit` / `--cpus`) and no `--read-only` / `--cap-drop`.

**Why:** This re-opens, at the target-repo level, the shared-state hazard ADR 0001/0004 closed for the
engine's own `src/` (mounted `:ro`). A hallucinated or hostile QA test can (1) **overwrite production
code to fake a green run**, (2) **exfiltrate over the network** / behave non-deterministically,
(3) **DoS the host** (fork-bomb / memory), and (4) write root-owned files onto the host bind mount.

**How to apply:** When modifying `gates.py` (or adding any container gate), enforce least privilege:
`--network none`, mount production code read-only (give only `tests-dir` `:rw`, or a tmpfs work area),
`--memory` / `--pids-limit` / `--cpus`, a non-root `--user`, and `--cap-drop ALL`. Treat the QA
container as running adversarial code. Related boundary: [[workspace-topology]].
