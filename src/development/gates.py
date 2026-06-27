import os
import re
from pathlib import Path

from src.shared.core.observability import log
from src.shared.core.environments import (
    SUPPORTED_ENVIRONMENTS, SAST_IMAGE, SAST_CMD, is_test_file, all_source_extensions,
    dependency_manifest, resolve_environment, repo_map_ignore_dirs,
)
from src.shared.core.docker_adapter import execute_in_sandbox, run_in_image

# The source-file extension alternation is REGISTRY-DERIVED (all_source_extensions) — never a hardcoded
# list — so adding a language to the env registry extends these parsers with NO edit here (the engine
# stays language-agnostic). Sorted longest-first by the helper, so e.g. `tsx` is tried before `ts`.
_SOURCE_EXT_ALT = "|".join(re.escape(ext.lstrip(".")) for ext in all_source_extensions())
# Compiler/diagnostic lines reference a source file with the line/col either COLON-style
# (`path/to/file.ext:line[:col]:` — ruff/gcc/go/eslint) OR MSBuild PARENTHESIS-style
# (`path/to/file.ext(line,col):` — Roslyn/`dotnet build`, `tsc --pretty false`). Both suffix forms are
# accepted so the parser stays language-agnostic: a stack whose compiler uses the parenthesis form
# (.NET) is classified by the SAME registry-derived regex with NO per-language branch. Without the
# parenthesis alternative, `build_failure_is_test_only`/`classify_lint_findings` silently fail to parse
# every MSBuild diagnostic (referenced==[] → "not test-only"), misrouting QA-owned test-compile errors
# to the Developer (who cannot edit tests) until the cycle budget is exhausted.
_FILE_REF_RE = re.compile(rf"^\s*([\w./\\-]+\.(?:{_SOURCE_EXT_ALT}))(?::\d+|\(\d+,\d+\))")
# A linter line that is ONLY a relative path with no `:line:col` (e.g. `gofmt -l` output). Kept as a
# SEPARATE pattern so the compile-error regex above is never loosened (which would risk mis-parsing the
# build gate's output). Used only by the lint-finding classifier.
_BARE_PATH_RE = re.compile(rf"^\s*([\w./\\-]+\.(?:{_SOURCE_EXT_ALT}))\s*$")


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
    "nu1301",
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
    "etimedout", "enotfound", "eai_again", "econnreset",
    "dial tcp",
    # NOTE: do NOT add the gates' own "🚨 Dependency restore failed:" banner here. It is prepended to
    # EVERY restore failure (gates.py run_*_gate), network OR not (e.g. MSB1003 "no project/solution",
    # a bad PackageReference). Matching it makes the classifier self-referential — it would tag every
    # restore failure as environmental and mask real code/config defects as false NU1301 network halts.
    # Match only the underlying tool's genuine network signatures above.
)
# Word-boundary matching, NOT naive substring. The short alnum error-code tokens (Node's `enotfound`/
# `eai_again`/`etimedout`/`econnreset`, NuGet's `nu1301`, …) collide as substrings of ordinary diagnostic
# words — e.g. `enotfound` ⊂ python `ModulENOTFOUNDError`, which would tag EVERY missing-module failure as
# a phantom network error. `\b…\b` requires the marker to stand alone as a token (spaces in multi-word
# phrases are already boundaries; `re.escape` keeps regex metachars literal), so a real `ENOTFOUND` from a
# DNS failure still matches while `ModuleNotFoundError` does not. Stays language-agnostic: one shared
# network-signature set matched uniformly across every stack, no per-language branch.
_ENV_BUILD_FAILURE_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(m) for m in _ENV_BUILD_FAILURE_MARKERS) + r")\b"
)


def build_failure_is_environmental(environment_id: str, log_lines: list[str]) -> bool:
    """True iff the build/restore output bears a network/feed-unreachable signature (and is therefore
    NOT a code defect). Used by the runner to fail FAST with a clear environment incident instead of
    rerouting the Developer to "fix" an unreachable package feed. Conservative: requires an explicit
    network/restore marker on a WORD BOUNDARY, so genuine compiler errors (and substrings like
    `ModuleNotFoundError` ⊃ `enotfound`) fall through to the normal compile-gate reroute."""
    blob = "\n".join(log_lines).lower()
    return _ENV_BUILD_FAILURE_RE.search(blob) is not None


