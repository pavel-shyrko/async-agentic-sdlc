"""Unit tests for git-driven state tracking.

The real ``git`` binary is never invoked: ``asyncio.create_subprocess_exec``
is replaced with an ``AsyncMock`` returning fabricated process handles so the
fan-out and fallback logic can be exercised deterministically.
"""
import unittest
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

from src.utils.git_helpers import (
    get_git_root,
    get_pipeline_snapshot_files,
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
    """Cumulative INDEX diff against the anchor branch drives the snapshot."""

    @mock.patch("src.utils.git_helpers.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_returns_changed_files_excluding_gitignore(self, mock_exec: AsyncMock) -> None:
        # Arrange — first call stages, second call yields the cached diff.
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
    async def test_raises_when_diff_fails(self, mock_exec: AsyncMock) -> None:
        # Arrange — non-zero diff returncode (e.g. unknown anchor branch / index.lock).
        mock_exec.side_effect = [_fake_proc(0), _fake_proc(128, b"")]
        # Act / Assert — fail fast instead of silently feeding an empty snapshot.
        with self.assertRaises(RuntimeError):
            await get_pipeline_snapshot_files("/repo", "ghost-branch")

    @mock.patch("src.utils.git_helpers.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_raises_when_git_add_fails(self, mock_exec: AsyncMock) -> None:
        # Arrange — staging itself fails (e.g. orphaned .git/index.lock).
        mock_exec.side_effect = [_fake_proc(128, b"")]
        # Act / Assert
        with self.assertRaises(RuntimeError):
            await get_pipeline_snapshot_files("/repo", "main")

    @mock.patch("src.utils.git_helpers.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_stages_all_then_diffs_cached_against_base_branch(self, mock_exec: AsyncMock) -> None:
        # Arrange
        mock_exec.side_effect = [_fake_proc(0), _fake_proc(0, b"")]
        # Act
        await get_pipeline_snapshot_files("/repo", "release/v2")
        # Assert — staging (incl. untracked) precedes the index diff against the anchor.
        commands = _git_subcommands(mock_exec)
        self.assertEqual(commands[0], ("add", "-A"))
        self.assertEqual(commands[1], ("diff", "--cached", "release/v2", "--name-only"))

    @mock.patch("src.utils.git_helpers.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_scopes_diff_to_subdir_pathspec(self, mock_exec: AsyncMock) -> None:
        # Arrange
        mock_exec.side_effect = [_fake_proc(0), _fake_proc(0, b"")]
        # Act
        await get_pipeline_snapshot_files("/repo", "main", subdir="src")
        # Assert — the pathspec isolates an agent to its own subtree within the shared index.
        commands = _git_subcommands(mock_exec)
        self.assertEqual(commands[1], ("diff", "--cached", "main", "--name-only", "--", "src"))


class GetGitRootTests(unittest.IsolatedAsyncioTestCase):
    """Root resolution must use git, not path guessing."""

    @mock.patch("src.utils.git_helpers.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_returns_repository_toplevel(self, mock_exec: AsyncMock) -> None:
        # Arrange
        mock_exec.return_value = _fake_proc(0, b"/clone/root\n")
        # Act
        root = await get_git_root("/clone/root/backend/app/src")
        # Assert — the real toplevel, regardless of how deep the requested path is.
        self.assertEqual(root, "/clone/root")
        self.assertEqual(_git_subcommands(mock_exec)[0], ("rev-parse", "--show-toplevel"))

    @mock.patch("src.utils.git_helpers.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_raises_when_path_is_not_a_repo(self, mock_exec: AsyncMock) -> None:
        # Arrange
        mock_exec.return_value = _fake_proc(128, b"")
        # Act / Assert
        with self.assertRaises(RuntimeError):
            await get_git_root("/nowhere")


if __name__ == "__main__":
    unittest.main()
