import os
import re

from src.shared.core.observability import log
from src.shared.core.environments import SUPPORTED_ENVIRONMENTS, SAST_IMAGE, SAST_CMD, is_test_file
from src.shared.core.docker_adapter import execute_in_sandbox, run_in_image

# Compiler/diagnostic lines reference a source file as `path/to/file.ext:line[:col]:`.
_FILE_REF_RE = re.compile(r"^\s*([\w./\\-]+\.(?:go|cs|ts|tsx|js|jsx|py)):\d+")


def build_failure_is_test_only(environment_id: str, log_lines: list[str]) -> bool:
    """True iff the build output references ≥1 source file AND every referenced file is a TEST file.

    The Go compile gate's `go build ./...` parses colocated `*_test.go` during package loading, so a
    broken test file can fail the build — but those are QA-owned and the Developer must NOT be rerouted
    for them. Returns False when no file references parse (never mask a real production failure)."""
    referenced = [m.group(1) for ln in log_lines if (m := _FILE_REF_RE.match(ln))]
    if not referenced:
        return False
    return all(is_test_file(environment_id, p) for p in referenced)


# Signatures of an ENVIRONMENTAL build/restore failure — the sandbox could not reach the package
# feed (NuGet/npm/Go/PyPI) or DNS/proxy dropped the connection. These are NOT code defects: the
# Developer cannot fix the network, so rerouting it just wastes budget and corrupts the contract
# (it drops mandated dependencies to "compile offline"). Matched case-insensitively. Kept to strong
# network/restore signatures only, so a real compiler error is never misread as environmental.
_ENV_BUILD_FAILURE_MARKERS = (
    "nu1301",                              # NuGet: unable to load the service index for source
    "unable to load the service index",
    "resource temporarily unavailable",    # EAGAIN — socket blocked (antivirus/proxy under burst)
    "temporary failure in name resolution",
    "could not resolve host",
    "name or service not known",
    "network is unreachable",
    "connection timed out",
    "connection refused",
    "could not connect to",
    "failed to connect to",
    "tls handshake timeout",
    "proxyerror",
    "etimedout", "enotfound", "eai_again", "econnreset",   # npm/node network errno
    "dial tcp",                            # go module fetch
    "🚨 dependency restore failed",         # our own restore-phase failure banner (gates setup_cmd)
)


def build_failure_is_environmental(environment_id: str, log_lines: list[str]) -> bool:
    """True iff the build/restore output bears a network/feed-unreachable signature (and is therefore
    NOT a code defect). Used by the runner to fail FAST with a clear environment incident instead of
    rerouting the Developer to "fix" an unreachable package feed. Conservative: requires an explicit
    network/restore marker, so genuine compiler errors fall through to the normal compile-gate reroute."""
    blob = "\n".join(log_lines).lower()
    return any(marker in blob for marker in _ENV_BUILD_FAILURE_MARKERS)


def _has_test_files(environment_id: str, repo_root: str) -> bool:
    """True if the workspace holds ≥1 test file for the target stack (language-aware, via the
    is_test_file SSOT). Runner-agnostic empty-suite detection: rather than special-casing each
    runner's "no tests" exit code (pytest 5, jest 1, go/dotnet 0), ask whether any test file is
    even present. None present → the functional gate is a no-op pass (e.g. a ticket with no testable
    source, like a thin scaffold/entrypoint). The Reviewer's test_integrity gate remains the backstop
    when tests WERE expected."""
    for root, dirs, files in os.walk(repo_root):
        if ".git" in dirs:
            dirs.remove(".git")  # never descend into git internals
        if any(is_test_file(environment_id, name) for name in files):
            return True
    return False

