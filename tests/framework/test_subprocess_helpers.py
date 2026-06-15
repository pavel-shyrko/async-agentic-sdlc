"""Unit tests for subprocess path validation and the Claude CLI launcher.

Security focus: ``_assert_within_root`` is the sandbox boundary guard, so
path-traversal and prefix-forgery attacks are asserted to raise before any
process is spawned. ``asyncio.create_subprocess_exec`` is always mocked.
"""
import os
import unittest
from decimal import Decimal
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

from src.utils import subprocess_helpers
from src.utils.subprocess_helpers import (
    _assert_within_root,
    parse_claude_usage,
    run_claude_cli,
    stream_subprocess_output,
)


class _MutedLogMixin:
    """Silences the module logger so expected security rejections don't spam
    the console (the 🚨 marker is un-encodable under the Windows codepage)."""

    def setUp(self) -> None:
        super().setUp()
        patcher = mock.patch.object(subprocess_helpers, "log")
        self.addCleanup(patcher.stop)
        patcher.start()

# Absolute anchors; os.path.abspath normalises both root and targets against
# the same drive/CWD, so the containment comparison is stable cross-platform.
_ROOT = os.path.abspath("/srv/sandbox/code")


class AssertWithinRootSecurityTests(_MutedLogMixin, unittest.TestCase):
    """The guard must accept only paths genuinely nested under the root."""

    def test_legitimate_nested_path_is_accepted(self) -> None:
        # Arrange
        target = os.path.join(_ROOT, "pkg", "module.py")
        # Act / Assert — no exception means the write is permitted.
        _assert_within_root([target], _ROOT)

    def test_path_equal_to_root_is_accepted(self) -> None:
        # Arrange / Act / Assert
        _assert_within_root([_ROOT], _ROOT)

    def test_empty_target_list_is_accepted(self) -> None:
        # Arrange / Act / Assert
        _assert_within_root([], _ROOT)

    def test_parent_traversal_is_rejected(self) -> None:
        # Arrange — '../' escapes the sandbox after normalisation.
        target = os.path.join(_ROOT, "..", "..", "etc", "passwd")
        # Act / Assert
        with self.assertRaises(ValueError):
            _assert_within_root([target], _ROOT)

    def test_sibling_prefix_forgery_is_rejected(self) -> None:
        # Arrange — '/srv/sandbox/code-evil' shares a textual prefix with the
        # root but is a distinct sibling directory.
        forged = os.path.abspath("/srv/sandbox/code-evil/file.py")
        # Act / Assert
        with self.assertRaises(ValueError):
            _assert_within_root([forged], _ROOT)

    def test_mixed_batch_rejects_when_any_path_escapes(self) -> None:
        # Arrange
        good = os.path.join(_ROOT, "ok.py")
        bad = os.path.abspath("/srv/sandbox/code-evil/x.py")
        # Act / Assert — the offending path is named in the failure.
        with self.assertRaises(ValueError) as ctx:
            _assert_within_root([good, bad], _ROOT)
        self.assertIn(bad, str(ctx.exception))


