"""Hermetic end-to-end pipeline test exercising REAL git + filesystem.

Unlike the unit suites (which mock ``asyncio.create_subprocess_exec`` and the whole agent
nodes), this drives the full orchestrator through the real
techlead/qa/developer/reviewer nodes so the genuine ``git`` binary, real file creation, and
OS-specific path/CRLF handling are all exercised — including the new git-anchored bootstrap,
which performs a **real shallow clone** of a programmatically-created source repo. Only the
model boundaries are mocked:

* Gemini  -> ``src.shared.utils.llm.instructor_client`` (structured output for techlead/qa/reviewer
  AND the per-skill ``SkillRelevance`` gate — every ``response_model`` must be handled or the call
  raises, ``with_api_retry`` swallows it after 2+4s backoff per attempt, and the run crawls)
* Claude  -> ``src.development.agents.developer.run_claude_cli`` (file mutation)
* docker gates -> ``run_build_gate`` / ``run_qa_unit_tests`` / ``run_security_scan`` / ``run_lint_gate``
  (and the ``run_format_pass`` autofix) are all stubbed (docker cannot be assumed portable in a hermetic test)

``reconfigure_logging`` is stubbed so the per-session log handler never pins an open file inside the
auto-cleaned temp tree.
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

# orchestrator imports src.shared.core.config at import time, which builds the genai client.
os.environ.setdefault("GEMINI_API_KEY", "test-key")

from src.nexus import runner as orchestrator
from src.shared.core.models import (
    TechLeadContract,
    QATestSuite,
    ReviewReport,
    DocumentationUpdate,
    SkillRelevance,
)

# Deterministic production code the (mocked) Claude developer "writes", and a trivial but
# valid unittest the (mocked) Gemini QA agent "generates". Both are written to disk for real.
_PROD_CODE = "def add(a: int, b: int) -> int:\n    return a + b\n"
_TEST_IMPORTS = "import unittest"
_TEST_CODE = (
    "class CalculatorTests(unittest.TestCase):\n"
    "    def test_add(self) -> None:\n"
    "        self.assertEqual(2, 2)\n"
)
_ADR_DOC = (
    "# Architecture State\n\n"
    "## Components\n- add(a, b) -> int\n\n"
    "## Invariants\n- Pure function; operands must be int.\n"
)


def _fake_structured_llm(*, model, response_model, messages):
    """Stand-in for instructor's create_with_completion: returns (instance, raw) per role."""
    raw = SimpleNamespace(usage_metadata=None)
    if response_model is TechLeadContract:
        return (
            TechLeadContract(
                files_to_modify=["src/calculator.py"],
                topology_contract=[
                    {"file_path": "src/calculator.py", "exports": ["add"], "depends_on": []}
                ],
                instruction="Implement add(a, b).",
                function_signatures="def add(a: int, b: int) -> int",
                strict_type_validation_rules="Operands must be int.",
                techlead_reasoning="Trivial pure function.",
                environment_id="python-3.12-core",
            ),
            raw,
        )
    if response_model is QATestSuite:
        return QATestSuite(new_imports=_TEST_IMPORTS, new_test_code=_TEST_CODE), raw
    if response_model is ReviewReport:
        return (
            ReviewReport(
                code_quality_analysis="ok",
                test_integrity_analysis="ok",
                log_verification_analysis="ok",
                code_quality_approved=True,
                test_integrity_approved=True,
                dev_diagnostic_payload="",
            ),
            raw,
        )
    if response_model is DocumentationUpdate:
        return DocumentationUpdate(
            architecture_document=_ADR_DOC,
            readme="# Calculator\n\nAdds two integers.\n",
            changelog="# Changelog\n\n## [Unreleased]\n### Added\n- add(a, b).\n",
        ), raw
    if response_model is SkillRelevance:
        # Per-node/per-skill relevance gate (prompts.py: score > 0.7 ⇒ inject). 0.0 keeps every
        # domain skill OUT of the hermetic run. WITHOUT this branch the call raises, with_api_retry
        # swallows it after 3 attempts of 2+4s backoff, and ~20 such gated calls add ~120s — the
        # entire reason this e2e took ~125s instead of ~2s.
        return SkillRelevance(score=0.0), raw
    raise AssertionError(f"Unexpected response_model: {response_model!r}")