# ==========================================
# PARALLEL RUNTIME GATES (Sandboxed execution)
# ==========================================
# Commands come from the static SUPPORTED_ENVIRONMENTS registry and run inside the canonical,
# hardened sandbox image for the ticket's environment_id — no host tooling, no hardcoded runtime.
async def run_qa_unit_tests(environment_id: str, repo_root: str) -> tuple[bool, list[str]]:
    """Functional-test gate. Dependency restore runs FIRST with network ON (project deps can't be
    baked into the image); the tests themselves then run with network OFF (isolated execution)."""
    spec = SUPPORTED_ENVIRONMENTS[environment_id]
    log_lines: list[str] = []

    # Empty-suite short-circuit: with no test files there is nothing to execute, so the gate is a
    # no-op pass — skipping the dependency restore too. This avoids a fictitious failure from a
    # runner that exits non-zero on "no tests collected" (pytest 5, jest 1) for a ticket with no
    # testable source (e.g. a thin scaffold/entrypoint).
    if not _has_test_files(environment_id, repo_root):
        log.debug(f"No test files present for [{environment_id}] — functional-test gate is a no-op pass.")
        return True, ["No test files present — functional-test gate skipped (empty suite is a no-op pass)."]

    setup_cmd = spec.get("setup_cmd")
    if setup_cmd:
        log.debug(f"Restoring dependencies [{environment_id}] (network ON): {setup_cmd}")
        # cache_writable: the restore phase is the ONLY writer of the persistent package cache volume;
        # build/test/compile mount it read-only so adversarial test code cannot poison it.
        rc, out, err = await execute_in_sandbox(environment_id, setup_cmd, repo_root, network="bridge", cache_writable=True)
        restore_out = (out + "\n" + err).strip()
        if rc != 0:
            log.debug(f"Dependency restore failed with exit code: {rc}")
            return False, ["🚨 Dependency restore failed:"] + restore_out.splitlines()
        # Restore succeeded: its output (e.g. "go: no module dependencies to download") is benign
        # noise — keep it OUT of the failure context so the test phase's real errors aren't buried.
        if restore_out:
            log.debug(f"Dependency restore output: {restore_out}")

    test_cmd = spec["test_cmd"]
    log.debug(f"Executing QA runtime gate [{environment_id}] (network OFF): {test_cmd}")
    returncode, stdout, stderr = await execute_in_sandbox(environment_id, test_cmd, repo_root, network="none")
    log_lines = (stdout + "\n" + stderr).strip().splitlines()
    log.debug(f"QA Runtime Gate completed with exit code: {returncode}")
    return returncode == 0, log_lines


async def run_build_gate(environment_id: str, repo_root: str) -> tuple[bool, list[str]]:
    """Compile gate run right after the Developer: restore deps (network ON) then compile/typecheck
    (network OFF). BUILD/RUN ONLY — `build_cmd` never executes tests, so the Developer stays fenced
    off from the QA-owned test files. Returns ``(ok, log_lines)``; a no-op pass when the env declares
    no ``build_cmd``."""
    spec = SUPPORTED_ENVIRONMENTS[environment_id]
    build_cmd = spec.get("build_cmd")
    if not build_cmd:
        return True, []

    setup_cmd = spec.get("setup_cmd")
    if setup_cmd:
        log.debug(f"Restoring dependencies for build [{environment_id}] (network ON): {setup_cmd}")
        # cache_writable: the restore phase is the ONLY writer of the persistent package cache volume;
        # build/test/compile mount it read-only so adversarial test code cannot poison it.
        rc, out, err = await execute_in_sandbox(environment_id, setup_cmd, repo_root, network="bridge", cache_writable=True)
        restore_out = (out + "\n" + err).strip()
        if rc != 0:
            log.debug(f"Dependency restore (build) failed with exit code: {rc}")
            return False, ["🚨 Dependency restore failed:"] + restore_out.splitlines()
        # Restore succeeded: benign output stays OUT of the failure context (the build errors are
        # what the Developer must act on), debug-logged only.
        if restore_out:
            log.debug(f"Dependency restore output: {restore_out}")

    log.debug(f"Executing build gate [{environment_id}] (network OFF): {build_cmd}")
    returncode, stdout, stderr = await execute_in_sandbox(environment_id, build_cmd, repo_root, network="none")
    log_lines = (stdout + "\n" + stderr).strip().splitlines()
    log.debug(f"Build gate completed with exit code: {returncode}")
    return returncode == 0, log_lines


