"""Unit tests for QA-agent deterministic helpers (zombie-test disposal)."""
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

# qa imports src.shared.core.config at module import time.
os.environ.setdefault("GEMINI_API_KEY", "test-key")

from src.executor.agents import qa


class DisposeZombieTestsTests(unittest.TestCase):
    """``_dispose_zombie_tests`` deletes Reviewer-flagged test files, strictly sandboxed to tests_dir."""

    def test_deletes_named_test_file_inside_tests_dir(self) -> None:
        with TemporaryDirectory() as td:
            tests_dir = Path(td)
            zombie = tests_dir / "test_old_module.py"
            zombie.write_text("import gone", encoding="utf-8")

            qa._dispose_zombie_tests(tests_dir, {"test_old_module.py"})

            self.assertFalse(zombie.exists())

    def test_refuses_path_traversal_escape(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            tests_dir = root / "tests"
            tests_dir.mkdir()
            outsider = root / "test_secret.py"  # a test_*.py, but OUTSIDE the tests dir
            outsider.write_text("keep me", encoding="utf-8")

            qa._dispose_zombie_tests(tests_dir, {"../test_secret.py"})

            self.assertTrue(outsider.exists())  # traversal rejected — protected file survives

    def test_refuses_non_test_file(self) -> None:
        with TemporaryDirectory() as td:
            tests_dir = Path(td)
            protected = tests_dir / "conftest.py"  # not a test_*.py
            protected.write_text("keep me", encoding="utf-8")

            qa._dispose_zombie_tests(tests_dir, {"conftest.py"})

            self.assertTrue(protected.exists())

    def test_missing_file_is_a_noop(self) -> None:
        with TemporaryDirectory() as td:
            # Names a file that does not exist — must not raise.
            qa._dispose_zombie_tests(Path(td), {"test_absent.py"})


if __name__ == "__main__":
    unittest.main()
