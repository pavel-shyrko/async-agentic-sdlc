"""Unit tests for the shared LLM retry decorator's failure DIAGNOSTICS — the fix for the opaque
RECITATION crash: the cause (genai finish_reason) must appear in the retry/CRITICAL log lines."""
import unittest
from types import SimpleNamespace
from unittest import mock

from src.shared.utils import api_retry
from src.shared.utils.api_retry import with_api_retry


class _RecitationError(Exception):
    """Stand-in for instructor's InstructorRetryException carrying the raw genai completion."""
    def __init__(self) -> None:
        super().__init__("validation failed")
        self.last_completion = SimpleNamespace(
            candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name="RECITATION"))]
        )


class ApiRetryDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_critical_log_names_the_finish_reason(self) -> None:
        @with_api_retry(max_retries=1, agent_name="TPM Agent")  # 1 attempt → fails fast, no sleep
        async def _always_recitation() -> None:
            raise _RecitationError()

        with mock.patch.object(api_retry, "log") as mock_log:
            with self.assertRaises(_RecitationError):
                await _always_recitation()

        # The terminal CRITICAL line must carry the diagnosed cause, not just a generic count.
        msg = mock_log.error.call_args.args[0]
        self.assertIn("TPM Agent", msg)
        self.assertIn("RECITATION", msg)

    async def test_falls_back_to_exception_type_when_no_finish_reason(self) -> None:
        @with_api_retry(max_retries=1, agent_name="PO Agent")
        async def _boom() -> None:
            raise ValueError("network blip")

        with mock.patch.object(api_retry, "log") as mock_log:
            with self.assertRaises(ValueError):
                await _boom()

        self.assertIn("ValueError", mock_log.error.call_args.args[0])

    async def test_recitation_fails_fast_without_burning_retries(self) -> None:
        # A content-filter block is DETERMINISTIC — even with retries left it must fail after one
        # attempt (no backoff sleep), not exhaust the budget on identical re-tries.
        calls = 0

        @with_api_retry(max_retries=3, agent_name="TPM Agent")
        async def _always_recitation() -> None:
            nonlocal calls
            calls += 1
            raise _RecitationError()

        with mock.patch.object(api_retry.asyncio, "sleep") as mock_sleep, \
                mock.patch.object(api_retry, "log") as mock_log:
            with self.assertRaises(_RecitationError):
                await _always_recitation()

        self.assertEqual(calls, 1)                 # one attempt only — no retry
        mock_sleep.assert_not_awaited()            # no backoff burned
        self.assertIn("non-retryable", mock_log.error.call_args.args[0])

    async def test_transient_error_retries_up_to_max(self) -> None:
        # A plain (non-content-filter) error still retries the full budget with backoff.
        calls = 0

        @with_api_retry(max_retries=3, agent_name="QA Agent")
        async def _flaky() -> None:
            nonlocal calls
            calls += 1
            raise ValueError("blip")

        with mock.patch.object(api_retry.asyncio, "sleep", new=mock.AsyncMock()), \
                mock.patch.object(api_retry, "log"):
            with self.assertRaises(ValueError):
                await _flaky()

        self.assertEqual(calls, 3)                 # all attempts used


if __name__ == "__main__":
    unittest.main()
