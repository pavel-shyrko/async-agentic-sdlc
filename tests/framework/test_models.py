"""Unit tests for the SDLC contract models and workspace bootstrap.

Filesystem is fully isolated: every WorkspacePaths construction patches
``Path.mkdir`` so the suite never touches the real artifact tree.
"""
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest import mock
from pydantic import ValidationError

from src.core.models import (
    CODE_DIR,
    LOGS_DIR,
    REPORTS_DIR,
    TESTS_DIR,
    ArchitectureContract,
    GlobalPipelineContext,
    QATestSuite,
    ReviewReport,
    WorkspacePaths,
)


class QATestSuiteFenceCleaningTests(unittest.TestCase):
    """Validator ``clean_markdown_fences`` must strip LLM markdown artifacts."""

    def test_strips_python_language_fence(self) -> None:
        # Arrange
        raw = "```python\nprint('hi')\n```"
        # Act
        suite = QATestSuite(test_code=raw)
        # Assert
        self.assertEqual(suite.test_code, "print('hi')")

    def test_language_fence_is_case_insensitive(self) -> None:
        # Arrange
        raw = "```PYTHON\nimport os\n```"
        # Act
        suite = QATestSuite(test_code=raw)
        # Assert
        self.assertEqual(suite.test_code, "import os")

    def test_strips_bare_fence_without_language(self) -> None:
        # Arrange
        raw = "```\nx = 1\n```"
        # Act
        suite = QATestSuite(test_code=raw)
        # Assert
        self.assertEqual(suite.test_code, "x = 1")

    def test_tolerates_trailing_whitespace_after_language_tag(self) -> None:
        # Arrange
        raw = "```python   \ndef f():\n    return 1\n```"
        # Act
        suite = QATestSuite(test_code=raw)
        # Assert
        self.assertEqual(suite.test_code, "def f():\n    return 1")

    def test_trims_blank_edges_when_no_fence_present(self) -> None:
        # Arrange
        raw = "\n\n   value = 42   \n\n"
        # Act
        suite = QATestSuite(test_code=raw)
        # Assert
        self.assertEqual(suite.test_code, "value = 42")

    def test_clean_code_passes_through_unchanged(self) -> None:
        # Arrange
        raw = "def add(a: int, b: int) -> int:\n    return a + b"
        # Act
        suite = QATestSuite(test_code=raw)
        # Assert
        self.assertEqual(suite.test_code, raw)

    def test_internal_fence_like_text_is_preserved(self) -> None:
        # Arrange — only edge fences are stripped, not interior content.
        raw = "s = '```not a fence```'"
        # Act
        suite = QATestSuite(test_code=raw)
        # Assert
        self.assertEqual(suite.test_code, "s = '```not a fence```'")


class WorkspacePathsTests(unittest.TestCase):
    """Workspace bootstrap creates the canonical tree without leaking to disk."""

    def test_defaults_match_canonical_artifact_dirs(self) -> None:
        # Arrange / Act
        with mock.patch.object(Path, "mkdir") as mkdir:
            paths = WorkspacePaths()
        # Assert
        self.assertEqual(paths.code_dir, CODE_DIR)
        self.assertEqual(paths.tests_dir, TESTS_DIR)
        self.assertEqual(paths.logs_dir, LOGS_DIR)
        self.assertEqual(paths.reports_dir, REPORTS_DIR)
        self.assertEqual(mkdir.call_count, 4)

    def test_post_init_creates_each_dir_recursively_and_idempotently(self) -> None:
        # Arrange / Act
        with mock.patch.object(Path, "mkdir") as mkdir:
            WorkspacePaths()
        # Assert — every directory is created with parents + exist_ok.
        self.assertTrue(mkdir.call_args_list)
        for call in mkdir.call_args_list:
            self.assertEqual(call, mock.call(parents=True, exist_ok=True))

    def test_custom_paths_are_honoured(self) -> None:
        # Arrange
        custom = Path("/tmp/sandbox/code")
        # Act
        with mock.patch.object(Path, "mkdir"):
            paths = WorkspacePaths(code_dir=custom)
        # Assert
        self.assertEqual(paths.code_dir, custom)


