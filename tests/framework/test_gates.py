"""Unit tests for the runtime validation gates.

Docker is never invoked: ``execute_in_sandbox`` / ``run_in_image`` are mocked so the registry-sourced
commands, the network phasing, and the adapter's ``(returncode, stdout, stderr)`` contract can be
inspected deterministically.
"""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from unittest.mock import AsyncMock, call

from src.development.gates import (
    run_qa_unit_tests, run_security_scan, run_build_gate, run_format_pass, run_test_compile_gate,
    run_lint_gate, classify_lint_findings, ran_zero_tests,
    build_failure_is_test_only, build_failure_is_environmental, lint_failure_is_tooling,
    missing_dependency_manifest, annotate_missing_manifest,
    _has_test_files, _FILE_REF_RE,
)
from src.shared.core.environments import SUPPORTED_ENVIRONMENTS, SAST_IMAGE, SAST_CMD, all_source_extensions

_ENV = "python-3.12-core"
_REPO = "/abs/repo/root"
_SETUP = SUPPORTED_ENVIRONMENTS[_ENV]["setup_cmd"]
_TEST = SUPPORTED_ENVIRONMENTS[_ENV]["test_cmd"]
_BUILD = SUPPORTED_ENVIRONMENTS[_ENV]["build_cmd"]
_TCOMPILE = SUPPORTED_ENVIRONMENTS[_ENV]["test_compile_cmd"]
_LINT = SUPPORTED_ENVIRONMENTS[_ENV]["lint_cmd"]