# Cross-language MODULE-RESOLUTION failure signatures — a dependency import could not be resolved. ONE
# shared set matched uniformly across every stack (no per-language dict), mirroring _ENV_BUILD_FAILURE_MARKERS.
# Kept to specific multi-word phrases (not short codes), so plain substring matching carries no collision risk.
_MODULE_RESOLUTION_MARKERS = (
    "no module named",          # python: ModuleNotFoundError: No module named 'x'
    "cannot find module",       # node: Error: Cannot find module 'x'
    "could not find module",
    "unresolved import",
    "cannot find package",      # go: cannot find package "x"
)
_MODULE_RESOLUTION_RE = re.compile("|".join(re.escape(m) for m in _MODULE_RESOLUTION_MARKERS))


def missing_dependency_manifest(environment_id: str, repo_root: str, log_lines: list[str]) -> bool:
    """True iff a gate failed on a module-resolution error AND the env's registry-declared dependency
    manifest is ABSENT from the repo — i.e. the dependencies were never declared where the toolchain
    restores them (the silent ``pip install -r requirements.txt 2>/dev/null || true`` no-op class: the
    restore exits 0 but installs nothing, so the failure surfaces two phases later as a module-not-found
    error mistaken for a code defect and misrouted to the Reviewer).

    Registry-driven (``dependency_manifest``) so no language is hardcoded. Requires BOTH conditions, so a
    genuine code defect, a network failure, OR a legitimately stdlib-only app (no third-party deps, hence
    no manifest needed and no import error) all fall through as False — never a false positive.
    """
    manifest = dependency_manifest(environment_id)
    if not manifest:
        return False
    blob = "\n".join(log_lines).lower()
    if not _MODULE_RESOLUTION_RE.search(blob):
        return False
    root = Path(repo_root)
    if not root.exists():
        return False
    return not any(root.rglob(manifest))


def annotate_missing_manifest(environment_id: str, repo_root: str, log_lines: list[str]) -> list[str]:
    """Prepend an explicit, actionable banner to a FAILED gate's output when the failure is the
    missing-dependency-manifest class (``missing_dependency_manifest``). The banner makes the diagnosis
    self-evident wherever the feedback lands — the Developer (who owns production deps) sees exactly what
    to create, instead of the Reviewer/Arbiter mislabelling a missing `requirements.txt` as a code defect
    and halting `unrecoverable`. A no-op for any other failure, so it never alters normal routing."""
    if not missing_dependency_manifest(environment_id, repo_root, log_lines):
        return log_lines
    manifest = dependency_manifest(environment_id)
    log.warning(f"🔶 Gate failure is a MISSING DEPENDENCY MANIFEST [{environment_id}]: `{manifest}` is "
                "absent — dependencies were declared nowhere the toolchain restores from.")
    return [
        f"🚨 MISSING DEPENDENCY MANIFEST: `{manifest}` is absent from the repository, so the toolchain "
        f"restored NO dependencies and the import above could not be resolved. This is NOT a code defect "
        f"in the modules — declare EVERY third-party dependency in `{manifest}` at the repo root (the "
        f"file the build/test toolchain restores from), then the import will resolve.",
    ] + log_lines


# Signatures of a lint/format TOOL that could not RUN AT ALL — a bad flag, an unknown subcommand, or a
# missing binary. These mean the engine's own `lint_cmd` is misconfigured (e.g. `ruff format` does not
# accept `--extend-exclude`), NOT that the code has a style defect: no Developer/QA edit can clear them.
# The runner must fail FAST with an environment incident rather than fold the gate failure into the
# budgeted cycle, where the lint-BLIND Reviewer approves the code and the Arbiter then halts with a
# misleading "unrecoverable" verdict (the exact shape that masked a malformed lint_cmd). Kept to strong
# CLI-invocation signatures so a genuine lint FINDING (which names a `file:line` and a rule code) is never
# misread as a tool error. Language-agnostic: one shared set across ruff/eslint/go vet/dotnet — no branch.
_LINT_TOOL_ERROR_MARKERS = (
    "unexpected argument",
    "unrecognized option",
    "unrecognized arguments",
    "unrecognized subcommand",
    "unknown flag",
    "unknown option",
    "invalid choice",
    "no such option",
    "flag provided but not defined",
    "usage:",
    "command not found",
)
_LINT_TOOL_ERROR_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(m) for m in _LINT_TOOL_ERROR_MARKERS) + r")"
)


def lint_failure_is_tooling(environment_id: str, log_lines: list[str]) -> bool:
    """True iff the lint-gate output bears a CLI-invocation-error signature — the linter/formatter could
    not execute (bad flag, unknown subcommand, missing binary), so the failure is an environment/registry
    misconfig (a wrong ``lint_cmd``), NOT an agent-fixable style finding. Used by the runner to fail FAST
    with an environment incident instead of rerouting agents who cannot fix the engine's own command.
    Conservative — a real finding (``file:line: RULE message``) carries none of these markers — and
    symmetric with ``build_failure_is_environmental`` (a tooling failure the agents cannot repair)."""
    blob = "\n".join(log_lines).lower()
    return _LINT_TOOL_ERROR_RE.search(blob) is not None


