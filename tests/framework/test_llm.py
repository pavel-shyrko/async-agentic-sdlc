"""Unit tests for run_structured_llm's RECITATION recovery: a deterministic recitation block triggers
ONE paraphrase-guarded retry (following the finish-reason hint), while any other error propagates."""
import os
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("GEMINI_API_KEY", "test-key")  # config builds the genai client at import

from src.shared.utils import llm
from src.shared.utils import api_retry
from src.shared.utils.llm import run_structured_llm, RECITATION_GUARD


class _RecitationError(Exception):
    """Stand-in for instructor's InstructorRetryException carrying a RECITATION completion."""
    def __init__(self) -> None:
        super().__init__("validation failed")
        self.last_completion = SimpleNamespace(
            candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name="RECITATION"))]
        )


def _fake_client(create_fn) -> SimpleNamespace:
    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create_with_completion=create_fn))
    )


class RunStructuredLlmRecitationTests(unittest.IsolatedAsyncioTestCase):
    async def test_recitation_triggers_one_guarded_retry_then_succeeds(self) -> None:
        calls: list[list[dict]] = []
        parsed, raw = SimpleNamespace(ok=True), SimpleNamespace()

        def _create(model, response_model, messages):
            calls.append(messages)
            if len(calls) == 1:
                raise _RecitationError()        # first call blocked
            return (parsed, raw)                # guarded retry succeeds

        with mock.patch.object(llm, "instructor_client", _fake_client(_create)):
            result = await run_structured_llm("tpm", object, [{"role": "user", "content": "hi"}])

        self.assertEqual(result, (parsed, raw))
        self.assertEqual(len(calls), 2)                                   # original + ONE guarded retry
        self.assertNotIn(RECITATION_GUARD, [m["content"] for m in calls[0]])
        self.assertIn(RECITATION_GUARD, [m["content"] for m in calls[1]])  # guard appended on retry

    async def test_second_recitation_propagates(self) -> None:
        calls: list[list[dict]] = []

        def _create(model, response_model, messages):
            calls.append(messages)
            raise _RecitationError()            # blocked every time

        with mock.patch.object(llm, "instructor_client", _fake_client(_create)):
            with self.assertRaises(_RecitationError):
                await run_structured_llm("tpm", object, [{"role": "user", "content": "hi"}])

        self.assertEqual(len(calls), 2)         # one guarded retry, then give up (no infinite loop)

    async def test_non_recitation_error_does_not_get_guarded_retry(self) -> None:
        calls: list[list[dict]] = []

        def _create(model, response_model, messages):
            calls.append(messages)
            raise ValueError("network blip")

        # with_api_retry exhausts its 3 attempts on a transient error; no extra guarded call is made.
        with mock.patch.object(api_retry.asyncio, "sleep", new=mock.AsyncMock()), \
                mock.patch.object(llm, "instructor_client", _fake_client(_create)):
            with self.assertRaises(ValueError):
                await run_structured_llm("tpm", object, [{"role": "user", "content": "hi"}])

        self.assertEqual(len(calls), 3)         # 3 retry attempts, none carrying the guard
        for sent in calls:
            self.assertNotIn(RECITATION_GUARD, [m["content"] for m in sent])


if __name__ == "__main__":
    unittest.main()
