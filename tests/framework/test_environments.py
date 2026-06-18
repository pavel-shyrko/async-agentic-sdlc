"""Registry invariants for the Paved-Road environment table (SUPPORTED_ENVIRONMENTS)."""
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

# environments imports nothing network-bound, but keep the guard consistent with sibling suites.
os.environ.setdefault("GEMINI_API_KEY", "test-key")

from src.shared.core.environments import (
    SUPPORTED_ENVIRONMENTS,
    GITIGNORE_TEMPLATES,
    get_gitignore_template,
)


class PythonTestCmdTests(unittest.TestCase):
    """The Python functional gate must invoke pytest via `python -m` so the sandbox cwd (/workspace)
    lands on sys.path[0] — otherwise topology imports like `from src.converter import …` raise
    `ModuleNotFoundError: No module named 'src'` (BACKLOG #15)."""

    def test_python_runs_pytest_as_module(self) -> None:
        test_cmd = SUPPORTED_ENVIRONMENTS["python-3.12-core"]["test_cmd"]
        self.assertEqual(test_cmd, "python -m pytest")
        # The bare console script would not put cwd on sys.path — guard against a regression to it.
        self.assertTrue(test_cmd.startswith("python -m "))


@unittest.skipIf(shutil.which("git") is None, "git not available")
class GitignoreTemplateTests(unittest.TestCase):
    """The canonical templates must never ignore a SOURCE directory that shares a name with the
    build artifact — the exact failure that looped a real run into the circuit breaker."""

    def _check_ignored(self, repo: Path, rel: str) -> bool:
        # `git check-ignore` exits 0 when the path IS ignored, 1 when it is not.
        return subprocess.run(
            ["git", "check-ignore", "-q", rel], cwd=str(repo)
        ).returncode == 0

    def test_every_env_resolves_to_a_template(self) -> None:
        for env_id in SUPPORTED_ENVIRONMENTS:
            self.assertTrue(get_gitignore_template(env_id).strip(), env_id)

    def test_source_dir_named_like_binary_is_not_ignored(self) -> None:
        # Regression: an unanchored `json2csv` once swallowed the cmd/json2csv/ source dir, so
        # `git add -A` dropped main.go from the snapshot. Assert NO template repeats that mistake.
        for env_id in SUPPORTED_ENVIRONMENTS:
            with TemporaryDirectory() as td, self.subTest(env=env_id):
                repo = Path(td)
                subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
                (repo / ".gitignore").write_text(get_gitignore_template(env_id), encoding="utf-8")
                src = repo / "cmd" / "json2csv"
                src.mkdir(parents=True)
                (src / "main.go").write_text("package main\n", encoding="utf-8")
                self.assertFalse(
                    self._check_ignored(repo, "cmd/json2csv/main.go"),
                    f"{env_id}: source file under cmd/json2csv/ is git-ignored by the template",
                )

    def test_go_ignores_binaries_by_extension_not_name(self) -> None:
        go = GITIGNORE_TEMPLATES["go"]
        self.assertIn("*.exe", go)
        self.assertIn("*.test", go)
        # A bare project-name line (unanchored, no glob/slash) is exactly the forbidden pattern.
        for line in go.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            self.assertTrue(
                "/" in line or "*" in line or "." in line,
                f"suspicious unanchored bare pattern in go template: {line!r}",
            )


if __name__ == "__main__":
    unittest.main()