def classify_lint_findings(environment_id: str, log_lines: list[str]) -> tuple[list[str], list[str]]:
    """Split lint-gate output into ``(production_findings, test_findings)`` so each routes to the right
    isolated channel — production findings → Developer, test findings → QA — exactly the prod/test split
    the compile gates already enforce via ``is_test_file``.

    Stateful by design: a line that references a source file (``path:line:col`` OR a bare ``path`` like
    ``gofmt -l``) sets the 'current file'; following detail lines with no path of their own inherit that
    file's bucket. This handles both per-line tools (ruff, ``go vet``) and file-grouped tools (eslint
    'stylish', which prints the path once then indented findings). Leading lines before any file
    reference (banner/preamble) are dropped."""
    prod: list[str] = []
    test: list[str] = []
    current_is_test: bool | None = None
    for line in log_lines:
        m = _FILE_REF_RE.match(line) or _BARE_PATH_RE.match(line)
        if m:
            current_is_test = is_test_file(environment_id, m.group(1))
        if current_is_test is True:
            test.append(line)
        elif current_is_test is False:
            prod.append(line)
    return prod, test


def ran_zero_tests(environment_id: str, log_lines: list[str]) -> bool:
    """True iff the functional-test output proves the runner executed ZERO tests for a NON-empty suite.

    Backstop for the orphan-test failure mode: test files exist on disk but aren't wired into any
    compiled/executed target (e.g. a test project missing from the solution), so the runner silently
    discovers nothing and exits 0 — a green merge with no coverage. The per-stack signals live in the env
    registry (``empty_test_markers``/``ran_test_markers`` on SUPPORTED_ENVIRONMENTS), NOT in this gate — so
    the engine stays language-agnostic and a new stack opts in by declaring markers, with no edit here.

    Conservative / asymmetric-safe: fires ONLY when the stack declares empty-markers AND an explicit empty
    marker is present AND no 'tests ran' marker is — so a real run (which never prints an empty marker), or a
    multi-target run where one target has no tests while siblings ran, never trips it. A stack that declares
    no ``empty_test_markers`` (e.g. Go) is exempt: the check returns False, leaving gate behaviour unchanged.
    """
    spec = SUPPORTED_ENVIRONMENTS[environment_id]
    empty_markers = spec.get("empty_test_markers")
    if not empty_markers:
        return False
    ran_markers = spec.get("ran_test_markers", ())
    blob = "\n".join(log_lines).lower()
    if any(m in blob for m in ran_markers):
        return False
    return any(m in blob for m in empty_markers)


def _has_test_files(environment_id: str, repo_root: str) -> bool:
    """True if the workspace holds ≥1 test file for the target stack (language-aware, via the
    is_test_file SSOT). Runner-agnostic empty-suite detection: rather than special-casing each
    runner's "no tests" exit code (pytest 5, jest 1, go/dotnet 0), ask whether any test file is
    even present. None present → the functional gate is a no-op pass (e.g. a ticket with no testable
    source, like a thin scaffold/entrypoint). The Reviewer's test_integrity gate remains the backstop
    when tests WERE expected."""
    ignore = repo_map_ignore_dirs(environment_id) | {".git"}
    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in ignore]
        if any(is_test_file(environment_id, name) for name in files):
            return True
    return False


# ==========================================
# PARALLEL RUNTIME GATES (Sandboxed execution)
# ==========================================
# Commands come from the static SUPPORTED_ENVIRONMENTS registry and run inside the canonical,
# hardened sandbox image for the ticket's environment_id — no host tooling, no hardcoded runtime.
async def run_qa_unit_tests(environment_id: str, repo_root: str, env_overlays: dict | None = None) -> tuple[bool, list[str]]:
    """Functional-test gate. Dependency restore runs FIRST with network ON (project deps can't be
    baked into the image); the tests themselves then run with network OFF (isolated execution)."""
    spec = resolve_environment(environment_id, env_overlays)
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
    # Orphan-test backstop: test files exist (we passed the empty-suite short-circuit above) yet the runner
    # executed ZERO tests — the suite isn't wired into a compiled/executed target (e.g. a .NET test project
    # missing from the solution). Fail explicitly instead of merging a zero-coverage green that exited 0.
    if ran_zero_tests(environment_id, log_lines):
        log.warning(f"🔶 Functional-test gate [{environment_id}]: test files present but the runner executed "
                    "ZERO tests — the suite is not wired into a build/execute target (missing/unregistered "
                    "test project).")
        return False, [
            "🚨 Test files are present but the test runner executed ZERO tests — the suite is not wired into "
            "a compiled/executed target (e.g. the test project is missing from the solution or not "
            "registered in the build). Register the test project so the contracted tests actually run.",
        ] + log_lines
    if returncode != 0:
        log_lines = annotate_missing_manifest(environment_id, repo_root, log_lines)
    return returncode == 0, log_lines


