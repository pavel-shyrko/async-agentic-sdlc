"""Registry invariants for the Paved-Road environment table (SUPPORTED_ENVIRONMENTS)."""
import os
import unittest

# environments imports nothing network-bound, but keep the guard consistent with sibling suites.
os.environ.setdefault("GEMINI_API_KEY", "test-key")

from src.shared.core.environments import SUPPORTED_ENVIRONMENTS


class PythonTestCmdTests(unittest.TestCase):
    """The Python functional gate must invoke pytest via `python -m` so the sandbox cwd (/workspace)
    lands on sys.path[0] — otherwise topology imports like `from src.converter import …` raise
    `ModuleNotFoundError: No module named 'src'` (BACKLOG #15)."""

    def test_python_runs_pytest_as_module(self) -> None:
        test_cmd = SUPPORTED_ENVIRONMENTS["python-3.12-core"]["test_cmd"]
        self.assertEqual(test_cmd, "python -m pytest")
        # The bare console script would not put cwd on sys.path — guard against a regression to it.
        self.assertTrue(test_cmd.startswith("python -m "))


if __name__ == "__main__":
    unittest.main()