class RunQaUnitTestsTests(unittest.IsolatedAsyncioTestCase):
    """The QA gate restores deps (network ON) then runs the registry test_cmd (network OFF).

    The empty-suite guard (`_has_test_files`) is forced True here so these cases exercise the
    restore/test phasing; the no-test no-op pass is covered by EmptySuiteGateTests below."""

    @mock.patch("src.development.gates._has_test_files", return_value=True)
    @mock.patch("src.development.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_restore_then_test_with_network_phasing(self, mock_sandbox: AsyncMock, _has: mock.Mock) -> None:
        mock_sandbox.side_effect = [(0, "go: no module dependencies to download", ""), (0, "ran 3 tests", "")]

        ok, log_lines = await run_qa_unit_tests(environment_id=_ENV, repo_root=_REPO)

        self.assertTrue(ok)
        # Restore runs first (network ON), then tests (network OFF).
        self.assertEqual(mock_sandbox.await_args_list, [
            call(_ENV, _SETUP, _REPO, network="bridge", cache_writable=True),
            call(_ENV, _TEST, _REPO, network="none"),
        ])
        # Benign successful-restore output must NOT pollute the test result context.
        self.assertEqual(log_lines, ["ran 3 tests"])

    @mock.patch("src.development.gates._has_test_files", return_value=True)
    @mock.patch("src.development.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_successful_restore_noise_excluded_from_test_failure(self, mock_sandbox: AsyncMock, _has: mock.Mock) -> None:
        # Restore succeeds (benign stderr), tests FAIL — the failure context is the test output only.
        mock_sandbox.side_effect = [
            (0, "go: no module dependencies to download", ""),
            (1, "", "processor_test.go:9: undefined: Convert"),
        ]

        ok, log_lines = await run_qa_unit_tests(environment_id=_ENV, repo_root=_REPO)

        self.assertFalse(ok)
        self.assertEqual(log_lines, ["processor_test.go:9: undefined: Convert"])
        self.assertNotIn("go: no module dependencies to download", log_lines)

    @mock.patch("src.development.gates._has_test_files", return_value=True)
    @mock.patch("src.development.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_restore_failure_short_circuits_before_tests(self, mock_sandbox: AsyncMock, _has: mock.Mock) -> None:
        mock_sandbox.return_value = (1, "could not resolve deps", "")

        ok, log_lines = await run_qa_unit_tests(environment_id=_ENV, repo_root=_REPO)

        self.assertFalse(ok)
        mock_sandbox.assert_awaited_once_with(_ENV, _SETUP, _REPO, network="bridge", cache_writable=True)  # tests never reached
        self.assertIn("🚨 Dependency restore failed:", log_lines[0])

    @mock.patch("src.development.gates._has_test_files", return_value=True)
    @mock.patch("src.development.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_nonzero_test_exit_reports_failure(self, mock_sandbox: AsyncMock, _has: mock.Mock) -> None:
        mock_sandbox.side_effect = [(0, "", ""), (1, "out line", "err line")]

        ok, log_lines = await run_qa_unit_tests(environment_id=_ENV, repo_root=_REPO)

        self.assertFalse(ok)
        self.assertEqual(log_lines, ["out line", "err line"])


class ZeroTestsGuardTests(unittest.IsolatedAsyncioTestCase):
    """Orphan-test backstop: when test files ARE present but the runner executed ZERO tests (the suite is
    not wired into a build/execute target — e.g. a .NET test project missing from the solution), the gate
    FAILS instead of merging a zero-coverage green that exited 0. See `ran_zero_tests`. Asymmetric-safe:
    it fires ONLY on an explicit 'ran zero' marker, so a real run can never trip it."""

    _DOTNET = "dotnet-10-sdk"

    def test_ran_zero_tests_dotnet_no_test_available(self) -> None:
        self.assertTrue(ran_zero_tests(self._DOTNET, ["Build succeeded.", "No test is available in JsonToCsv.dll."]))

    def test_ran_zero_tests_suppressed_when_a_sibling_target_ran(self) -> None:
        # Multi-target run: one assembly had no tests, another ran — the 'ran' marker suppresses the fail.
        self.assertFalse(ran_zero_tests(self._DOTNET, ["No test is available in Empty.dll.", "Passed!  - Failed: 0, Passed: 5"]))

    def test_ran_zero_tests_false_on_real_run(self) -> None:
        self.assertFalse(ran_zero_tests(self._DOTNET, ["Passed!  - Failed: 0, Passed: 3, Skipped: 0, Total: 3"]))
        self.assertFalse(ran_zero_tests(_ENV, ["===== 5 passed in 0.10s ====="]))

    def test_ran_zero_tests_python_no_tests_ran(self) -> None:
        self.assertTrue(ran_zero_tests(_ENV, ["collected 0 items", "no tests ran in 0.01s"]))

    def test_go_is_exempt_from_the_guard(self) -> None:
        # Go has no entry in the signal map → the check never fires (its `[no test files]` is per-package,
        # and colocated Go tests cannot be orphaned the way a separate .NET test project can).
        self.assertFalse(ran_zero_tests("go-1.23-cli", ["?   pkg   [no test files]"]))

    @mock.patch("src.development.gates._has_test_files", return_value=True)
    @mock.patch("src.development.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_orphan_tests_fail_the_gate(self, mock_sandbox: AsyncMock, _has: mock.Mock) -> None:
        # Restore OK, then `dotnet test` discovers nothing (orphaned test source) and exits 0 → gate FAILS.
        mock_sandbox.side_effect = [(0, "restored", ""), (0, "No test is available in JsonToCsv.dll.", "")]
        ok, log_lines = await run_qa_unit_tests(environment_id=self._DOTNET, repo_root=_REPO)
        self.assertFalse(ok)
        self.assertTrue(any("executed ZERO tests" in ln for ln in log_lines))

    @mock.patch("src.development.gates._has_test_files", return_value=True)
    @mock.patch("src.development.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_real_run_still_passes(self, mock_sandbox: AsyncMock, _has: mock.Mock) -> None:
        mock_sandbox.side_effect = [(0, "restored", ""), (0, "Passed!  - Failed: 0, Passed: 1, Total: 1", "")]
        ok, log_lines = await run_qa_unit_tests(environment_id=self._DOTNET, repo_root=_REPO)
        self.assertTrue(ok)


class FileRefRegexDerivationTests(unittest.TestCase):
    """The compile-error/lint file-ref regex is built from all_source_extensions() — not a hardcoded
    extension list — so a new registry language is parsed with no edit to gates.py. Pin that linkage."""

    def test_regex_matches_every_registered_source_extension(self) -> None:
        for ext in all_source_extensions():
            self.assertIsNotNone(_FILE_REF_RE.match(f"  src/pkg/file{ext}:12:5: error"), ext)

    def test_regex_rejects_a_non_source_extension(self) -> None:
        # A doc/config path must NOT be misread as a compiled source ref.
        self.assertIsNone(_FILE_REF_RE.match("README.md:3:1: note"))


class RunFormatPassTests(unittest.IsolatedAsyncioTestCase):
    """The post-QA format pass runs the env's optional format_cmd (network OFF) and is strictly
    non-fatal: a missing key no-ops, and a non-zero exit or sandbox error is swallowed."""

    _GO = "go-1.23-cli"
    _GO_FMT = SUPPORTED_ENVIRONMENTS[_GO]["format_cmd"]

    @mock.patch("src.development.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_runs_format_cmd_network_off(self, mock_sandbox: AsyncMock) -> None:
        mock_sandbox.return_value = (0, "", "")
        await run_format_pass(self._GO, _REPO)
        mock_sandbox.assert_awaited_once_with(self._GO, self._GO_FMT, _REPO, network="none")

    @mock.patch("src.development.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_noop_when_no_format_cmd(self, mock_sandbox: AsyncMock) -> None:
        # Build a throwaway env spec with no format_cmd; the pass must not touch the sandbox.
        env_id = "no-fmt-env"
        with mock.patch.dict(SUPPORTED_ENVIRONMENTS, {env_id: {"image": "x"}}, clear=False):
            await run_format_pass(env_id, _REPO)
        mock_sandbox.assert_not_awaited()

    @mock.patch("src.development.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_nonzero_exit_is_non_fatal(self, mock_sandbox: AsyncMock) -> None:
        mock_sandbox.return_value = (1, "", "goimports: boom")
        # Must NOT raise — a formatter hiccup never derails the pipeline.
        await run_format_pass(self._GO, _REPO)
        mock_sandbox.assert_awaited_once()

    @mock.patch("src.development.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_sandbox_exception_is_swallowed(self, mock_sandbox: AsyncMock) -> None:
        mock_sandbox.side_effect = RuntimeError("docker unavailable")
        await run_format_pass(self._GO, _REPO)  # no raise


class EmptySuiteGateTests(unittest.IsolatedAsyncioTestCase):
    """An empty test suite (no test files) is a no-op PASS — never a fictitious functional failure
    from a runner that exits non-zero on "no tests collected" (pytest 5, jest 1)."""

    @mock.patch("src.development.gates._has_test_files", return_value=False)
    @mock.patch("src.development.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_no_test_files_passes_without_running_runner(self, mock_sandbox: AsyncMock, _has: mock.Mock) -> None:
        ok, log_lines = await run_qa_unit_tests(environment_id=_ENV, repo_root=_REPO)

        self.assertTrue(ok)
        # Neither dependency restore nor the test runner is invoked — there is nothing to execute.
        mock_sandbox.assert_not_awaited()
        self.assertTrue(any("empty suite" in line for line in log_lines))


class HasTestFilesTests(unittest.TestCase):
    """`_has_test_files` applies the env-aware `is_test_file` SSOT over the workspace tree."""

    def test_detects_python_test_file(self) -> None:
        import tempfile, os as _os
        with tempfile.TemporaryDirectory() as d:
            _os.makedirs(_os.path.join(d, "tests"))
            open(_os.path.join(d, "tests", "test_converter.py"), "w").close()
            self.assertTrue(_has_test_files(_ENV, d))

    def test_no_test_files_in_sourceless_tree(self) -> None:
        import tempfile, os as _os
        with tempfile.TemporaryDirectory() as d:
            for name in (".gitignore", "README.md", "LICENSE"):
                open(_os.path.join(d, name), "w").close()
            self.assertFalse(_has_test_files(_ENV, d))


class RunBuildGateTests(unittest.IsolatedAsyncioTestCase):
    """The compile gate restores deps (network ON) then builds (network OFF) — build/run only."""

    @mock.patch("src.development.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_restore_then_build_with_network_phasing(self, mock_sandbox: AsyncMock) -> None:
        mock_sandbox.side_effect = [(0, "restored", ""), (0, "build ok", "")]

        ok, log_lines = await run_build_gate(environment_id=_ENV, repo_root=_REPO)

        self.assertTrue(ok)
        self.assertEqual(mock_sandbox.await_args_list, [
            call(_ENV, _SETUP, _REPO, network="bridge", cache_writable=True),
            call(_ENV, _BUILD, _REPO, network="none"),
        ])

    @mock.patch("src.development.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_nonzero_build_exit_reports_failure(self, mock_sandbox: AsyncMock) -> None:
        mock_sandbox.side_effect = [(0, "", ""), (1, "undefined: Foo", "")]

        ok, log_lines = await run_build_gate(environment_id=_ENV, repo_root=_REPO)

        self.assertFalse(ok)
        self.assertIn("undefined: Foo", log_lines)

    @mock.patch("src.development.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_restore_failure_short_circuits_before_build(self, mock_sandbox: AsyncMock) -> None:
        mock_sandbox.return_value = (1, "deps error", "")

        ok, log_lines = await run_build_gate(environment_id=_ENV, repo_root=_REPO)

        self.assertFalse(ok)
        mock_sandbox.assert_awaited_once_with(_ENV, _SETUP, _REPO, network="bridge", cache_writable=True)  # build never reached


class RunTestCompileGateTests(unittest.IsolatedAsyncioTestCase):
    """The pre-Reviewer QA test-compile gate: restore (network ON) → compile-only tests (network OFF),
    with no-op passes when there's no `test_compile_cmd` or no test files."""

    @mock.patch("src.development.gates._has_test_files", return_value=True)
    @mock.patch("src.development.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_restore_then_compile_with_network_phasing(self, mock_sandbox: AsyncMock, _has: mock.Mock) -> None:
        mock_sandbox.side_effect = [(0, "restored", ""), (0, "collected 3 items", "")]

        ok, log_lines = await run_test_compile_gate(environment_id=_ENV, repo_root=_REPO)

        self.assertTrue(ok)
        self.assertEqual(mock_sandbox.await_args_list, [
            call(_ENV, _SETUP, _REPO, network="bridge", cache_writable=True),
            call(_ENV, _TCOMPILE, _REPO, network="none"),
        ])

    @mock.patch("src.development.gates._has_test_files", return_value=True)
    @mock.patch("src.development.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_compile_failure_reports_lines(self, mock_sandbox: AsyncMock, _has: mock.Mock) -> None:
        mock_sandbox.side_effect = [(0, "", ""), (1, "", "test_x.py:2: ImportError: no module")]

        ok, log_lines = await run_test_compile_gate(environment_id=_ENV, repo_root=_REPO)

        self.assertFalse(ok)
        self.assertIn("test_x.py:2: ImportError: no module", log_lines)

    @mock.patch("src.development.gates._has_test_files", return_value=False)
    @mock.patch("src.development.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_noop_when_no_test_files(self, mock_sandbox: AsyncMock, _has: mock.Mock) -> None:
        ok, log_lines = await run_test_compile_gate(environment_id=_ENV, repo_root=_REPO)
        self.assertTrue(ok)
        mock_sandbox.assert_not_awaited()

    @mock.patch("src.development.gates._has_test_files", return_value=True)
    @mock.patch("src.development.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_noop_when_env_has_no_test_compile_cmd(self, mock_sandbox: AsyncMock, _has: mock.Mock) -> None:
        env_id = "no-tc-env"
        with mock.patch.dict(SUPPORTED_ENVIRONMENTS, {env_id: {"image": "x"}}, clear=False):
            ok, log_lines = await run_test_compile_gate(environment_id=env_id, repo_root=_REPO)
        self.assertTrue(ok)
        mock_sandbox.assert_not_awaited()


class RunSecurityScanTests(unittest.IsolatedAsyncioTestCase):
    """The SAST gate runs the GENERIC Semgrep image (not the language image) over the repo."""

    @mock.patch("src.development.gates.run_in_image", new_callable=AsyncMock)
    async def test_runs_generic_semgrep_image_offline(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = (1, "findings", "")

        ok, log_lines = await run_security_scan(environment_id=_ENV, repo_root=_REPO)

        self.assertFalse(ok)
        # Vendored-rules image → fully offline (no semgrep.dev call behind the corporate proxy).
        mock_run.assert_awaited_once_with(SAST_IMAGE, SAST_CMD, _REPO, network="none")
        self.assertEqual(log_lines, ["findings"])

    @mock.patch("src.development.gates.run_in_image", new_callable=AsyncMock)
    async def test_silent_success_injects_pass_message(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = (0, "", "")

        ok, log_lines = await run_security_scan(environment_id=_ENV, repo_root=_REPO)

        self.assertTrue(ok)
        self.assertEqual(log_lines, ["SAST execution passed. Zero vulnerabilities identified."])


class BuildFailureClassifierTests(unittest.TestCase):
    """`build_failure_is_test_only` decides whether a build failure is QA-owned (test files only)."""

    _GO = "go-1.23-cli"

    def test_test_only_failure_is_true(self) -> None:
        lines = [
            "internal/converter/processor_test.go:1:1: expected 'package', found 'import'",
            "cmd/json2csv/main_test.go:1:1: expected 'package', found 'import'",
        ]
        self.assertTrue(build_failure_is_test_only(self._GO, lines))

    def test_mixed_prod_and_test_is_false(self) -> None:
        lines = [
            "internal/converter/processor.go:10:2: undefined: Foo",
            "internal/converter/processor_test.go:1:1: expected 'package', found 'import'",
        ]
        self.assertFalse(build_failure_is_test_only(self._GO, lines))

    def test_production_only_is_false(self) -> None:
        self.assertFalse(build_failure_is_test_only(self._GO, ["cmd/json2csv/main.go:3:1: syntax error"]))

    def test_no_file_refs_is_false(self) -> None:
        self.assertFalse(build_failure_is_test_only(self._GO, ["go: some toolchain error", ""]))

    # MSBuild emits `path(line,col):` diagnostics (parenthesis form), NOT `path:line:col`. `dotnet build`
    # compiles the test project too, so a QA-owned test-compile error surfaces in the production build
    # gate; it MUST be classified test-only (→ QA), never rerouted to the Developer who cannot edit tests.
    _DOTNET = "dotnet-10-sdk"

    def test_msbuild_test_only_failure_is_true(self) -> None:
        lines = [
            "/workspace/tests/JsonToCsv.Tests/ProgramTests.cs(53,10): error CS0182: An attribute argument "
            "must be a constant expression [/workspace/tests/JsonToCsv.Tests/JsonToCsv.Tests.csproj]",
            "/workspace/tests/JsonToCsv.Tests/ProgramTests.cs(20,30): error CS0029: Cannot implicitly "
            "convert type 'void' to 'int' [/workspace/tests/JsonToCsv.Tests/JsonToCsv.Tests.csproj]",
        ]
        self.assertTrue(build_failure_is_test_only(self._DOTNET, lines))

    def test_msbuild_production_only_is_false(self) -> None:
        self.assertFalse(build_failure_is_test_only(
            self._DOTNET,
            ["/workspace/src/JsonToCsv.Cli/Program.cs(12,9): error CS0103: The name 'Foo' does not exist"],
        ))

    def test_msbuild_mixed_prod_and_test_is_false(self) -> None:
        lines = [
            "/workspace/src/JsonToCsv.Cli/Program.cs(12,9): error CS0103: The name 'Foo' does not exist",
            "/workspace/tests/JsonToCsv.Tests/ProgramTests.cs(53,10): error CS0182: attribute argument",
        ]
        self.assertFalse(build_failure_is_test_only(self._DOTNET, lines))


class EnvironmentalBuildFailureTests(unittest.TestCase):
    """`build_failure_is_environmental` flags feed/DNS/proxy-unreachable failures (NOT code defects)."""

    _DOTNET = "dotnet-10-sdk"

    def test_nuget_service_index_unreachable_is_environmental(self) -> None:
        lines = ["/workspace/src/x.csproj : error NU1301: Unable to load the service index for source https://api.nuget.org/v3/index.json"]
        self.assertTrue(build_failure_is_environmental(self._DOTNET, lines))

    def test_resource_temporarily_unavailable_is_environmental(self) -> None:
        lines = ["error NU1301:   Resource temporarily unavailable (api.nuget.org:443)"]
        self.assertTrue(build_failure_is_environmental(self._DOTNET, lines))

    def test_dns_and_npm_errno_are_environmental(self) -> None:
        self.assertTrue(build_failure_is_environmental("node-20-web", ["npm error code EAI_AGAIN", "getaddrinfo EAI_AGAIN registry.npmjs.org"]))
        self.assertTrue(build_failure_is_environmental("go-1.23-cli", ["dial tcp: lookup proxy.golang.org: Temporary failure in name resolution"]))

    def test_restore_banner_without_network_signature_is_not_environmental(self) -> None:
        # Regression guard: the gates prepend "🚨 Dependency restore failed:" to EVERY restore failure.
        # A restore that failed for a NON-network reason (here MSB1003 — no project/solution at the
        # restore CWD) must NOT be misread as a network halt just because that banner is present; it must
        # fall through to the normal compile-gate reroute so the Developer can fix the real defect.
        lines = [
            "🚨 Dependency restore failed:",
            "MSBUILD : error MSB1003: Specify a project or solution file. The current working "
            "directory does not contain a project or solution file.",
        ]
        self.assertFalse(build_failure_is_environmental(self._DOTNET, lines))

    def test_real_compiler_error_is_not_environmental(self) -> None:
        # A genuine code defect must fall through to the normal compile-gate reroute.
        self.assertFalse(build_failure_is_environmental(self._DOTNET, ["Program.cs(12,9): error CS0103: The name 'Foo' does not exist"]))
        self.assertFalse(build_failure_is_environmental("go-1.23-cli", ["internal/converter/processor.go:10:2: undefined: Foo"]))


class MissingDependencyManifestTests(unittest.TestCase):
    """`missing_dependency_manifest` flags the silent `pip install -r requirements.txt || true` no-op class
    (restore exits 0 but installed nothing because the manifest is absent) — registry-keyed, and ONLY when
    a module-resolution error is ALSO present, so a stdlib-only app / real code defect never false-positives."""

    _MODULE_ERR = ["E   ModuleNotFoundError: No module named 'fastapi'"]

    def test_missing_manifest_plus_import_error_is_flagged(self) -> None:
        with TemporaryDirectory() as repo:  # no requirements.txt on disk
            self.assertTrue(missing_dependency_manifest("python-3.12-core", repo, self._MODULE_ERR))

    def test_present_manifest_is_not_flagged(self) -> None:
        with TemporaryDirectory() as repo:
            (Path(repo) / "requirements.txt").write_text("fastapi==0.110.0\n", encoding="utf-8")
            self.assertFalse(missing_dependency_manifest("python-3.12-core", repo, self._MODULE_ERR))

    def test_no_import_error_is_not_flagged(self) -> None:
        # A legitimately stdlib-only app (no manifest, no import failure) must NOT be flagged.
        with TemporaryDirectory() as repo:
            self.assertFalse(missing_dependency_manifest("python-3.12-core", repo, ["1 passed in 0.1s"]))

    def test_unknown_env_is_exempt(self) -> None:
        with TemporaryDirectory() as repo:
            self.assertFalse(missing_dependency_manifest("no-such-env", repo, self._MODULE_ERR))

    def test_dotnet_csproj_glob_resolves_present_manifest(self) -> None:
        # `*.csproj` is matched via rglob, so a nested project file counts as present.
        with TemporaryDirectory() as repo:
            proj = Path(repo) / "src" / "App"
            proj.mkdir(parents=True)
            (proj / "App.csproj").write_text("<Project/>", encoding="utf-8")
            self.assertFalse(missing_dependency_manifest(
                "dotnet-10-sdk", repo, ["error CS: cannot find module 'X'"]))

    def test_annotate_prepends_actionable_banner_only_when_flagged(self) -> None:
        with TemporaryDirectory() as repo:
            annotated = annotate_missing_manifest("python-3.12-core", repo, self._MODULE_ERR)
            self.assertIn("MISSING DEPENDENCY MANIFEST", annotated[0])
            self.assertIn("requirements.txt", annotated[0])
            self.assertEqual(annotated[1:], self._MODULE_ERR)  # original lines preserved below the banner
            # A non-manifest failure is returned unchanged (no banner, no routing change).
            real_defect = ["E   AssertionError: 1 != 2"]
            self.assertEqual(annotate_missing_manifest("python-3.12-core", repo, real_defect), real_defect)


class DotnetFormatWorkspaceTargetingTests(unittest.TestCase):
    """Regression guard: `dotnet format` hard-crashes in ParseWorkspaceOptions (exit 1) when the CWD is
    ambiguous ("Both a MSBuild project file and solution file found in '.'") or empty ("no project or
    solution file found") — unlike build/restore/test, which prefer the .sln. So the dotnet lint/format
    commands MUST resolve a SINGLE explicit workspace (the root .sln, else a lone .csproj) and SKIP
    cleanly when none resolves, never invoke a bare `dotnet format`/`dotnet format .` that auto-discovers
    the CWD. A bare command silently reds the lint gate forever and loops the FSM to the breaker."""
    _SPEC = SUPPORTED_ENVIRONMENTS["dotnet-10-sdk"]

    def test_lint_and_format_resolve_and_target_the_solution(self) -> None:
        for key in ("lint_cmd", "format_cmd"):
            cmd = self._SPEC[key]
            self.assertIn("dotnet format", cmd, key)
            # Resolves a workspace target rather than relying on CWD auto-discovery (the crash trigger):
            # prefer the solution, fall back to a lone .csproj, into a quoted "$ws".
            # MUST match BOTH the newer .slnx (the .NET 10 `dotnet new sln` default) and the classic .sln —
            # globbing only *.sln would miss a .slnx and silently no-op the lint gate.
            self.assertIn("*.slnx", cmd, key)
            self.assertIn("*.sln", cmd, key)
            self.assertIn("*.csproj", cmd, key)
            self.assertIn('"$ws"', cmd, key)
            # Never targets a bare '.' (the ambiguous-/empty-CWD crash trigger we are guarding against).
            self.assertNotIn("dotnet format .", cmd, key)
            self.assertNotIn("${ws:-.}", cmd, key)

    def test_commands_skip_cleanly_when_no_workspace_resolves(self) -> None:
        # When neither a .sln nor a .csproj exists at the root, both commands exit 0 (a clean no-op)
        # rather than crashing dotnet format on an empty CWD — the non-fatal format-pass crash fix.
        for key in ("lint_cmd", "format_cmd"):
            cmd = self._SPEC[key]
            self.assertIn('if [ -z "$ws" ]', cmd, key)
            self.assertIn("exit 0", cmd, key)

    def test_commands_are_single_line(self) -> None:
        # The docker adapter rejects multi-line commands; the resolver must stay a one-liner.
        for key in ("lint_cmd", "format_cmd"):
            self.assertNotIn("\n", self._SPEC[key], key)

    def test_lint_is_verify_only_and_format_is_autofix(self) -> None:
        self.assertIn("--verify-no-changes", self._SPEC["lint_cmd"])
        self.assertNotIn("--verify-no-changes", self._SPEC["format_cmd"])


class RunLintGateTests(unittest.IsolatedAsyncioTestCase):
    """The HARD lint gate restores deps (network ON) then runs the registry `lint_cmd` (network OFF);
    no-op pass when the env has no `lint_cmd`; a stack whose linter needs project config (node/eslint)
    self-guards INSIDE its own `lint_cmd` (exit 0 when the config is absent), so gates.py has no node branch."""

    @mock.patch("src.development.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_restore_then_lint_with_network_phasing(self, mock_sandbox: AsyncMock) -> None:
        mock_sandbox.side_effect = [(0, "restored", ""), (0, "All checks passed!", "")]

        ok, log_lines = await run_lint_gate(environment_id=_ENV, repo_root=_REPO)

        self.assertTrue(ok)
        self.assertEqual(mock_sandbox.await_args_list, [
            call(_ENV, _SETUP, _REPO, network="bridge", cache_writable=True),
            call(_ENV, _LINT, _REPO, network="none"),
        ])

    @mock.patch("src.development.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_lint_violation_reports_failure(self, mock_sandbox: AsyncMock) -> None:
        mock_sandbox.side_effect = [
            (0, "", ""),
            (1, "tests/test_cli.py:26:71: F841 Local variable `mock_stdout` is assigned to but never used", ""),
        ]

        ok, log_lines = await run_lint_gate(environment_id=_ENV, repo_root=_REPO)

        self.assertFalse(ok)
        self.assertTrue(any("F841" in ln for ln in log_lines))

    @mock.patch("src.development.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_noop_when_no_lint_cmd(self, mock_sandbox: AsyncMock) -> None:
        env_id = "no-lint-env"
        with mock.patch.dict(SUPPORTED_ENVIRONMENTS, {env_id: {"image": "x", "language_id": "python"}}, clear=False):
            ok, log_lines = await run_lint_gate(environment_id=env_id, repo_root=_REPO)
        self.assertTrue(ok)
        mock_sandbox.assert_not_awaited()

    @mock.patch("src.development.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_node_lint_runs_through_sandbox_no_host_branch(self, mock_sandbox: AsyncMock) -> None:
        # The node "no eslint config" skip moved INTO the lint_cmd (registry self-guard) — gates.py no
        # longer special-cases "node" host-side, so the gate always restores then runs the command, which
        # itself exits 0 when no config is present.
        mock_sandbox.side_effect = [(0, "restored", ""), (0, "no eslint config at repo root — lint gate no-op pass", "")]
        node_lint = SUPPORTED_ENVIRONMENTS["node-20-web"]["lint_cmd"]
        ok, log_lines = await run_lint_gate(environment_id="node-20-web", repo_root=_REPO)
        self.assertTrue(ok)
        self.assertEqual(mock_sandbox.await_args_list[-1], call("node-20-web", node_lint, _REPO, network="none"))

    def test_node_lint_cmd_self_guards_for_missing_eslint_config(self) -> None:
        # The eslint-config precondition lives in the REGISTRY command, not gates.py — the engine carries
        # no language. Verify the guard tokens + the safe exit-0 fallback are in the command itself.
        node_lint = SUPPORTED_ENVIRONMENTS["node-20-web"]["lint_cmd"]
        self.assertIn("eslint.config.js", node_lint)
        self.assertIn("eslintConfig", node_lint)
        self.assertIn("npx --no-install eslint .", node_lint)
        self.assertIn("no eslint config", node_lint)


class ClassifyLintFindingsTests(unittest.TestCase):
    """`classify_lint_findings` buckets findings prod-vs-test (so prod → Developer, test → QA),
    handling both `path:line:col` output AND bare-path output (gofmt -l), statefully."""

    _GO = "go-1.23-cli"

    def test_python_splits_prod_and_test(self) -> None:
        lines = [
            "src/converter.py:10:5: F401 `os` imported but unused",
            "tests/test_converter.py:26:71: F841 Local variable `x` is unused",
            "Found 2 errors.",   # trailing summary inherits the last file's bucket (test)
        ]
        prod, test = classify_lint_findings(_ENV, lines)
        self.assertEqual(prod, ["src/converter.py:10:5: F401 `os` imported but unused"])
        self.assertIn("tests/test_converter.py:26:71: F841 Local variable `x` is unused", test)

    def test_gofmt_bare_path_is_classified(self) -> None:
        # gofmt -l prints ONLY the path (no :line:col) — Risk 2.
        prod, test = classify_lint_findings(self._GO, ["cmd/json2csv/main.go", "internal/conv/conv_test.go"])
        self.assertEqual(prod, ["cmd/json2csv/main.go"])
        self.assertEqual(test, ["internal/conv/conv_test.go"])

    def test_eslint_grouped_detail_lines_inherit_file_bucket(self) -> None:
        # eslint 'stylish': the path is a header line; indented detail lines have no path of their own.
        lines = [
            "src/app.ts:0:0",
            "  3:7  error  'x' is assigned a value but never used  no-unused-vars",
        ]
        prod, test = classify_lint_findings("node-20-web", lines)
        self.assertEqual(len(prod), 2)   # header + its detail line both bucketed to prod
        self.assertEqual(test, [])

    def test_preamble_before_any_file_is_dropped(self) -> None:
        prod, test = classify_lint_findings(_ENV, ["ruff 0.3.0", "checking 4 files"])
        self.assertEqual((prod, test), ([], []))

    def test_msbuild_paren_format_splits_prod_and_test(self) -> None:
        # MSBuild `path(line,col):` diagnostics must bucket like colon-style ones (the same seam that
        # routes .NET test-compile errors to QA also drives the lint prod/test split).
        lines = [
            "/workspace/src/JsonToCsv.Cli/Program.cs(12,9): warning CA1822: Mark as static",
            "/workspace/tests/JsonToCsv.Tests/ProgramTests.cs(8,1): warning IDE0005: Unnecessary using",
        ]
        prod, test = classify_lint_findings("dotnet-10-sdk", lines)
        self.assertEqual(len(prod), 1)
        self.assertEqual(len(test), 1)
        self.assertIn("Program.cs(12,9)", prod[0])
        self.assertIn("ProgramTests.cs(8,1)", test[0])


class FileRefRegexUnchangedTests(unittest.TestCase):
    """Pin: the shared compile-error regex matches BOTH the colon suffix (`path:line[:col]`) and the
    MSBuild parenthesis suffix (`path(line,col):`), but a bare path (no line/col) still does NOT match."""

    def test_requires_line_number(self) -> None:
        self.assertIsNotNone(_FILE_REF_RE.match("src/converter.py:10:5: F401 unused"))
        self.assertIsNone(_FILE_REF_RE.match("src/converter.py"))   # bare path is NOT a compile-error ref

    def test_matches_msbuild_paren_suffix(self) -> None:
        m = _FILE_REF_RE.match(
            "/workspace/tests/JsonToCsv.Tests/ProgramTests.cs(53,10): error CS0182: bad attribute"
        )
        self.assertIsNotNone(m)
        self.assertTrue(m.group(1).endswith("ProgramTests.cs"))


class LintToolingFailureTests(unittest.TestCase):
    """`lint_failure_is_tooling` flags a lint command that could not RUN (bad flag / unknown subcommand /
    missing binary) — an engine `lint_cmd` misconfig the agents cannot fix — so the runner fails fast with
    an environment incident instead of folding it into the budgeted cycle. A real finding is NOT flagged."""

    _ENV = "python-3.12-core"

    def test_ruff_format_bad_flag_is_tooling(self) -> None:
        # The exact failure observed: `ruff format` rejects `--extend-exclude` (only `ruff check` has it).
        lines = [
            "error: unexpected argument '--extend-exclude' found",
            "tip: to pass '--extend-exclude' as a value, use '-- --extend-exclude'",
            "Usage: ruff format --check [FILES]...",
        ]
        self.assertTrue(lint_failure_is_tooling(self._ENV, lines))

    def test_missing_binary_is_tooling(self) -> None:
        self.assertTrue(lint_failure_is_tooling(self._ENV, ["sh: 1: ruff: command not found"]))

    def test_unknown_flag_is_tooling(self) -> None:
        self.assertTrue(lint_failure_is_tooling("go-1.23-cli", ["flag provided but not defined: -foo", "Usage of vet:"]))

    def test_real_lint_finding_is_not_tooling(self) -> None:
        # A genuine style finding must ride the budgeted cycle, NOT be reclassified as an env fault.
        lines = [
            "src/converter.py:10:5: F401 `os` imported but unused",
            "Found 1 error.",
        ]
        self.assertFalse(lint_failure_is_tooling(self._ENV, lines))

    def test_msbuild_style_finding_is_not_tooling(self) -> None:
        self.assertFalse(lint_failure_is_tooling(
            "dotnet-10-sdk",
            ["/workspace/src/App/Program.cs(12,9): warning CA1822: Mark members as static"],
        ))


if __name__ == "__main__":
    unittest.main()