class ContractModelTests(unittest.TestCase):
    """Pydantic contracts parse expected payloads and defaults."""

    def test_architecture_contract_round_trips_fields(self) -> None:
        # Arrange
        payload = {
            "files_to_modify": ["src/core/calc.py"],
            "instruction": "Implement prime sieve.",
            "function_signatures": "def is_prime(n: int) -> bool",
            "strict_type_validation_rules": "bool must raise TypeError",
            "architecture_reasoning": "Guard against bool subtype of int.",
        }
        # Act
        contract = ArchitectureContract(**payload)
        # Assert
        self.assertEqual(contract.files_to_modify, ["src/core/calc.py"])
        self.assertIn("TypeError", contract.strict_type_validation_rules)

    def test_review_report_requires_explicit_approval_flags(self) -> None:
        # Arrange / Act
        report = ReviewReport(
            code_quality_analysis="clean",
            test_integrity_analysis="no softening",
            log_verification_analysis="bandit clean",
            code_quality_approved=True,
            test_integrity_approved=False,
            diagnostic_payload="tighten assertions",
        )
        # Assert
        self.assertTrue(report.code_quality_approved)
        self.assertFalse(report.test_integrity_approved)

    def test_global_context_applies_defaults(self) -> None:
        # Arrange / Act — default_factory builds WorkspacePaths, so isolate mkdir.
        with mock.patch.object(Path, "mkdir"):
            ctx = GlobalPipelineContext(pr_description="add prime util")
        # Assert
        self.assertEqual(ctx.base_branch, "main")
        self.assertIsNone(ctx.contract)
        self.assertIsNone(ctx.review_report)
        self.assertEqual(ctx.production_code_snapshot, "")
        self.assertEqual(ctx.current_attempt, 1)
        self.assertIsInstance(ctx.workspace_paths, WorkspacePaths)


class NeedsTestRegenerationTests(unittest.TestCase):
    """Initial recovery decision: regenerate tests on rejection or when no snapshot exists."""

    def _context(self, **kwargs) -> GlobalPipelineContext:
        with mock.patch.object(Path, "mkdir"):
            return GlobalPipelineContext(pr_description="x", **kwargs)

    def _report(self, *, test_integrity_approved: bool) -> ReviewReport:
        return ReviewReport(
            code_quality_analysis="",
            test_integrity_analysis="",
            log_verification_analysis="",
            code_quality_approved=True,
            test_integrity_approved=test_integrity_approved,
            diagnostic_payload="",
        )

    def test_rejected_tests_force_regeneration_even_with_snapshot(self) -> None:
        ctx = self._context(
            test_code_snapshot="assert True",
            review_report=self._report(test_integrity_approved=False),
        )
        self.assertTrue(ctx.needs_test_regeneration())

    def test_no_report_no_snapshot_regenerates(self) -> None:
        ctx = self._context()
        self.assertTrue(ctx.needs_test_regeneration())

    def test_no_report_with_snapshot_skips(self) -> None:
        ctx = self._context(test_code_snapshot="assert True")
        self.assertFalse(ctx.needs_test_regeneration())

    def test_approved_tests_with_snapshot_skips(self) -> None:
        ctx = self._context(
            test_code_snapshot="assert True",
            review_report=self._report(test_integrity_approved=True),
        )
        self.assertFalse(ctx.needs_test_regeneration())


class GlobalContextCheckpointTests(unittest.TestCase):
    """Checkpoint save/load APIs must persist and restore full context state."""

    def test_checkpoint_round_trip_preserves_core_fields(self) -> None:
        # Arrange
        with TemporaryDirectory() as td:
            base = Path(td)
            paths = WorkspacePaths(
                code_dir=base / "code",
                tests_dir=base / "tests",
                logs_dir=base / "logs",
                reports_dir=base / "reports",
            )
            ctx = GlobalPipelineContext(
                pr_description="ship checkpoint support",
                base_branch="main",
                workspace_paths=paths,
                production_code_snapshot="print('ok')",
                test_code_snapshot="assert True",
                error_trace="none",
            )
            checkpoint = paths.reports_dir / "checkpoint.json"

            # Act
            ctx.save_checkpoint(checkpoint)
            loaded = GlobalPipelineContext.load_checkpoint(checkpoint)

            # Assert
            self.assertEqual(loaded.pr_description, "ship checkpoint support")
            self.assertEqual(loaded.production_code_snapshot, "print('ok')")
            self.assertEqual(loaded.test_code_snapshot, "assert True")
            self.assertEqual(loaded.error_trace, "none")

    def test_workspace_paths_round_trip_back_to_path_instances(self) -> None:
        # Arrange
        with TemporaryDirectory() as td:
            base = Path(td)
            paths = WorkspacePaths(
                code_dir=base / "code",
                tests_dir=base / "tests",
                logs_dir=base / "logs",
                reports_dir=base / "reports",
            )
            checkpoint = base / "checkpoint.json"
            GlobalPipelineContext(pr_description="p", workspace_paths=paths).save_checkpoint(checkpoint)

            # Act
            loaded = GlobalPipelineContext.load_checkpoint(checkpoint)

            # Assert
            self.assertIsInstance(loaded.workspace_paths.code_dir, Path)
            self.assertIsInstance(loaded.workspace_paths.tests_dir, Path)
            self.assertIsInstance(loaded.workspace_paths.logs_dir, Path)
            self.assertIsInstance(loaded.workspace_paths.reports_dir, Path)

    def test_load_checkpoint_raises_for_invalid_json(self) -> None:
        # Arrange
        with TemporaryDirectory() as td:
            checkpoint = Path(td) / "checkpoint.json"
            checkpoint.write_text("{broken json", encoding="utf-8")

            # Act / Assert
            with self.assertRaises(ValidationError):
                GlobalPipelineContext.load_checkpoint(checkpoint)


if __name__ == "__main__":
    unittest.main()
