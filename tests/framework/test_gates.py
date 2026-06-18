"""Unit tests for the runtime validation gates.

Docker is never invoked: ``execute_in_sandbox`` / ``run_in_image`` are mocked so the registry-sourced
commands, the network phasing, and the adapter's ``(returncode, stdout, stderr)`` contract can be
inspected deterministically.
"""
import unittest
from unittest import mock
from unittest.mock import AsyncMock, call

from src.executor.nodes.gates import (
    run_qa_unit_tests, run_security_scan, run_build_gate, run_format_pass, run_test_compile_gate,
    build_failure_is_test_only, build_failure_is_environmental, _has_test_files,
)
from src.shared.core.environments import SUPPORTED_ENVIRONMENTS, SAST_IMAGE, SAST_CMD

_ENV = "python-3.12-core"
_REPO = "/abs/repo/root"
_SETUP = SUPPORTED_ENVIRONMENTS[_ENV]["setup_cmd"]
_TEST = SUPPORTED_ENVIRONMENTS[_ENV]["test_cmd"]
_BUILD = SUPPORTED_ENVIRONMENTS[_ENV]["build_cmd"]
_TCOMPILE = SUPPORTED_ENVIRONMENTS[_ENV]["test_compile_cmd"]


class RunQaUnitTestsTests(unittest.IsolatedAsyncioTestCase):
    """The QA gate restores deps (network ON) then runs the registry test_cmd (network OFF).

    The empty-suite guard (`_has_test_files`) is forced True here so these cases exercise the
    restore/test phasing; the no-test no-op pass is covered by EmptySuiteGateTests below."""

    @mock.patch("src.executor.nodes.gates._has_test_files", return_value=True)
    @mock.patch("src.executor.nodes.gates.execute_in_sandbox", new_callable=AsyncMock)
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

    @mock.patch("src.executor.nodes.gates._has_test_files", return_value=True)
    @mock.patch("src.executor.nodes.gates.execute_in_sandbox", new_callable=AsyncMock)
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

    @mock.patch("src.executor.nodes.gates._has_test_files", return_value=True)
    @mock.patch("src.executor.nodes.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_restore_failure_short_circuits_before_tests(self, mock_sandbox: AsyncMock, _has: mock.Mock) -> None:
        mock_sandbox.return_value = (1, "could not resolve deps", "")

        ok, log_lines = await run_qa_unit_tests(environment_id=_ENV, repo_root=_REPO)

        self.assertFalse(ok)
        mock_sandbox.assert_awaited_once_with(_ENV, _SETUP, _REPO, network="bridge", cache_writable=True)  # tests never reached
        self.assertIn("🚨 Dependency restore failed:", log_lines[0])

    @mock.patch("src.executor.nodes.gates._has_test_files", return_value=True)
    @mock.patch("src.executor.nodes.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_nonzero_test_exit_reports_failure(self, mock_sandbox: AsyncMock, _has: mock.Mock) -> None:
        mock_sandbox.side_effect = [(0, "", ""), (1, "out line", "err line")]

        ok, log_lines = await run_qa_unit_tests(environment_id=_ENV, repo_root=_REPO)

        self.assertFalse(ok)
        self.assertEqual(log_lines, ["out line", "err line"])


class RunFormatPassTests(unittest.IsolatedAsyncioTestCase):
    """The post-QA format pass runs the env's optional format_cmd (network OFF) and is strictly
    non-fatal: a missing key no-ops, and a non-zero exit or sandbox error is swallowed."""

    _GO = "go-1.23-cli"
    _GO_FMT = SUPPORTED_ENVIRONMENTS[_GO]["format_cmd"]

    @mock.patch("src.executor.nodes.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_runs_format_cmd_network_off(self, mock_sandbox: AsyncMock) -> None:
        mock_sandbox.return_value = (0, "", "")
        await run_format_pass(self._GO, _REPO)
        mock_sandbox.assert_awaited_once_with(self._GO, self._GO_FMT, _REPO, network="none")

    @mock.patch("src.executor.nodes.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_noop_when_no_format_cmd(self, mock_sandbox: AsyncMock) -> None:
        # Build a throwaway env spec with no format_cmd; the pass must not touch the sandbox.
        env_id = "no-fmt-env"
        with mock.patch.dict(SUPPORTED_ENVIRONMENTS, {env_id: {"image": "x"}}, clear=False):
            await run_format_pass(env_id, _REPO)
        mock_sandbox.assert_not_awaited()

    @mock.patch("src.executor.nodes.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_nonzero_exit_is_non_fatal(self, mock_sandbox: AsyncMock) -> None:
        mock_sandbox.return_value = (1, "", "goimports: boom")
        # Must NOT raise — a formatter hiccup never derails the pipeline.
        await run_format_pass(self._GO, _REPO)
        mock_sandbox.assert_awaited_once()

    @mock.patch("src.executor.nodes.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_sandbox_exception_is_swallowed(self, mock_sandbox: AsyncMock) -> None:
        mock_sandbox.side_effect = RuntimeError("docker unavailable")
        await run_format_pass(self._GO, _REPO)  # no raise


class EmptySuiteGateTests(unittest.IsolatedAsyncioTestCase):
    """An empty test suite (no test files) is a no-op PASS — never a fictitious functional failure
    from a runner that exits non-zero on "no tests collected" (pytest 5, jest 1)."""

    @mock.patch("src.executor.nodes.gates._has_test_files", return_value=False)
    @mock.patch("src.executor.nodes.gates.execute_in_sandbox", new_callable=AsyncMock)
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

    @mock.patch("src.executor.nodes.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_restore_then_build_with_network_phasing(self, mock_sandbox: AsyncMock) -> None:
        mock_sandbox.side_effect = [(0, "restored", ""), (0, "build ok", "")]

        ok, log_lines = await run_build_gate(environment_id=_ENV, repo_root=_REPO)

        self.assertTrue(ok)
        self.assertEqual(mock_sandbox.await_args_list, [
            call(_ENV, _SETUP, _REPO, network="bridge", cache_writable=True),
            call(_ENV, _BUILD, _REPO, network="none"),
        ])

    @mock.patch("src.executor.nodes.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_nonzero_build_exit_reports_failure(self, mock_sandbox: AsyncMock) -> None:
        mock_sandbox.side_effect = [(0, "", ""), (1, "undefined: Foo", "")]

        ok, log_lines = await run_build_gate(environment_id=_ENV, repo_root=_REPO)

        self.assertFalse(ok)
        self.assertIn("undefined: Foo", log_lines)

    @mock.patch("src.executor.nodes.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_restore_failure_short_circuits_before_build(self, mock_sandbox: AsyncMock) -> None:
        mock_sandbox.return_value = (1, "deps error", "")

        ok, log_lines = await run_build_gate(environment_id=_ENV, repo_root=_REPO)

        self.assertFalse(ok)
        mock_sandbox.assert_awaited_once_with(_ENV, _SETUP, _REPO, network="bridge", cache_writable=True)  # build never reached


class RunTestCompileGateTests(unittest.IsolatedAsyncioTestCase):
    """The pre-Reviewer QA test-compile gate: restore (network ON) → compile-only tests (network OFF),
    with no-op passes when there's no `test_compile_cmd` or no test files."""

    @mock.patch("src.executor.nodes.gates._has_test_files", return_value=True)
    @mock.patch("src.executor.nodes.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_restore_then_compile_with_network_phasing(self, mock_sandbox: AsyncMock, _has: mock.Mock) -> None:
        mock_sandbox.side_effect = [(0, "restored", ""), (0, "collected 3 items", "")]

        ok, log_lines = await run_test_compile_gate(environment_id=_ENV, repo_root=_REPO)

        self.assertTrue(ok)
        self.assertEqual(mock_sandbox.await_args_list, [
            call(_ENV, _SETUP, _REPO, network="bridge", cache_writable=True),
            call(_ENV, _TCOMPILE, _REPO, network="none"),
        ])

    @mock.patch("src.executor.nodes.gates._has_test_files", return_value=True)
    @mock.patch("src.executor.nodes.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_compile_failure_reports_lines(self, mock_sandbox: AsyncMock, _has: mock.Mock) -> None:
        mock_sandbox.side_effect = [(0, "", ""), (1, "", "test_x.py:2: ImportError: no module")]

        ok, log_lines = await run_test_compile_gate(environment_id=_ENV, repo_root=_REPO)

        self.assertFalse(ok)
        self.assertIn("test_x.py:2: ImportError: no module", log_lines)

    @mock.patch("src.executor.nodes.gates._has_test_files", return_value=False)
    @mock.patch("src.executor.nodes.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_noop_when_no_test_files(self, mock_sandbox: AsyncMock, _has: mock.Mock) -> None:
        ok, log_lines = await run_test_compile_gate(environment_id=_ENV, repo_root=_REPO)
        self.assertTrue(ok)
        mock_sandbox.assert_not_awaited()

    @mock.patch("src.executor.nodes.gates._has_test_files", return_value=True)
    @mock.patch("src.executor.nodes.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_noop_when_env_has_no_test_compile_cmd(self, mock_sandbox: AsyncMock, _has: mock.Mock) -> None:
        env_id = "no-tc-env"
        with mock.patch.dict(SUPPORTED_ENVIRONMENTS, {env_id: {"image": "x"}}, clear=False):
            ok, log_lines = await run_test_compile_gate(environment_id=env_id, repo_root=_REPO)
        self.assertTrue(ok)
        mock_sandbox.assert_not_awaited()


class RunSecurityScanTests(unittest.IsolatedAsyncioTestCase):
    """The SAST gate runs the GENERIC Semgrep image (not the language image) over the repo."""

    @mock.patch("src.executor.nodes.gates.run_in_image", new_callable=AsyncMock)
    async def test_runs_generic_semgrep_image_offline(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = (1, "findings", "")

        ok, log_lines = await run_security_scan(environment_id=_ENV, repo_root=_REPO)

        self.assertFalse(ok)
        # Vendored-rules image → fully offline (no semgrep.dev call behind the corporate proxy).
        mock_run.assert_awaited_once_with(SAST_IMAGE, SAST_CMD, _REPO, network="none")
        self.assertEqual(log_lines, ["findings"])

    @mock.patch("src.executor.nodes.gates.run_in_image", new_callable=AsyncMock)
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

    def test_restore_failed_banner_is_environmental(self) -> None:
        # The gates' own restore-phase failure banner must be recognised.
        self.assertTrue(build_failure_is_environmental(self._DOTNET, ["🚨 Dependency restore failed:", "some output"]))

    def test_real_compiler_error_is_not_environmental(self) -> None:
        # A genuine code defect must fall through to the normal compile-gate reroute.
        self.assertFalse(build_failure_is_environmental(self._DOTNET, ["Program.cs(12,9): error CS0103: The name 'Foo' does not exist"]))
        self.assertFalse(build_failure_is_environmental("go-1.23-cli", ["internal/converter/processor.go:10:2: undefined: Foo"]))


if __name__ == "__main__":
    unittest.main()