async def _fake_claude_cli(prompt, files, allowed_root, model=None, effort=None, timeout=None, idle_timeout=None):
    """Stand-in for the Claude CLI developer: writes real production code to each target.

    Returns the ``(returncode, usage)`` tuple shape of the real ``run_claude_cli``; the usage
    dict mirrors a parsed ``--output-format json`` envelope so telemetry recording is exercised.
    """
    for f in files:
        # The real Claude CLI creates any missing parent dirs as it writes; mirror that here (the
        # workspace no longer pre-creates a src/ tree — layout is contract-driven).
        Path(f).parent.mkdir(parents=True, exist_ok=True)
        Path(f).write_text(_PROD_CODE, encoding="utf-8")
    return 0, {
        "input_tokens": 100,
        "cache_write_tokens": 5000,
        "cache_read_tokens": 80000,
        "output_tokens": 20,
        "cost_usd": 0.001,
    }


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
                    ),
                ),
                mock.patch("src.shared.utils.llm.instructor_client", client),
                mock.patch(
                    "src.development.agents.developer.run_claude_cli",
                    new=AsyncMock(side_effect=_fake_claude_cli),
                ),
                mock.patch.object(
                    orchestrator,
                    "run_build_gate",
                    new=AsyncMock(return_value=(True, [])),
                ),
                mock.patch.object(
                    orchestrator,
                    "run_qa_unit_tests",
                    new=AsyncMock(return_value=(True, [])),
                ),
                mock.patch.object(
                    orchestrator,
                    "run_security_scan",
                    new=AsyncMock(return_value=(True, [])),
                ),
                mock.patch.object(
                    orchestrator,
                    "run_lint_gate",
                    new=AsyncMock(return_value=(True, [])),
                ),
                mock.patch.object(
                    orchestrator,
                    "run_format_pass",
                    new=AsyncMock(return_value=None),
                ),
            ):
                # Act — real bootstrap (shallow clone + feature branch) + real agents. The sandboxed
                # QA/SAST Docker gates are stubbed (no docker dependency in the hermetic test).
                await orchestrator.main()

            # Assert — exactly one session was bootstrapped with a real clone. New layout groups runs
            # under a project slug: runs/<slug>/NNN_exec_<ticket>_<ts>_<uid>/repo.
            repos = list(runs_base.glob("*/*_exec_*/repo"))
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
            test_file = repo_dir / "tests" / "test_src_calculator.py"
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
            self.assertNotIn("tests/test_src_calculator.py", prod)
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

            # Assert — the Technical Writer wrote the living ADR and it was committed atomically
            # (staged before finalize_transaction, so it rides the same single success commit).
            adr_file = repo_dir / "docs" / "architecture_state.md"
            self.assertTrue(adr_file.is_file(), "techwriter did not write the ADR")
            self.assertIn("Architecture State", adr_file.read_text(encoding="utf-8"))
            tracked = subprocess.run(
                ["git", "-C", str(repo_dir), "ls-files", "docs/architecture_state.md"],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            self.assertEqual(tracked, "docs/architecture_state.md")

            # Assert — the Technical Writer also owns README.md, the root CHANGELOG.md, and LICENSE.
            # README/CHANGELOG are LLM-authored (the fake response above); LICENSE is the engine's
            # deterministic Apache 2.0 text (no LLM field). All ride the same atomic success commit.
            self.assertIn("Calculator", (repo_dir / "README.md").read_text(encoding="utf-8"))
            self.assertIn("Changelog", (repo_dir / "CHANGELOG.md").read_text(encoding="utf-8"))
            self.assertIn("Apache License", (repo_dir / "LICENSE").read_text(encoding="utf-8"))
            tracked_docs = subprocess.run(
                ["git", "-C", str(repo_dir), "ls-files", "README.md", "CHANGELOG.md", "LICENSE"],
                capture_output=True, text=True, check=True,
            ).stdout.split()
            self.assertEqual(sorted(tracked_docs), ["CHANGELOG.md", "LICENSE", "README.md"])


if __name__ == "__main__":
    unittest.main()
