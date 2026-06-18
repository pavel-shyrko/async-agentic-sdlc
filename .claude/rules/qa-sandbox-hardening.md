---
paths:
  - "src/shared/core/docker_adapter.py"
  - "src/executor/nodes/gates.py"
---

# Sandbox least-privilege invariants (PRESERVE THEM)

Every container gate runs **LLM-generated / target-repo** code, so it must stay least-privilege. The
single chokepoint is `run_in_image` in `src/shared/core/docker_adapter.py` (all gates go through
`execute_in_sandbox` → `run_in_image`). It currently enforces, and you MUST keep:

- `--network none` by default; only the dependency-restore / SAST-rule-fetch phase passes
  `network="bridge"` (and `gates.py` runs the test/build phase network-OFF).
- `--cap-drop ALL`, `--memory` / `--pids-limit` / `--cpus` (`_SANDBOX_*` caps), non-root
  `--user $(uid):$(gid)` on POSIX, and a writable `--tmpfs /tmp` (no host scratch bind).
- The repo is mounted at `/workspace`; the persistent package-cache volume is mounted **read-only**
  except during the network-ON restore phase (`cache_writable`), so adversarial tests can't poison it.

**Why:** This is the target-repo-level version of the shared-state hazard ADR 0001/0004 closed for the
engine's own `src/` (mounted `:ro`). Without it a hallucinated or hostile QA test could (1) overwrite
production code to fake a green run, (2) exfiltrate over the network / behave non-deterministically,
(3) DoS the host (fork-bomb / memory), or (4) write root-owned files onto a host bind mount.

**How to apply:** When modifying `docker_adapter.py` or `gates.py` (or adding any container gate), treat
the container as running adversarial code: never widen the mount to read-write production code, never
enable host networking on the execution phase, never drop the resource caps / `--cap-drop ALL` /
non-root user. Related boundary: [workspace-topology](workspace-topology.md). Open hardening:
docs/BACKLOG.md #4 (egress during restore).