async def run_test_compile_gate(environment_id: str, repo_root: str) -> tuple[bool, list[str]]:
    """Pre-Reviewer COMPILE-ONLY gate over the QA-generated tests: restore deps (network ON) then run
    the env's `test_compile_cmd` (network OFF), which builds the test code but runs NO test bodies.
    Surfaces test compile errors (unused imports, undefined symbols) deterministically so the runner
    can fast-fail-reroute them to the QA channel without spending the Reviewer. Compile-only (not
    `go test`) on purpose: a real assertion failure references the test file too, so running tests here
    would misroute production bugs to QA. Returns ``(ok, log_lines)``; a no-op pass when the env has no
    `test_compile_cmd` or no test files are present."""
    spec = SUPPORTED_ENVIRONMENTS[environment_id]
    test_compile_cmd = spec.get("test_compile_cmd")
    if not test_compile_cmd:
        return True, []
    if not _has_test_files(environment_id, repo_root):
        log.debug(f"No test files present for [{environment_id}] — QA test-compile gate is a no-op pass.")
        return True, []

    setup_cmd = spec.get("setup_cmd")
    if setup_cmd:
        log.debug(f"Restoring dependencies for test-compile [{environment_id}] (network ON): {setup_cmd}")
        # cache_writable: the restore phase is the ONLY writer of the persistent package cache volume;
        # build/test/compile mount it read-only so adversarial test code cannot poison it.
        rc, out, err = await execute_in_sandbox(environment_id, setup_cmd, repo_root, network="bridge", cache_writable=True)
        restore_out = (out + "\n" + err).strip()
        if rc != 0:
            log.debug(f"Dependency restore (test-compile) failed with exit code: {rc}")
            return False, ["🚨 Dependency restore failed:"] + restore_out.splitlines()
        if restore_out:
            log.debug(f"Dependency restore output: {restore_out}")

    log.debug(f"Executing QA test-compile gate [{environment_id}] (network OFF): {test_compile_cmd}")
    returncode, stdout, stderr = await execute_in_sandbox(environment_id, test_compile_cmd, repo_root, network="none")
    log_lines = (stdout + "\n" + stderr).strip().splitlines()
    log.debug(f"QA test-compile gate completed with exit code: {returncode}")
    return returncode == 0, log_lines


async def run_format_pass(environment_id: str, repo_root: str) -> None:
    """Deterministic cleanup run over the workspace right after QA writes test files, before the
    compile gate. Its main job is stripping unused imports (a HARD compile error in Go) so generated
    tests don't bounce QA→Reviewer over a trivial `imported and not used`. Runs the env's optional
    `format_cmd` (network OFF). STRICTLY non-fatal: any missing tool, non-zero exit, or sandbox error
    is logged and swallowed — a formatter hiccup must never derail the pipeline. No-ops when the env
    declares no `format_cmd`."""
    format_cmd = SUPPORTED_ENVIRONMENTS[environment_id].get("format_cmd")
    if not format_cmd:
        return
    try:
        log.debug(f"Executing format pass [{environment_id}] (network OFF): {format_cmd}")
        rc, stdout, stderr = await execute_in_sandbox(environment_id, format_cmd, repo_root, network="none")
        if rc != 0:
            tail = (stderr or stdout).strip().splitlines()[-3:]
            log.warning(f"🟡 Format pass [{environment_id}] exited {rc} (non-fatal): {' | '.join(tail)}")
        else:
            log.debug(f"Format pass [{environment_id}] applied cleanly.")
    except Exception as exc:  # never let a cleanup pass break the run
        log.warning(f"🟡 Format pass [{environment_id}] errored (non-fatal): {exc}")


async def run_security_scan(environment_id: str, repo_root: str) -> tuple[bool, list[str]]:
    """Generic SAST gate: one Semgrep image scans every language. Runs fully OFFLINE — the image
    vendors its rules, so no semgrep.dev call (which fails behind a corporate TLS proxy) and no
    network window. Semgrep analyses source; it never executes the project code."""
    log.debug(f"Executing SAST security gate [{environment_id}] via {SAST_IMAGE}: {SAST_CMD}")
    returncode, stdout, stderr = await run_in_image(SAST_IMAGE, SAST_CMD, repo_root, network="none")
    log_lines = (stdout + "\n" + stderr).strip().splitlines()
    if returncode == 0 and not log_lines:
        log_lines = ["SAST execution passed. Zero vulnerabilities identified."]
    log.debug(f"SAST Security Gate completed with exit code: {returncode}")
    return returncode == 0, log_lines
