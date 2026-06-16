# Backlog

Deferred fixes surfaced by the analysis of `run_9305be1f473f4337830b6d8bad0ddc29` (Go `json2csv`
pipeline that hit `CIRCUIT BREAKER OPEN` after 3 cycles). Item #1 (Developer CLI `cwd` sandbox
isolation) was fixed separately; the items below remain open.

## 1. Developer agent must never touch test files (`*_test.go` cascade) — ✅ RESOLVED
**Was:** with Go colocation QA writes `*_test.go` into the Developer's package; the Python-only test
filter let them leak into `production_code_snapshot`, so the doc guardrail flagged them and the dev
commented/deleted them.
**Fixed by:** env-aware `is_test_file()` SSOT used by `build_production_snapshot` (colocated tests
excluded for every language); a hard "TEST FILES ARE OFF-LIMITS" gate in `developer.md` (dependency-fix
rule scoped to production); SA/TPM prompts demarcate production vs test.

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

---
New items from `run_bb7a268aad844656910343c081e44f3e` (Go `json2csv`, `CIRCUIT BREAKER OPEN` after 3
cycles — both gates red EVERY cycle). The surfaced line (`go: no module dependencies to download`) was
a red herring; the real causes are below.

## 5. [P0] QA emits SYNTACTICALLY INVALID Go test files (no `package` clause) — actual failure cause
**Symptom:** every cycle, both the compile gate and the functional gate failed with:
`internal/converter/processor_test.go:1:1: expected 'package', found 'import'` (×3 files). The QA
test files start with `import (...)` and have NO `package <name>` first line — invalid Go, won't
parse. QA regenerated the same broken shape each cycle → 3 cycles → breaker.
**Root cause:** the non-Python whole-file assembly (`_assemble_suite_text`) concatenates
`new_imports` + `new_test_code` verbatim; the model emitted imports with no leading `package` clause,
and nothing enforces/repairs it. `go_qa.md` doesn't hard-require a `package` declaration as line 1.
**Fix direction (why it matters: this is THE blocker):**
- `go_qa.md`: mandate that every Go test file's FIRST line is `package <pkg>` (same package as the
  unit under test), before any import.
- `_assemble_suite_text` (or a per-language post-assembly check): for Go/.NET/Node, validate the
  emitted file has the required leading declaration (`package`/namespace); if missing, fail QA
  generation loudly (route to QA channel) instead of writing an un-parseable file the gates choke on.
- Consider a cheap structural lint on generated test files per language before they hit the gate.

## 6. [P1] Semgrep `--config auto` fails behind a corporate TLS proxy AND needs network
**Symptom:** SAST gate fails every cycle: `HTTPSConnectionPool(host='semgrep.dev', port=443) … SSL:
CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate`. `--config auto` fetches rulesets
from `semgrep.dev`; the corporate MITM proxy presents a cert the Semgrep container's CA store doesn't
trust → SAST can NEVER pass here. (Same corporate-CA class as docs/docker-on-windows.md §cert.)
**Fix direction:**
- Bundle a ruleset INTO a custom Semgrep image and run `--config <local-dir>` with `--network none`
  (offline) — removes both the SSL dependency AND the network-on SAST window (folds into #4).
- OR inject the corporate CA bundle into the Semgrep image / `REQUESTS_CA_BUNDLE`, and/or
  `--metrics=off` to avoid the telemetry call.

## 7. [P1] Go compile gate parses colocated `_test.go` → leaks test errors to the Developer (who can't fix tests)
**Symptom:** `go build ./...` failed on the malformed `*_test.go` (`expected 'package'`), so the
compile gate (option B) rerouted the **Developer** with TEST-file parse errors — but the Developer is
hard-forbidden from touching tests, so the reroutes are unfixable and just burn out before
fall-through.
**Root cause:** Go's package loader parses ALL `.go` files (incl. `_test.go`) when building a package,
so `go build ./...` is NOT actually test-isolated — contradicting the "build never touches tests"
assumption behind the compile gate.
**Fix direction:** make the compile gate test-agnostic — e.g. build only non-test files / a synthetic
build that excludes `_test.go`, or classify "test-file syntax" failures as a QA-channel issue (route
to QA, not the Developer). At minimum, a build failure caused solely by `*_test.go` must NOT reroute
the Developer.

## 8. [P2] Misleading gate failure surface buries the real error
**Symptom:** `[GATE][FUNCTIONAL-TESTS] Failure raw output:` showed only
`go: no module dependencies to download` — an INFORMATIONAL stderr line from `go mod download`
(exit 0, stdlib-only project), while the actual compile errors were elsewhere in the stream.
**Fix direction:** drop restore-phase stderr (and known-benign informational lines) from the
functional-failure context shown to the operator/Reviewer; surface the build/test phase's real
diagnostics. Keeps `_extract_failure_context` pointed at the true root cause.
