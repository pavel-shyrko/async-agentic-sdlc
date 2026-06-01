"""Hermetic end-to-end pipeline test exercising REAL git + filesystem.

Unlike the unit suites (which mock ``asyncio.create_subprocess_exec`` and the whole agent
nodes), this drives the full orchestrator through the real
architect/qa/developer/reviewer nodes so the genuine ``git`` binary, real file creation, and
OS-specific path/CRLF handling are all exercised. Only the model boundaries are mocked:

* Gemini  -> ``src.utils.llm.instructor_client`` (structured output for architect/qa/reviewer)
* Claude  -> ``src.agents.developer.run_claude_cli`` (file mutation)
* docker QA gate -> ``orchestrator.run_qa_unit_tests`` (docker cannot be assumed portable)

The bandit SAST gate runs for real (pure-Python, portable).
"""
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock
from unittest.mock import AsyncMock

# orchestrator imports src.core.config at import time, which builds the genai client.
os.environ.setdefault("GEMINI_API_KEY", "test-key")

import orchestrator
from src.core.models import (
    ArchitectureContract,
    GlobalPipelineContext,
    QATestSuite,
    ReviewReport,
    WorkspacePaths,
)

# Deterministic production code the (mocked) Claude developer "writes", and a trivial but
# valid unittest the (mocked) Gemini QA agent "generates". Both are written to disk for real.
_PROD_CODE = "def add(a: int, b: int) -> int:\n    return a + b\n"
_TEST_CODE = (
    "import unittest\n\n"
    "class CalculatorTests(unittest.TestCase):\n"
    "    def test_add(self) -> None:\n"
    "        self.assertEqual(2, 2)\n"
)


def _fake_structured_llm(*, model, response_model, messages):
    """Stand-in for instructor's create_with_completion: returns (instance, raw) per role."""
    raw = SimpleNamespace(usage_metadata=None)
    if response_model is ArchitectureContract:
        return (
            ArchitectureContract(
                files_to_modify=["calculator.py"],
                instruction="Implement add(a, b).",
                function_signatures="def add(a: int, b: int) -> int",
                strict_type_validation_rules="Operands must be int.",
                architecture_reasoning="Trivial pure function.",
            ),
            raw,
        )
    if response_model is QATestSuite:
        return QATestSuite(test_code=_TEST_CODE), raw
    if response_model is ReviewReport:
        return (
            ReviewReport(
                code_quality_analysis="ok",
                test_integrity_analysis="ok",
                log_verification_analysis="ok",
                code_quality_approved=True,
                test_integrity_approved=True,
                diagnostic_payload="",
            ),
            raw,
        )
    raise AssertionError(f"Unexpected response_model: {response_model!r}")


async def _fake_claude_cli(prompt, files, allowed_root):
    """Stand-in for the Claude CLI developer: writes real production code to each target."""
    for f in files:
        Path(f).write_text(_PROD_CODE, encoding="utf-8")
    return 0


class PipelineEndToEndTests(unittest.IsolatedAsyncioTestCase):
    """Full pipeline over real git + real files, mocking only Gemini/Claude/docker."""

    def setUp(self) -> None:
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("git binary not available on PATH")

    async def test_full_pipeline_creates_real_files_and_commits(self) -> None:
        # Arrange — isolate the entire artifact tree under a temp dir.
        with TemporaryDirectory() as td:
            base = Path(td)
            paths = WorkspacePaths(
                code_dir=base / "code",
                tests_dir=base / "tests",
                logs_dir=base / "logs",
                reports_dir=base / "reports",
            )
            ctx = GlobalPipelineContext(
                pr_description="add two ints", base_branch="main", workspace_paths=paths
            )

            client = mock.MagicMock()
            client.chat.completions.create_with_completion.side_effect = _fake_structured_llm

            with (
                mock.patch.object(orchestrator, "check_environment"),
                mock.patch.object(
                    orchestrator,
                    "parse_args",
                    return_value=("add two ints", "main", None, False),
                ),
                mock.patch.object(
                    orchestrator, "GlobalPipelineContext", wraps=GlobalPipelineContext
                ) as wrapped_ctx_cls,
                mock.patch("src.utils.llm.instructor_client", client),
                mock.patch(
                    "src.agents.developer.run_claude_cli",
                    new=AsyncMock(side_effect=_fake_claude_cli),
                ),
                mock.patch.object(
                    orchestrator,
                    "run_qa_unit_tests",
                    new=AsyncMock(return_value=(True, [])),
                ),
            ):
                wrapped_ctx_cls.return_value = ctx

                # Act — real architect/qa/developer/reviewer nodes + real git + real bandit.
                await orchestrator.main()

            # Assert — real files were created on disk.
            code_file = paths.code_dir / "calculator.py"
            test_file = paths.tests_dir / "test_calculator.py"
            self.assertTrue(code_file.is_file(), "developer did not write production code")
            self.assertEqual(code_file.read_text(encoding="utf-8"), _PROD_CODE)
            self.assertTrue(test_file.is_file(), "QA did not write the test file")
            self.assertIn("CalculatorTests", test_file.read_text(encoding="utf-8"))

            # Assert — real sandbox git repos were initialised and hold a real commit.
            self.assertTrue((paths.code_dir / ".git").is_dir())
            self.assertTrue((paths.tests_dir / ".git").is_dir())
            commit_count = subprocess.run(
                ["git", "-C", str(paths.code_dir), "rev-list", "--count", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            self.assertGreaterEqual(int(commit_count), 1)

            # Assert — the real git-diff snapshot path captured both artifacts. This is where
            # path-separator ("\\" vs "/") and CRLF/LF discrepancies would surface.
            self.assertIn("=== FILE: calculator.py ===", ctx.production_code_snapshot)
            self.assertIn("def add", ctx.production_code_snapshot)
            self.assertIn("CalculatorTests", ctx.test_code_snapshot)


if __name__ == "__main__":
    unittest.main()