class RunClaudeCliTests(_MutedLogMixin, unittest.IsolatedAsyncioTestCase):
    """The launcher validates the sandbox boundary before spawning anything."""

    @mock.patch("src.utils.subprocess_helpers.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_out_of_sandbox_target_blocks_before_spawn(self, mock_exec: AsyncMock) -> None:
        # Arrange
        forged = os.path.abspath("/srv/sandbox/code-evil/x.py")
        # Act / Assert — guard raises and no subprocess is ever created.
        with self.assertRaises(ValueError):
            await run_claude_cli("prompt", [forged], _ROOT)
        mock_exec.assert_not_called()

    @mock.patch("src.utils.subprocess_helpers.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_builds_expected_command_for_valid_target(self, mock_exec: AsyncMock) -> None:
        # Arrange
        target = os.path.join(_ROOT, "feature.py")
        proc = MagicMock()
        proc.stdout = _empty_stream()
        proc.stderr = _empty_stream()
        proc.wait = AsyncMock(return_value=0)
        proc.returncode = 0
        mock_exec.return_value = proc
        # Act
        rc, usage = await run_claude_cli("do the thing", [target], _ROOT)
        # Assert
        self.assertEqual(rc, 0)
        self.assertIsNone(usage)  # empty stdout → no usage envelope to parse
        spawned = mock_exec.call_args.args
        self.assertEqual(
            spawned,
            ("claude", "-p", "do the thing", "--output-format", "json",
             "--dangerously-skip-permissions", target),
        )

    @mock.patch("src.utils.subprocess_helpers.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_forwards_model_and_effort_flags(self, mock_exec: AsyncMock) -> None:
        # Arrange
        target = os.path.join(_ROOT, "feature.py")
        proc = MagicMock()
        proc.stdout = _empty_stream()
        proc.stderr = _empty_stream()
        proc.wait = AsyncMock(return_value=0)
        proc.returncode = 0
        mock_exec.return_value = proc
        # Act
        rc, _ = await run_claude_cli("do it", [target], _ROOT, model="sonnet", effort="medium")
        # Assert — model/effort are forwarded to the CLI before the permissions flag and files.
        self.assertEqual(rc, 0)
        spawned = mock_exec.call_args.args
        self.assertEqual(
            spawned,
            ("claude", "-p", "do it", "--output-format", "json",
             "--model", "sonnet", "--effort", "medium",
             "--dangerously-skip-permissions", target),
        )


class ParseClaudeUsageTests(_MutedLogMixin, unittest.TestCase):
    """The usage parser is total and defensive: valid envelope → dict, anything else → None."""

    def test_parses_valid_envelope_and_folds_cache_into_input(self) -> None:
        # Arrange — mirrors the real `claude --output-format json` result shape.
        envelope = (
            '{"type":"result","total_cost_usd":0.1234,'
            '"usage":{"input_tokens":6,"cache_creation_input_tokens":30000,'
            '"cache_read_input_tokens":100,"output_tokens":12}}'
        )
        # Act
        usage = parse_claude_usage(envelope)
        # Assert — input side = 6 + 30000 + 100; cost is exact Decimal from total_cost_usd.
        self.assertEqual(usage, {"input_tokens": 30106, "output_tokens": 12, "cost_usd": Decimal("0.1234")})

    def test_legacy_cost_key_is_honoured(self) -> None:
        usage = parse_claude_usage('{"cost_usd":0.5,"usage":{"input_tokens":1,"output_tokens":2}}')
        self.assertEqual(usage["cost_usd"], Decimal("0.5"))

    def test_malformed_json_returns_none(self) -> None:
        self.assertIsNone(parse_claude_usage("not json at all"))

    def test_missing_usage_block_defaults_to_zero(self) -> None:
        usage = parse_claude_usage('{"type":"result","total_cost_usd":0.0}')
        self.assertEqual(usage, {"input_tokens": 0, "output_tokens": 0, "cost_usd": Decimal("0.0")})


class StreamSubprocessOutputTests(unittest.IsolatedAsyncioTestCase):
    """The stream consumer buffers decoded lines until EOF."""

    async def test_collects_and_strips_lines_until_eof(self) -> None:
        # Arrange
        reader = MagicMock()
        reader.readline = AsyncMock(side_effect=[b"first line\n", b"second\n", b""])
        buffer: list[str] = []
        # Act
        await stream_subprocess_output("[T]", reader, buffer)
        # Assert
        self.assertEqual(buffer, ["first line", "second"])


def _empty_stream() -> MagicMock:
    """A StreamReader stand-in that immediately reports EOF."""
    reader = MagicMock()
    reader.readline = AsyncMock(return_value=b"")
    return reader


if __name__ == "__main__":
    unittest.main()
