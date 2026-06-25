"""Unit tests for subprocess path validation and the Claude CLI launcher.

Security focus: ``_assert_within_root`` is the sandbox boundary guard, so
path-traversal and prefix-forgery attacks are asserted to raise before any
process is spawned. ``asyncio.create_subprocess_exec`` is always mocked.
"""
import asyncio
import os
import unittest
from decimal import Decimal
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

from src.shared.utils import subprocess_helpers
from src.shared.utils.subprocess_helpers import (
    ClaudeCliQuotaExhausted,
    _assert_within_root,
    detect_claude_quota_block,
    parse_claude_usage,
    run_claude_cli,
    sanitize_for_argv,
    stream_subprocess_output,
)

# A real Claude CLI session-limit block, as a stream-json assistant event line.
_QUOTA_EVENT = (
    '{"type":"assistant","message":{"content":[{"type":"text",'
    '"text":"You\'ve hit your session limit \\u00b7 resets 5:30am (Europe/Warsaw)"}]}}'
)


class SanitizeForArgvTests(unittest.TestCase):
    """sanitize_for_argv strips control chars that crash/garble a subprocess argv, keeping whitespace."""

    def test_strips_embedded_null(self) -> None:
        # The exact crash: a "©" mangled to NUL in a ticket's License line.
        self.assertEqual(sanitize_for_argv("MIT \x00 2026"), "MIT  2026")
        self.assertNotIn("\x00", sanitize_for_argv("a\x00b"))

    def test_preserves_whitespace_and_unicode(self) -> None:
        body = "line1\nline2\twith tab\r\n## License\nMIT © 2026"
        out = sanitize_for_argv(body)
        self.assertEqual(out, body)            # \n \t \r and a REAL © are untouched
        self.assertIn("©", out)

    def test_strips_other_c0_controls_and_del(self) -> None:
        self.assertEqual(sanitize_for_argv("a\x07b\x1f\x7fc"), "abc")

    def test_clean_string_unchanged(self) -> None:
        self.assertEqual(sanitize_for_argv("feat(TASK-01): plain subject"), "feat(TASK-01): plain subject")


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

    @mock.patch("src.shared.utils.subprocess_helpers.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_out_of_sandbox_target_blocks_before_spawn(self, mock_exec: AsyncMock) -> None:
        # Arrange
        forged = os.path.abspath("/srv/sandbox/code-evil/x.py")
        # Act / Assert — guard raises and no subprocess is ever created.
        with self.assertRaises(ValueError):
            await run_claude_cli("prompt", [forged], _ROOT)
        mock_exec.assert_not_called()

    @mock.patch("src.shared.utils.subprocess_helpers.asyncio.create_subprocess_exec", new_callable=AsyncMock)
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
            ("claude", "-p", "do the thing", "--output-format", "stream-json", "--verbose",
             "--dangerously-skip-permissions", target),
        )
        # Sandbox isolation: the child is anchored to the run repo (allowed_root), so the inner
        # Claude loads the sandbox project context, not the orchestrator's CLAUDE.md/.claude.
        self.assertEqual(mock_exec.call_args.kwargs["cwd"], _ROOT)

    @mock.patch("src.shared.utils.subprocess_helpers.asyncio.create_subprocess_exec", new_callable=AsyncMock)
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
            ("claude", "-p", "do it", "--output-format", "stream-json", "--verbose",
             "--model", "sonnet", "--effort", "medium",
             "--dangerously-skip-permissions", target),
        )


    @mock.patch("src.shared.utils.subprocess_helpers.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_timeout_kills_and_reaps_child(self, mock_exec: AsyncMock) -> None:
        # Arrange — streams never EOF, so the real asyncio.wait_for must fire and cancel the readers.
        target = os.path.join(_ROOT, "feature.py")
        proc = MagicMock()
        proc.stdout = _hanging_stream()
        proc.stderr = _hanging_stream()
        proc.kill = MagicMock()
        proc.wait = AsyncMock(return_value=-9)
        mock_exec.return_value = proc
        # Act — tiny real timeout so the test is fast; the launcher must not hang.
        rc, usage = await run_claude_cli("do it", [target], _ROOT, timeout=0.05)
        # Assert — child is killed AND reaped (no zombie), and the timeout sentinel is returned.
        proc.kill.assert_called_once()
        proc.wait.assert_awaited_once()
        self.assertEqual((rc, usage), (124, None))

    @mock.patch("src.shared.utils.subprocess_helpers.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_quota_block_raises_instead_of_returning(self, mock_exec: AsyncMock) -> None:
        # Arrange — the CLI emits a session-limit line then exits non-zero with no usage envelope.
        target = os.path.join(_ROOT, "feature.py")
        proc = MagicMock()
        proc.stdout = _stream_lines([_QUOTA_EVENT.encode() + b"\n"])
        proc.stderr = _empty_stream()
        proc.wait = AsyncMock(return_value=1)
        proc.returncode = 1
        mock_exec.return_value = proc
        # Act / Assert — surfaced as an infrastructure halt signal carrying the reset hint, NOT (1, None).
        with self.assertRaises(ClaudeCliQuotaExhausted) as ctx:
            await run_claude_cli("do it", [target], _ROOT)
        self.assertIn("resets 5:30am", ctx.exception.reset_hint)

    @mock.patch("src.shared.utils.subprocess_helpers.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_idle_watchdog_kills_on_silence(self, mock_exec: AsyncMock) -> None:
        # Arrange — one event then silence; the inactivity watchdog must kill even with NO hard timeout.
        target = os.path.join(_ROOT, "feature.py")
        killed = asyncio.Event()
        proc = MagicMock()
        proc.stdout = _stream_then_eof_on_kill([b'{"type":"system","subtype":"init"}\n'], killed)
        proc.stderr = _stream_then_eof_on_kill([], killed)
        proc.kill = MagicMock(side_effect=killed.set)   # real kill closes pipes -> readers EOF
        proc.wait = AsyncMock(return_value=-9)
        mock_exec.return_value = proc
        # Act — small idle window, no hard timeout; the watchdog is the only kill switch.
        rc, usage = await run_claude_cli("do it", [target], _ROOT, idle_timeout=0.1)
        # Assert — killed on silence, reaped, sentinel returned.
        proc.kill.assert_called_once()
        proc.wait.assert_awaited_once()
        self.assertEqual((rc, usage), (124, None))


class DetectClaudeQuotaBlockTests(unittest.TestCase):
    """The quota detector matches a session/usage-limit block and ignores unrelated output."""

    def test_detects_session_limit_event_and_humanizes_it(self) -> None:
        # Act — the limit text lives inside a stream-json assistant envelope.
        hint = detect_claude_quota_block([
            '{"type":"system","subtype":"init"}',
            _QUOTA_EVENT,
        ])
        # Assert — returns the clean humanized sentence, not the raw JSON.
        self.assertIsNotNone(hint)
        self.assertIn("session limit", hint)
        self.assertIn("resets 5:30am", hint)
        self.assertNotIn('{"type"', hint)

    def test_detects_usage_limit_reached_phrasing(self) -> None:
        self.assertIsNotNone(detect_claude_quota_block(["Claude usage limit reached. Try again later."]))

    def test_normal_output_is_not_a_false_positive(self) -> None:
        # Assert — ordinary assistant work (incl. mentioning "limit" without the quota shape) is ignored.
        self.assertIsNone(detect_claude_quota_block([
            '{"type":"assistant","message":{"content":[{"type":"text","text":"Implemented the depth limit check."}]}}',
            '{"type":"result","subtype":"success","total_cost_usd":0.1}',
        ]))

    def test_empty_buffer_returns_none(self) -> None:
        self.assertIsNone(detect_claude_quota_block([]))


class ParseClaudeUsageTests(_MutedLogMixin, unittest.TestCase):
    """The usage parser is total and defensive: valid envelope → dict, anything else → None."""

    def test_parses_usage_from_streaming_jsonl(self) -> None:
        # Arrange — `--output-format stream-json` emits many event lines; usage is in the LAST one.
        jsonl = "\n".join([
            '{"type":"system","subtype":"init"}',
            '{"type":"assistant","message":{"content":[{"type":"text","text":"working"}]}}',
            '{"type":"user","message":{"content":[]}}',
            '{"type":"result","subtype":"success","total_cost_usd":0.5,'
            '"usage":{"input_tokens":3,"cache_creation_input_tokens":10,'
            '"cache_read_input_tokens":50,"output_tokens":7}}',
        ])
        # Act
        usage = parse_claude_usage(jsonl)
        # Assert — parsed from the final result event, cache kept separate.
        self.assertEqual(usage, {
            "input_tokens": 3,
            "cache_write_tokens": 10,
            "cache_read_tokens": 50,
            "output_tokens": 7,
            "cost_usd": Decimal("0.5"),
        })

    def test_parses_valid_envelope_keeping_cache_separate(self) -> None:
        # Arrange — mirrors the legacy single-blob `--output-format json` result shape.
        envelope = (
            '{"type":"result","total_cost_usd":0.1234,'
            '"usage":{"input_tokens":6,"cache_creation_input_tokens":30000,'
            '"cache_read_input_tokens":100,"output_tokens":12}}'
        )
        # Act
        usage = parse_claude_usage(envelope)
        # Assert — cache is NOT folded into input_tokens (fresh=6); cost is exact Decimal.
        self.assertEqual(usage, {
            "input_tokens": 6,
            "cache_write_tokens": 30000,
            "cache_read_tokens": 100,
            "output_tokens": 12,
            "cost_usd": Decimal("0.1234"),
        })

    def test_legacy_cost_key_is_honoured(self) -> None:
        usage = parse_claude_usage('{"cost_usd":0.5,"usage":{"input_tokens":1,"output_tokens":2}}')
        self.assertEqual(usage["cost_usd"], Decimal("0.5"))

    def test_malformed_json_returns_none(self) -> None:
        self.assertIsNone(parse_claude_usage("not json at all"))

    def test_missing_usage_block_defaults_to_zero(self) -> None:
        usage = parse_claude_usage('{"type":"result","total_cost_usd":0.0}')
        self.assertEqual(usage, {
            "input_tokens": 0,
            "cache_write_tokens": 0,
            "cache_read_tokens": 0,
            "output_tokens": 0,
            "cost_usd": Decimal("0.0"),
        })


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


def _stream_lines(lines: list) -> MagicMock:
    """A StreamReader stand-in that yields each line in ``lines`` then reports EOF."""
    it = iter(lines)

    async def _readline(*_a, **_k):
        try:
            return next(it)
        except StopIteration:
            return b""

    reader = MagicMock()
    reader.readline = _readline
    return reader


def _hanging_stream() -> MagicMock:
    """A StreamReader stand-in whose readline never resolves — parks the reader forever."""
    async def _never(*_a, **_k):
        await asyncio.Event().wait()   # never set -> coroutine parks until cancelled
    reader = MagicMock()
    reader.readline = _never
    return reader


def _stream_then_eof_on_kill(lines: list, kill_event: "asyncio.Event") -> MagicMock:
    """A StreamReader stand-in that yields ``lines`` then parks until ``kill_event`` is set, after
    which it returns EOF (b"") — modelling a real pipe that closes when the child is killed."""
    it = iter(lines)

    async def _readline(*_a, **_k):
        try:
            return next(it)
        except StopIteration:
            await kill_event.wait()
            return b""

    reader = MagicMock()
    reader.readline = _readline
    return reader


if __name__ == "__main__":
    unittest.main()
