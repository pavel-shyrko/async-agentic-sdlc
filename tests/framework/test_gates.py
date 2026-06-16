"""Unit tests for the runtime validation gates.

Docker is never invoked: ``execute_in_sandbox`` is mocked so the registry-sourced command and the
adapter's ``(returncode, stdout, stderr)`` contract can be inspected deterministically.
"""
import unittest
from unittest import mock
from unittest.mock import AsyncMock

from src.executor.nodes.gates import run_qa_unit_tests, run_security_scan
from src.shared.core.environments import SUPPORTED_ENVIRONMENTS

_ENV = "python-3.12-core"
_REPO = "/abs/repo/root"


class RunQaUnitTestsTests(unittest.IsolatedAsyncioTestCase):
    """The QA gate must run the registry ``test_cmd`` in the env's sandbox — no hardcoded runtime."""

    @mock.patch("src.executor.nodes.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_runs_registry_test_cmd_and_reports_success(self, mock_sandbox: AsyncMock) -> None:
        mock_sandbox.return_value = (0, "ran 3 tests", "")

        ok, log_lines = await run_qa_unit_tests(environment_id=_ENV, repo_root=_REPO)

        self.assertTrue(ok)
        mock_sandbox.assert_awaited_once_with(_ENV, SUPPORTED_ENVIRONMENTS[_ENV]["test_cmd"], _REPO)
        self.assertEqual(log_lines, ["ran 3 tests"])

    @mock.patch("src.executor.nodes.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_nonzero_exit_reports_failure_and_combines_streams(self, mock_sandbox: AsyncMock) -> None:
        mock_sandbox.return_value = (1, "out line", "err line")

        ok, log_lines = await run_qa_unit_tests(environment_id=_ENV, repo_root=_REPO)

        self.assertFalse(ok)
        self.assertEqual(log_lines, ["out line", "err line"])


class RunSecurityScanTests(unittest.IsolatedAsyncioTestCase):
    """The SAST gate must run the registry ``sast_cmd`` and inject a pass message on silent success."""

    @mock.patch("src.executor.nodes.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_runs_registry_sast_cmd(self, mock_sandbox: AsyncMock) -> None:
        mock_sandbox.return_value = (1, "issue found", "")

        ok, log_lines = await run_security_scan(environment_id=_ENV, repo_root=_REPO)

        self.assertFalse(ok)
        mock_sandbox.assert_awaited_once_with(_ENV, SUPPORTED_ENVIRONMENTS[_ENV]["sast_cmd"], _REPO)
        self.assertEqual(log_lines, ["issue found"])

    @mock.patch("src.executor.nodes.gates.execute_in_sandbox", new_callable=AsyncMock)
    async def test_silent_success_injects_pass_message(self, mock_sandbox: AsyncMock) -> None:
        mock_sandbox.return_value = (0, "", "")

        ok, log_lines = await run_security_scan(environment_id=_ENV, repo_root=_REPO)

        self.assertTrue(ok)
        self.assertEqual(log_lines, ["SAST execution passed. Zero vulnerabilities identified."])


if __name__ == "__main__":
    unittest.main()