async def run_build_gate(environment_id: str, repo_root: str, env_overlays: dict | None = None) -> tuple[bool, list[str]]:
    """Compile gate run right after the Developer: restore deps (network ON) then compile/typecheck
    (network OFF). BUILD/RUN ONLY — `build_cmd` never executes tests, so the Developer stays fenced
    off from the QA-owned test files. Returns ``(ok, log_lines)``; a no-op pass when the env declares
    no ``build_cmd``."""
    spec = resolve_environment(environment_id, env_overlays)
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
    if returncode != 0:
        log_lines = annotate_missing_manifest(environment_id, repo_root, log_lines)
    return returncode == 0, log_lines


async def run_test_compile_gate(environment_id: str, repo_root: str, env_overlays: dict | None = None) -> tuple[bool, list[str]]:
    """Pre-Reviewer COMPILE-ONLY gate over the QA-generated tests: restore deps (network ON) then run
    the env's `test_compile_cmd` (network OFF), which builds the test code but runs NO test bodies.
    Surfaces test compile errors (unused imports, undefined symbols) deterministically so the runner
    can fast-fail-reroute them to the QA channel without spending the Reviewer. Compile-only (not
    `go test`) on purpose: a real assertion failure references the test file too, so running tests here
    would misroute production bugs to QA. Returns ``(ok, log_lines)``; a no-op pass when the env has no
    `test_compile_cmd` or no test files are present."""
    spec = resolve_environment(environment_id, env_overlays)
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
    if returncode != 0:
        log_lines = annotate_missing_manifest(environment_id, repo_root, log_lines)
    return returncode == 0, log_lines


async def run_lint_gate(environment_id: str, repo_root: str, env_overlays: dict | None = None) -> tuple[bool, list[str]]:
    """HARD style/lint gate: restore deps (network ON) then run the env's `lint_cmd` (network OFF).

    The engine's own quality bar so a strict CI stays green — `lint_cmd` is the SSOT the DevOps-generated
    workflow also runs, making engine-green ⇒ CI-green. Returns ``(ok, log_lines)``; a no-op pass when the
    env declares no `lint_cmd`. (A stack whose linter needs project config to run — e.g. node/eslint —
    self-guards INSIDE its `lint_cmd`, exiting 0 when the config is absent, so the engine carries no
    per-language branch.) Verify-only — the paired `format_cmd` autofix runs first, so only genuinely-
    unfixable findings (e.g. F841) fail here."""
    spec = resolve_environment(environment_id, env_overlays)
    lint_cmd = spec.get("lint_cmd")
    if not lint_cmd:
        return True, []

    setup_cmd = spec.get("setup_cmd")
    if setup_cmd:
        log.debug(f"Restoring dependencies for lint [{environment_id}] (network ON): {setup_cmd}")
        # cache_writable: the restore phase is the ONLY writer of the persistent package cache volume.
        rc, out, err = await execute_in_sandbox(environment_id, setup_cmd, repo_root, network="bridge", cache_writable=True)
        restore_out = (out + "\n" + err).strip()
        if rc != 0:
            log.debug(f"Dependency restore (lint) failed with exit code: {rc}")
            return False, ["🚨 Dependency restore failed:"] + restore_out.splitlines()
        if restore_out:
            log.debug(f"Dependency restore output: {restore_out}")

    log.debug(f"Executing lint gate [{environment_id}] (network OFF): {lint_cmd}")
    returncode, stdout, stderr = await execute_in_sandbox(environment_id, lint_cmd, repo_root, network="none")
    log_lines = (stdout + "\n" + stderr).strip().splitlines()
    log.debug(f"Lint gate completed with exit code: {returncode}")
    return returncode == 0, log_lines


async def run_format_pass(environment_id: str, repo_root: str, env_overlays: dict | None = None) -> None:
    """Deterministic cleanup run over the workspace right after QA writes test files, before the
    compile gate. Its main job is stripping unused imports (a HARD compile error in Go) so generated
    tests don't bounce QA→Reviewer over a trivial `imported and not used`. Runs the env's optional
    `format_cmd` (network OFF). STRICTLY non-fatal: any missing tool, non-zero exit, or sandbox error
    is logged and swallowed — a formatter hiccup must never derail the pipeline. No-ops when the env
    declares no `format_cmd`."""
    format_cmd = resolve_environment(environment_id, env_overlays).get("format_cmd")
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
