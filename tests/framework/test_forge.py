"""Unit tests for the provider-agnostic forge (gh-backed PR open/approve/merge), E2."""
import os
import json
import unittest
from unittest import mock
from unittest.mock import AsyncMock

# forge → observability may pull config at import time; a dummy key suffices for the mocked suite.
os.environ.setdefault("GEMINI_API_KEY", "test-key")

from src.shared.utils import forge


def _proc(rc: int, stdout: bytes = b"", stderr: bytes = b""):
    p = mock.MagicMock()
    p.returncode = rc
    p.communicate = AsyncMock(return_value=(stdout, stderr))
    return p


class OpenPrTests(unittest.IsolatedAsyncioTestCase):
    async def test_creates_pr_when_none_exists(self) -> None:
        # `gh pr view` exits non-zero (no PR) → fall through to `gh pr create`.
        procs = [_proc(1, stderr=b"no pull requests found"),
                 _proc(0, stdout=b"https://github.com/o/r/pull/5")]
        with mock.patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=procs)) as ex:
            ref = await forge.open_pr("/repo", "feat/ticket-T1", "main", "feat(T1): x", "body")
        self.assertEqual(ref, "https://github.com/o/r/pull/5")
        self.assertEqual(ex.call_count, 2)
        create_cmd = ex.call_args_list[1].args
        self.assertIn("create", create_cmd)
        self.assertIn("--base", create_cmd)
        self.assertIn("main", create_cmd)
        self.assertIn("--head", create_cmd)
        self.assertIn("feat/ticket-T1", create_cmd)

    async def test_reuses_open_pr_with_matching_base(self) -> None:
        view = _proc(0, stdout=json.dumps(
            {"number": 7, "state": "OPEN", "baseRefName": "main", "url": "u"}).encode())
        with mock.patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=[view])) as ex:
            ref = await forge.open_pr("/repo", "feat/ticket-T1", "main", "t", "b")
        self.assertEqual(ref, "7")
        self.assertEqual(ex.call_count, 1)  # no `create` call

    async def test_creates_anew_when_existing_pr_targets_different_base(self) -> None:
        view = _proc(0, stdout=json.dumps(
            {"number": 7, "state": "OPEN", "baseRefName": "develop", "url": "u"}).encode())
        create = _proc(0, stdout=b"https://github.com/o/r/pull/8")
        with mock.patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=[view, create])) as ex:
            ref = await forge.open_pr("/repo", "feat/ticket-T1", "main", "t", "b")
        self.assertEqual(ref, "https://github.com/o/r/pull/8")
        self.assertEqual(ex.call_count, 2)
        self.assertIn("create", ex.call_args_list[1].args)

    async def test_null_byte_in_body_does_not_crash_argv(self) -> None:
        # Regression: a corrupted glyph ("©"→NUL) in the agent-authored PR body must NOT reach execvp
        # (which raises "embedded null byte"). _run_gh sanitizes every arg — assert the argv is NUL-free.
        procs = [_proc(1, stderr=b"no pull requests found"),
                 _proc(0, stdout=b"https://github.com/o/r/pull/9")]
        with mock.patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=procs)) as ex:
            ref = await forge.open_pr("/repo", "feat/ticket-T1", "main",
                                      "feat(T1): ok", "## License\nMIT \x00 2026\n")
        self.assertEqual(ref, "https://github.com/o/r/pull/9")
        for call in ex.call_args_list:
            for arg in call.args:
                self.assertNotIn("\x00", str(arg))

    async def test_skips_when_already_merged(self) -> None:
        view = _proc(0, stdout=json.dumps(
            {"number": 7, "state": "MERGED", "baseRefName": "main", "url": "u"}).encode())
        with mock.patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=[view])) as ex:
            ref = await forge.open_pr("/repo", "feat/ticket-T1", "main", "t", "b")
        self.assertIsNone(ref)            # caller skips the merge
        self.assertEqual(ex.call_count, 1)


class MergePrTests(unittest.IsolatedAsyncioTestCase):
    async def test_admin_squash_merge(self) -> None:
        with mock.patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=[_proc(0)])) as ex:
            await forge.merge_pr("/repo", "7")
        self.assertEqual(ex.call_count, 1)
        cmd = ex.call_args_list[0].args
        for token in ("merge", "7", "--squash", "--admin", "--delete-branch"):
            self.assertIn(token, cmd)

    async def test_falls_back_to_auto_on_pending_checks(self) -> None:
        # The immediate --admin merge is refused for pending required checks → queue with --auto.
        procs = [_proc(1, stderr=b"Required status check 'ci' is expected."), _proc(0)]
        with mock.patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=procs)) as ex:
            await forge.merge_pr("/repo", "7")
        self.assertEqual(ex.call_count, 2)
        self.assertIn("--admin", ex.call_args_list[0].args)
        self.assertIn("--auto", ex.call_args_list[1].args)

    async def test_hard_failure_exits_nonzero(self) -> None:
        with mock.patch("asyncio.create_subprocess_exec",
                        new=AsyncMock(side_effect=[_proc(1, stderr=b"fatal: not authorized")])):
            with self.assertRaises(SystemExit):
                await forge.merge_pr("/repo", "7")


class ApprovePrTests(unittest.IsolatedAsyncioTestCase):
    async def test_noop_without_reviewer_token(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GITHUB_REVIEWER_TOKEN", None)
            with mock.patch("asyncio.create_subprocess_exec", new=AsyncMock()) as ex:
                approved = await forge.approve_pr("/repo", "7")
        self.assertFalse(approved)
        ex.assert_not_called()             # never even invokes gh

    async def test_swallows_gh_failure(self) -> None:
        with mock.patch.dict(os.environ, {"GITHUB_REVIEWER_TOKEN": "tok"}, clear=False):
            with mock.patch("asyncio.create_subprocess_exec",
                            new=AsyncMock(side_effect=[_proc(1, stderr=b"not authorized")])):
                approved = await forge.approve_pr("/repo", "7")   # must NOT raise
        self.assertFalse(approved)


if __name__ == "__main__":
    unittest.main()
