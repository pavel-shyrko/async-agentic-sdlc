"""Unit tests for the runtime validation gates.

Docker is never invoked: ``execute_in_sandbox`` / ``run_in_image`` are mocked so the registry-sourced
commands, the network phasing, and the adapter's ``(returncode, stdout, stderr)`` contract can be
inspected deterministically.
"""
import unittest
from unittest import mock
from unittest.mock import AsyncMock, call

from src.executor.nodes.gates import run_qa_unit_tests, run_security_scan
from src.shared.core.environments import SUPPORTED_ENVIRONMENTS, SAST_IMAGE, SAST_CMD

_ENV = "python-3.12-core"
_REPO = "/abs/repo/root"
_SETUP = SUPPORTED_ENVIRONMENTS[_ENV]["setup_cmd"]
_TEST = SUPPORTED_ENVIRONMENTS[_ENV]["test_cmd"]


class RunQaUnitTestsTests(unittest.IsolatedAsyncioTestCase):
    """The QA gate restores deps (network ON) then runs the registry test_cmd (network OFF)."""

    @mock.patch("src.executor.nodes.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_restore_then_test_with_network_phasing(self, mock_sandbox: AsyncMock) -> None:
        mock_sandbox.side_effect = [(0, "restored", ""), (0, "ran 3 tests", "")]

        ok, log_lines = await run_qa_unit_tests(environment_id=_ENV, repo_root=_REPO)

        self.assertTrue(ok)
        # Restore runs first (network ON), then tests (network OFF).
        self.assertEqual(mock_sandbox.await_args_list, [
            call(_ENV, _SETUP, _REPO, network="bridge"),
            call(_ENV, _TEST, _REPO, network="none"),
        ])
        self.assertEqual(log_lines, ["restored", "ran 3 tests"])

    @mock.patch("src.executor.nodes.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_restore_failure_short_circuits_before_tests(self, mock_sandbox: AsyncMock) -> None:
        mock_sandbox.return_value = (1, "could not resolve deps", "")

        ok, log_lines = await run_qa_unit_tests(environment_id=_ENV, repo_root=_REPO)

        self.assertFalse(ok)
        mock_sandbox.assert_awaited_once_with(_ENV, _SETUP, _REPO, network="bridge")  # tests never reached
        self.assertIn("🚨 Dependency restore failed:", log_lines[0])

    @mock.patch("src.executor.nodes.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_nonzero_test_exit_reports_failure(self, mock_sandbox: AsyncMock) -> None:
        mock_sandbox.side_effect = [(0, "", ""), (1, "out line", "err line")]

        ok, log_lines = await run_qa_unit_tests(environment_id=_ENV, repo_root=_REPO)

        self.assertFalse(ok)
        self.assertEqual(log_lines, ["out line", "err line"])


class RunSecurityScanTests(unittest.IsolatedAsyncioTestCase):
    """The SAST gate runs the GENERIC Semgrep image (not the language image) over the repo."""

    @mock.patch("src.executor.nodes.gates.run_in_image", new_callable=AsyncMock)
    async def test_runs_generic_semgrep_image(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = (1, "findings", "")

        ok, log_lines = await run_security_scan(environment_id=_ENV, repo_root=_REPO)

        self.assertFalse(ok)
        mock_run.assert_awaited_once_with(SAST_IMAGE, SAST_CMD, _REPO, network="bridge")
        self.assertEqual(log_lines, ["findings"])

    @mock.patch("src.executor.nodes.gates.run_in_image", new_callable=AsyncMock)
    async def test_silent_success_injects_pass_message(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = (0, "", "")

        ok, log_lines = await run_security_scan(environment_id=_ENV, repo_root=_REPO)

        self.assertTrue(ok)
        self.assertEqual(log_lines, ["SAST execution passed. Zero vulnerabilities identified."])


if __name__ == "__main__":
    unittest.main()
