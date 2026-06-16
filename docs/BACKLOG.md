# Backlog

Deferred fixes surfaced by the analysis of `run_9305be1f473f4337830b6d8bad0ddc29` (Go `json2csv`
pipeline that hit `CIRCUIT BREAKER OPEN` after 3 cycles). Item #1 (Developer CLI `cwd` sandbox
isolation) was fixed separately; the items below remain open.

## 1. Developer agent must never touch test files (`*_test.go` cascade)
**Symptom:** with Go colocation, QA writes `*_test.go` into the Developer's own package, and the
Developer edited, commented, then deleted them.
**Evidence (run audit log):**
- L206 — *"test files are missing `package` declarations … Applying the Dependency Fix Rule to add the declarations"* → dev edits tests.
- L218, L320–321, L331–336 — `enforce_documentation_guardrail` flags the QA tests as the dev's "undocumented new files" and forces architectural-justification comments into them.
- L623 — Ghost-File-GC then makes the dev delete both test files.
- L269 — contradicts the role_constraint *"You cannot edit tests."*
**Fix direction:**
- Exclude `*_test.go` (and language test patterns) from `build_production_snapshot`,
  `enforce_documentation_guardrail`, and Ghost-File-GC.
- Resolve the guard contradiction: the `CRITICAL DEPENDENCY FIX RULE` must NOT authorize editing test
  files; tests must not block the Developer's compile step.

## 2. Gate execution environment is broken (compile/test/SAST must actually run) — ✅ RESOLVED
**Was:** stock images lacked the gate tools (no `pytest`/`bandit` in `python:3.12-slim`, no `gosec`
in `golang:1.23-alpine`) and the non-root run hit `mkdir /.cache: permission denied` (L797/L798).
**Fixed by:** per-env custom sandbox images (`docker/*.Dockerfile` + `scripts/build_sandbox_images.sh`)
carrying the test runner + writable `HOME`/cache; a generic **Semgrep** SAST image for ALL languages
(`SAST_IMAGE`/`SAST_CMD`); `docker_adapter.run_in_image` injecting `sandbox_env` + resource limits +
`--cap-drop ALL` + tmpfs; and a network-ON dependency-restore phase (`setup_cmd`) before the
network-OFF test phase in `gates.py`.

## 4. Restrict egress during the dependency-restore / SAST phases
**Why:** the restore phase (`setup_cmd`) and Semgrep rule-fetch run with `--network bridge`. Package
managers execute install hooks (e.g. npm `postinstall`) → an exfiltration surface for LLM-authored
code. Test execution stays `--network none`, so the window is narrow but real.
**Fix direction:** route restore through an egress-restricted proxy (allowlist package registries),
or vendor dependencies offline, so no phase has unrestricted network.

## 3. TASK-01 mandated baseline artifacts don't survive the run
**Symptom:** the contract included `.gitignore` and `LICENSE`, but the final repo tree had only
`README.md`, `go.mod`, `src/cmd/json2csv/main.go`, `src/internal/converter/converter.go`.
**Fix direction:** investigate why mandated TASK-01 files (`.gitignore`, `LICENSE`) are lost across
the develop/snapshot/retry cycles and ensure baseline artifacts persist to the final commit.
