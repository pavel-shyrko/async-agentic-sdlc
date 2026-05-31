"""Unit tests for git-driven state tracking.

The real ``git`` binary is never invoked: ``asyncio.create_subprocess_exec``
is replaced with an ``AsyncMock`` returning fabricated process handles so the
fan-out and fallback logic can be exercised deterministically.
"""
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

from src.utils import git_helpers
from src.utils.git_helpers import (
    _deploy_gitignore,
    get_pipeline_snapshot_files,
    init_sandbox_git,
)


def _fake_proc(returncode: int, stdout: bytes = b"") -> MagicMock:
    """Builds a stand-in asyncio subprocess with an awaitable ``communicate``."""
    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(stdout, b""))
    proc.returncode = returncode
    return proc


def _git_subcommands(mock_exec: AsyncMock) -> list[tuple[str, ...]]:
    """Extracts the git argument tuples (dropping the leading 'git') per call."""
    return [call.args[1:] for call in mock_exec.call_args_list]


class GetPipelineSnapshotFilesTests(unittest.IsolatedAsyncioTestCase):
    """Cumulative diff against the anchor branch drives the snapshot."""

    def setUp(self) -> None:
        super().setUp()
        # The missing-branch path logs a 🚨 ERROR that the Windows console
        # cannot encode; mute it so the expected fallback stays quiet.
        patcher = mock.patch.object(git_helpers, "log")
        self.addCleanup(patcher.stop)
        patcher.start()

    @mock.patch("src.utils.git_helpers.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_returns_changed_files_excluding_gitignore(self, mock_exec: AsyncMock) -> None:
        # Arrange — first call stages, second call yields the diff.
        mock_exec.side_effect = [
            _fake_proc(0),
            _fake_proc(0, b"src/a.py\nsrc/b.py\n.gitignore\n"),
        ]
        # Act
        files = await get_pipeline_snapshot_files("/repo", "main")
        # Assert
        self.assertEqual(files, ["src/a.py", "src/b.py"])

    @mock.patch("src.utils.git_helpers.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_filters_blank_lines_from_diff_output(self, mock_exec: AsyncMock) -> None:
        # Arrange
        mock_exec.side_effect = [_fake_proc(0), _fake_proc(0, b"src/a.py\n\n\nsrc/c.py\n")]
        # Act
        files = await get_pipeline_snapshot_files("/repo", "main")
        # Assert
        self.assertEqual(files, ["src/a.py", "src/c.py"])

    @mock.patch("src.utils.git_helpers.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_falls_back_to_empty_list_when_base_branch_missing(self, mock_exec: AsyncMock) -> None:
        # Arrange — non-zero diff returncode signals an unknown anchor branch.
        mock_exec.side_effect = [_fake_proc(0), _fake_proc(128, b"")]
        # Act
        files = await get_pipeline_snapshot_files("/repo", "ghost-branch")
        # Assert
        self.assertEqual(files, [])

    @mock.patch("src.utils.git_helpers.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_diffs_against_the_supplied_base_branch(self, mock_exec: AsyncMock) -> None:
        # Arrange
        mock_exec.side_effect = [_fake_proc(0), _fake_proc(0, b"")]
        # Act
        await get_pipeline_snapshot_files("/repo", "release/v2")
        # Assert — staging precedes the name-only diff against the anchor.
        commands = _git_subcommands(mock_exec)
        self.assertEqual(commands[0], ("add", "."))
        self.assertEqual(commands[1], ("diff", "release/v2", "--name-only"))


class InitSandboxGitTests(unittest.IsolatedAsyncioTestCase):
    """Sandbox bootstrap must be idempotent and pin the anchor branch."""

    @mock.patch("src.utils.git_helpers.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    @mock.patch("src.utils.git_helpers.os.path.isdir", return_value=True)
    async def test_skips_initialisation_when_repo_already_exists(
        self, _mock_isdir: MagicMock, mock_exec: AsyncMock
    ) -> None:
        # Arrange / Act
        await init_sandbox_git("/repo", "main")
        # Assert — an existing .git short-circuits every git invocation.
        mock_exec.assert_not_called()

    @mock.patch("src.utils.git_helpers._deploy_gitignore")
    @mock.patch("src.utils.git_helpers.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    @mock.patch("src.utils.git_helpers.os.path.isdir", return_value=False)
    async def test_bootstraps_repo_and_pins_anchor_branch(
        self, _mock_isdir: MagicMock, mock_exec: AsyncMock, mock_deploy: MagicMock
    ) -> None:
        # Arrange
        mock_exec.return_value = _fake_proc(0)
        # Act
        await init_sandbox_git("/repo", "main")
        # Assert
        commands = _git_subcommands(mock_exec)
        self.assertEqual(commands[0], ("init",))
        self.assertIn(("branch", "-m", "main"), commands)
        self.assertIn(("checkout", "-b", "agent-workspace"), commands)
        mock_deploy.assert_called_once_with("/repo")

    @mock.patch("src.utils.git_helpers._deploy_gitignore")
    @mock.patch("src.utils.git_helpers.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    @mock.patch("src.utils.git_helpers.os.path.isdir", return_value=False)
    async def test_configures_identity_before_first_commit(
        self, _mock_isdir: MagicMock, mock_exec: AsyncMock, _mock_deploy: MagicMock
    ) -> None:
        # Arrange
        mock_exec.return_value = _fake_proc(0)
        # Act
        await init_sandbox_git("/repo", "main")
        # Assert — identity config must precede the initial commit.
        commands = _git_subcommands(mock_exec)
        email_idx = commands.index(("config", "user.email", "pipeline@sdlc.local"))
        commit_idx = next(i for i, c in enumerate(commands) if c[0] == "commit")
        self.assertLess(email_idx, commit_idx)


class DeployGitignoreTests(unittest.TestCase):
    """Template deployment with a minimal fallback when the template is absent."""

    @mock.patch("src.utils.git_helpers.Path.write_text")
    def test_copies_template_when_present(self, mock_write: MagicMock) -> None:
        # Arrange
        template = MagicMock()
        template.exists.return_value = True
        template.read_text.return_value = "node_modules/\n"
        # Act
        with mock.patch.object(git_helpers, "_GITIGNORE_TEMPLATE", template):
            _deploy_gitignore("/repo")
        # Assert
        mock_write.assert_called_once_with("node_modules/\n", encoding="utf-8")

    @mock.patch("src.utils.git_helpers.Path.write_text")
    def test_writes_minimal_fallback_when_template_missing(self, mock_write: MagicMock) -> None:
        # Arrange
        template = MagicMock()
        template.exists.return_value = False
        # Act
        with mock.patch.object(git_helpers, "_GITIGNORE_TEMPLATE", template):
            _deploy_gitignore("/repo")
        # Assert
        mock_write.assert_called_once_with(git_helpers._GITIGNORE_FALLBACK, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
