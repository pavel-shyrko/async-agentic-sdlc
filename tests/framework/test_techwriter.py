"""Unit tests for the Technical Writer node (living-ADR maintenance).

Hermetic: the LLM boundary and the `git add` subprocess are mocked, so the test exercises the
node's read/guard/write/stage logic against a real TemporaryDirectory without touching git or
the network.
"""
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock
from unittest.mock import AsyncMock

# techwriter imports src.shared.core.config at import time, which builds the genai client.
os.environ.setdefault("GEMINI_API_KEY", "test-key")

from src.executor.agents import techwriter
from src.shared.core.models import ArchitectureUpdate, GlobalPipelineContext, WorkspacePaths


class RunTechwriterNodeTests(unittest.IsolatedAsyncioTestCase):
    """The node updates docs/architecture_state.md and stages it for the atomic success commit."""

    @staticmethod
    def _ctx(repo: Path) -> GlobalPipelineContext:
        paths = WorkspacePaths(
            logs_dir=repo / "logs", reports_dir=repo / "reports", repo_dir=repo,
        )
        ctx = GlobalPipelineContext(pr_description="add streaming export", base_branch="main", workspace_paths=paths)
        ctx.production_code_snapshot = {"src/export.py": "def export():\n    ...\n"}
        return ctx

    async def test_writes_and_stages_updated_document(self) -> None:
        # Arrange
        with TemporaryDirectory() as td:
            repo = Path(td)
            ctx = self._ctx(repo)
            doc = "# Architecture State\n\n## Invariants\n- Streaming: row-by-row.\n"
            fake = (ArchitectureUpdate(updated_architecture_document=doc), SimpleNamespace(usage_metadata=None))
            with (
                mock.patch.object(techwriter, "run_structured_llm", new=AsyncMock(return_value=fake)) as llm,
                mock.patch.object(techwriter.subprocess, "run") as git_run,
            ):
                # Act
                await techwriter.run_techwriter_node(ctx)

            # Assert — document written verbatim to the canonical path...
            adr = repo / "docs" / "architecture_state.md"
            self.assertTrue(adr.is_file())
            self.assertEqual(adr.read_text(encoding="utf-8"), doc)
            # ...and staged so finalize_transaction's commit includes it.
            git_run.assert_called_once()
            self.assertEqual(git_run.call_args.args[0], ["git", "add", "docs/architecture_state.md"])
            self.assertEqual(git_run.call_args.kwargs["cwd"], str(repo))
            # ...against the techwriter role + ArchitectureUpdate schema.
            self.assertEqual(llm.call_args.args[0], "techwriter")
            self.assertIs(llm.call_args.args[1], ArchitectureUpdate)

    async def test_first_iteration_feeds_placeholder_without_filenotfound(self) -> None:
        # Arrange — no docs/ dir exists yet (the very first task).
        with TemporaryDirectory() as td:
            repo = Path(td)
            ctx = self._ctx(repo)
            captured: dict[str, str] = {}

            def _capture(role, response_model, messages):
                captured["user"] = messages[1]["content"]
                return ArchitectureUpdate(updated_architecture_document="# doc"), SimpleNamespace(usage_metadata=None)

            with (
                mock.patch.object(techwriter, "run_structured_llm", new=AsyncMock(side_effect=_capture)),
                mock.patch.object(techwriter.subprocess, "run"),
            ):
                # Act — must not raise FileNotFoundError.
                await techwriter.run_techwriter_node(ctx)

            # Assert — the previous-state section carried the first-iteration placeholder.
            self.assertIn("No architecture state documented yet", captured["user"])


if __name__ == "__main__":
    unittest.main()
