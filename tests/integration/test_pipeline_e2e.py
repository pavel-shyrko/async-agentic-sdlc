"""Hermetic end-to-end pipeline test exercising REAL git + filesystem.

Unlike the unit suites (which mock ``asyncio.create_subprocess_exec`` and the whole agent
nodes), this drives the full orchestrator through the real
architect/qa/developer/reviewer nodes so the genuine ``git`` binary, real file creation, and
OS-specific path/CRLF handling are all exercised — including the new git-anchored bootstrap,
which performs a **real shallow clone** of a programmatically-created source repo. Only the
model boundaries are mocked:

* Gemini  -> ``src.utils.llm.instructor_client`` (structured output for architect/qa/reviewer)
* Claude  -> ``src.agents.developer.run_claude_cli`` (file mutation)
* docker QA gate -> ``orchestrator.run_qa_unit_tests`` (docker cannot be assumed portable)

The bandit SAST gate runs for real (pure-Python, portable). ``reconfigure_logging`` is stubbed
so the per-session log handler never pins an open file inside the auto-cleaned temp tree.
"""
import os
import json
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
    QATestSuite,
    ReviewReport,
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


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


class PipelineEndToEndTests(unittest.IsolatedAsyncioTestCase):
    """Full pipeline over a REAL shallow clone, mocking only Gemini/Claude/docker."""

    def setUp(self) -> None:
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("git binary not available on PATH")

    def _seed_source_repo(self, root: Path) -> Path:
        """Builds a real git repo with a single commit so ``clone --depth 1`` has a HEAD."""
        source = root / "source"
        source.mkdir()
        _git(["init"], source)
        _git(["config", "user.email", "seed@sdlc.local"], source)
        _git(["config", "user.name", "Seed"], source)
        (source / "README.md").write_text("seed\n", encoding="utf-8")
        _git(["add", "."], source)
        _git(["commit", "-m", "seed commit"], source)
        # Normalise the default branch to 'main' so ctx.base_branch="main" resolves in the clone.
        _git(["branch", "-M", "main"], source)
        return source

    async def test_full_pipeline_clones_creates_real_files_and_commits(self) -> None:
        # Arrange — isolate both the source repo and the run tree under a temp dir.
        with TemporaryDirectory() as td:
            base = Path(td)
            source = self._seed_source_repo(base)
            runs_base = base / "runs"

            client = mock.MagicMock()
            client.chat.completions.create_with_completion.side_effect = _fake_structured_llm

            with (
                mock.patch.object(orchestrator, "check_environment"),
                mock.patch.object(orchestrator, "RUNS_BASE", runs_base),
                # Avoid pinning an open audit-log file inside the auto-cleaned temp tree.
                mock.patch.object(orchestrator, "reconfigure_logging"),
                mock.patch.object(
                    orchestrator,
                    "parse_args",
                    return_value=orchestrator.RunConfig(
                        description="add two ints", base_branch="main", resume=None,
                        reset_attempts=False, repo=str(source), ticket="DEMO-1",
                        src_dir="src/", tests_dir="tests/",
                    ),
                ),
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
                # Act — real bootstrap (shallow clone + feature branch) + real agents + real bandit.
                await orchestrator.main()

            # Assert — exactly one session was bootstrapped with a real clone.
            repos = list(runs_base.glob("run_*/repo"))
            self.assertEqual(len(repos), 1, "expected one cloned session repo")
            repo_dir = repos[0]
            run_dir = repo_dir.parent

            # Assert — the clone is on the feature branch.
            head = subprocess.run(
                ["git", "-C", str(repo_dir), "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            self.assertEqual(head, "feat/ticket-DEMO-1")

            # Assert — real files were created under the dynamic code/tests dirs inside the clone.
            code_file = repo_dir / "src" / "calculator.py"
            test_file = repo_dir / "tests" / "test_calculator.py"
            self.assertTrue(code_file.is_file(), "developer did not write production code")
            self.assertEqual(code_file.read_text(encoding="utf-8"), _PROD_CODE)
            self.assertTrue(test_file.is_file(), "QA did not write the test file")
            self.assertIn("CalculatorTests", test_file.read_text(encoding="utf-8"))

            # Assert — meta-state lives OUTSIDE the clone, and the real checkpoint captured the
            # git-diff snapshots (where path-separator / CRLF discrepancies would surface).
            self.assertFalse((repo_dir / "logs").exists())
            checkpoint = run_dir / "reports" / "checkpoint.json"
            self.assertTrue(checkpoint.is_file(), "checkpoint not written to run reports dir")
            data = json.loads(checkpoint.read_text(encoding="utf-8"))
            # production_code_snapshot is now a {repo-relative path: full content} dict built from the
            # real working tree; tests are excluded by the snapshot builder.
            prod = data["production_code_snapshot"]
            self.assertIn("src/calculator.py", prod)
            self.assertIn("def add", prod["src/calculator.py"])
            self.assertNotIn("tests/test_calculator.py", prod)
            self.assertIn("CalculatorTests", data["test_code_snapshot"])

            # Assert — the atomic success transaction produced exactly one commit on the feature
            # branch (seed + atomic) with the conventional subject. No push (hermetic).
            subject = subprocess.run(
                ["git", "-C", str(repo_dir), "log", "-1", "--pretty=%s"],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            self.assertEqual(subject, "feat(DEMO-1): add two ints")
            # Assert — the commit author identity was dynamically pinned from the ticket.
            author = subprocess.run(
                ["git", "-C", str(repo_dir), "log", "-1", "--pretty=%an"],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            self.assertEqual(author, "AI Agent (DEMO-1)")
            count = int(subprocess.run(
                ["git", "-C", str(repo_dir), "rev-list", "--count", "HEAD"],
                capture_output=True, text=True, check=True,
            ).stdout.strip())
            self.assertGreaterEqual(count, 2)


if __name__ == "__main__":
    unittest.main()
