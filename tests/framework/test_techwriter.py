"""Unit tests for the Technical Writer node (human-facing documentation maintenance).

Hermetic: the LLM boundary and the `git add` subprocess are mocked, so the test exercises the
node's read/guard/write/stage logic against a real TemporaryDirectory without touching git or
the network. Covers the ADR + README + CHANGELOG (LLM-authored) and the deterministic LICENSE.
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

from src.development.agents import techwriter
from src.shared.core.models import DocumentationUpdate, GlobalPipelineContext, WorkspacePaths


def _fake_update(adr="# Architecture State\n", readme="# Proj\n", changelog="# Changelog\n", usage=""):
    doc = DocumentationUpdate(
        architecture_document=adr, readme=readme, changelog=changelog, usage_guide=usage,
    )
    return doc, SimpleNamespace(usage_metadata=None)


class RunTechwriterNodeTests(unittest.IsolatedAsyncioTestCase):
    """The node writes the docs set and stages it for the atomic success commit."""

    @staticmethod
    def _ctx(repo: Path) -> GlobalPipelineContext:
        paths = WorkspacePaths(
            logs_dir=repo / "logs", reports_dir=repo / "reports", repo_dir=repo,
        )
        ctx = GlobalPipelineContext(pr_description="add streaming export", base_branch="main", workspace_paths=paths)
        ctx.production_code_snapshot = {"src/export.py": "def export():\n    ...\n"}
        return ctx

    async def test_writes_and_stages_all_documents(self) -> None:
        with TemporaryDirectory() as td:
            repo = Path(td)
            ctx = self._ctx(repo)
            adr = "# Architecture State\n\n## Invariants\n- Streaming: row-by-row.\n"
            readme = "# Exporter\n\nStreams rows.\n"
            changelog = "# Changelog\n\n## [Unreleased]\n### Added\n- Export.\n"
            with (
                mock.patch.object(
                    techwriter, "run_structured_llm",
                    new=AsyncMock(return_value=_fake_update(adr, readme, changelog)),
                ) as llm,
                mock.patch.object(techwriter.subprocess, "run") as git_run,
            ):
                await techwriter.run_techwriter_node(ctx)

            # LLM-authored documents written verbatim to their canonical paths...
            self.assertEqual((repo / "docs" / "architecture_state.md").read_text(encoding="utf-8"), adr)
            self.assertEqual((repo / "README.md").read_text(encoding="utf-8"), readme)
            self.assertEqual((repo / "CHANGELOG.md").read_text(encoding="utf-8"), changelog)
            # ...LICENSE written deterministically (engine Apache 2.0 text, NOT from the LLM)...
            license_text = (repo / "LICENSE").read_text(encoding="utf-8")
            self.assertIn("Apache License", license_text)
            self.assertNotIn(readme, license_text)
            # ...and all four staged in one git add so the commit includes them.
            git_run.assert_called_once()
            self.assertEqual(
                git_run.call_args.args[0],
                ["git", "add", "docs/architecture_state.md", "README.md", "CHANGELOG.md", "LICENSE"],
            )
            self.assertEqual(git_run.call_args.kwargs["cwd"], str(repo))
            # ...against the techwriter role + DocumentationUpdate schema.
            self.assertEqual(llm.call_args.args[0], "techwriter")
            self.assertIs(llm.call_args.args[1], DocumentationUpdate)

    async def test_first_iteration_feeds_placeholders_without_filenotfound(self) -> None:
        # No docs/, README, or CHANGELOG exist yet (the very first task).
        with TemporaryDirectory() as td:
            repo = Path(td)
            ctx = self._ctx(repo)
            captured: dict[str, str] = {}

            def _capture(role, response_model, messages):
                captured["user"] = messages[1]["content"]
                return _fake_update()

            with (
                mock.patch.object(techwriter, "run_structured_llm", new=AsyncMock(side_effect=_capture)),
                mock.patch.object(techwriter.subprocess, "run"),
            ):
                await techwriter.run_techwriter_node(ctx)  # must not raise FileNotFoundError

            # The previous-state sections carried the first-iteration placeholders.
            self.assertIn("No architecture state documented yet", captured["user"])
            self.assertIn("No README yet", captured["user"])
            self.assertIn("No CHANGELOG yet", captured["user"])

    async def test_final_ticket_writes_and_stages_usage_guide(self) -> None:
        # On the batch's final ticket the end-user usage guide is authored to docs/USAGE.md and staged.
        with TemporaryDirectory() as td:
            repo = Path(td)
            ctx = self._ctx(repo)
            ctx.is_final_ticket = True
            usage = "# Usage\n\nRun `exporter --in a --out b`.\n"
            captured: dict[str, str] = {}

            def _capture(role, response_model, messages):
                captured["user"] = messages[1]["content"]
                return _fake_update(usage=usage)

            with (
                mock.patch.object(techwriter, "run_structured_llm", new=AsyncMock(side_effect=_capture)),
                mock.patch.object(techwriter.subprocess, "run") as git_run,
            ):
                await techwriter.run_techwriter_node(ctx)

            self.assertEqual((repo / "docs" / "USAGE.md").read_text(encoding="utf-8"), usage)
            self.assertIn("docs/USAGE.md", git_run.call_args.args[0])
            # The prompt was told this is the final iteration.
            self.assertIn("=== FINAL ITERATION ===\ntrue", captured["user"])

    async def test_non_final_ticket_does_not_write_usage_guide(self) -> None:
        # A stray usage_guide on a non-final ticket is ignored (node-gated by is_final_ticket).
        with TemporaryDirectory() as td:
            repo = Path(td)
            ctx = self._ctx(repo)  # is_final_ticket defaults False
            with (
                mock.patch.object(
                    techwriter, "run_structured_llm",
                    new=AsyncMock(return_value=_fake_update(usage="# leaked usage\n")),
                ),
                mock.patch.object(techwriter.subprocess, "run") as git_run,
            ):
                await techwriter.run_techwriter_node(ctx)

            self.assertFalse((repo / "docs" / "USAGE.md").exists())
            self.assertNotIn("docs/USAGE.md", git_run.call_args.args[0])

    async def test_existing_license_is_not_regenerated_and_not_restaged(self) -> None:
        # A subsequent ticket: LICENSE already on disk → idempotent, left untouched and not re-staged.
        with TemporaryDirectory() as td:
            repo = Path(td)
            ctx = self._ctx(repo)
            (repo / "LICENSE").write_text("PRE-EXISTING LICENSE TEXT\n", encoding="utf-8")
            with (
                mock.patch.object(
                    techwriter, "run_structured_llm", new=AsyncMock(return_value=_fake_update()),
                ),
                mock.patch.object(techwriter.subprocess, "run") as git_run,
            ):
                await techwriter.run_techwriter_node(ctx)

            self.assertEqual((repo / "LICENSE").read_text(encoding="utf-8"), "PRE-EXISTING LICENSE TEXT\n")
            staged = git_run.call_args.args[0]
            self.assertNotIn("LICENSE", staged)
            self.assertEqual(staged, ["git", "add", "docs/architecture_state.md", "README.md", "CHANGELOG.md"])


if __name__ == "__main__":
    unittest.main()
