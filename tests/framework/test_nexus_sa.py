"""Unit tests for the Solution Architect runner — specifically that an explicitly user-mandated stack
in the raw idea reaches the SA (the Epic is language-neutral and would otherwise drop it)."""
import os
import unittest
from types import SimpleNamespace
from unittest import mock
from unittest.mock import AsyncMock

os.environ.setdefault("GEMINI_API_KEY", "test-key")

from src.nexus import sa as sa_mod
from src.nexus.sa import run_sa, Blueprint
from src.shared.core.models import PipelineTelemetry


def _result() -> Blueprint:
    return Blueprint(environment_id="python-3.12-core", markdown="# Blueprint")


class RunSaRawIdeaTests(unittest.IsolatedAsyncioTestCase):

    async def test_raw_idea_is_forwarded_verbatim_to_the_architect(self) -> None:
        with mock.patch.object(
            sa_mod, "run_structured_llm", new=AsyncMock(return_value=(_result(), None))
        ) as mocked:
            await run_sa("EPIC: convert json to csv", raw_idea="Напиши CLI-утилиту на Python")

        user_content = mocked.await_args.args[2][1]["content"]
        self.assertIn("ORIGINAL USER REQUEST", user_content)
        self.assertIn("на Python", user_content)          # the mandated stack survives to the SA
        self.assertIn("EPIC: convert json to csv", user_content)

    async def test_no_raw_idea_passes_epic_alone(self) -> None:
        with mock.patch.object(
            sa_mod, "run_structured_llm", new=AsyncMock(return_value=(_result(), None))
        ) as mocked:
            await run_sa("EPIC ONLY")

        user_content = mocked.await_args.args[2][1]["content"]
        self.assertEqual(user_content, "EPIC ONLY")        # backward-compatible: no wrapper when absent

    async def test_token_usage_recorded_into_passed_telemetry(self) -> None:
        # Executor-parity observability: when a telemetry object is threaded in, the agent records
        # its Gemini token usage into it (the data behind the [TOKENS] line + FinOps total).
        raw = SimpleNamespace(usage_metadata=SimpleNamespace(
            prompt_token_count=1000, candidates_token_count=200,
            cached_content_token_count=0, prompt_tokens_details=None,
        ))
        telemetry = PipelineTelemetry()
        with mock.patch.object(
            sa_mod, "run_structured_llm", new=AsyncMock(return_value=(_result(), raw))
        ):
            await run_sa("EPIC ONLY", telemetry=telemetry)

        self.assertIn("Solution Architect Agent", telemetry.by_agent)
        self.assertEqual(telemetry.total_tokens, 1200)     # fresh 1000 + output 200


if __name__ == "__main__":
    unittest.main()
