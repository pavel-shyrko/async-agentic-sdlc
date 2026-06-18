"""Unit tests for per-session audit-log reconfiguration.

reconfigure_logging mutates the process-global ``SDLC`` logger, so each test closes the
temp-dir handler and restores a working global handler in ``finally`` — both to keep other
suites unaffected and to release the Windows file lock before the temp dir is removed.
"""
import logging
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory, mkdtemp
from types import SimpleNamespace
from logging.handlers import RotatingFileHandler

import io

from src.shared.core.models import GlobalPipelineContext, PipelineTelemetry
from src.shared.core.observability import reconfigure_logging, log_token_usage, describe_finish_reason
from src.shared.utils.redaction import RedactionFilter


class RedactionFilterInstalledTests(unittest.TestCase):
    """The security gate must be wired onto the shared SDLC logger so every record is scrubbed."""

    def test_redaction_filter_attached_to_logger(self) -> None:
        logger = logging.getLogger("SDLC")
        self.assertTrue(any(isinstance(f, RedactionFilter) for f in logger.filters))

    def test_logged_pat_url_is_redacted_in_output(self) -> None:
        logger = logging.getLogger("SDLC")
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        try:
            logger.info("[GIT] Shallow-cloned %s -> repo", "https://ghp_FAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE@github.com/o/r.git")
            out = stream.getvalue()
            self.assertNotIn("ghp_FAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE", out)
            self.assertIn("https://***@github.com/o/r.git", out)
        finally:
            logger.removeHandler(handler)
            handler.close()


class ReconfigureLoggingTests(unittest.TestCase):
    """reconfigure_logging re-points the audit file handler per session, keeping the console."""

    @classmethod
    def setUpClass(cls) -> None:
        # A stable scratch dir to re-anchor the global handler onto in each test's `finally`,
        # releasing the Windows lock on the per-test temp dir before it is cleaned up.
        cls._restore_dir = Path(mkdtemp(prefix="sdlc-audit-restore-"))

    @classmethod
    def tearDownClass(cls) -> None:
        logger = logging.getLogger("SDLC")
        for handler in [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]:
            handler.close()
            logger.removeHandler(handler)
        shutil.rmtree(cls._restore_dir, ignore_errors=True)

    def test_swaps_file_handler_and_preserves_console(self) -> None:
        # Arrange
        logger = logging.getLogger("SDLC")
        td = TemporaryDirectory()
        try:
            new_dir = Path(td.name) / "session-logs"
            # Act
            reconfigure_logging(new_dir)

            # Assert — exactly one audit file handler, now anchored in the session dir.
            file_handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
            console_handlers = [
                h for h in logger.handlers
                if isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler)
            ]
            self.assertEqual(len(file_handlers), 1, "exactly one audit file handler expected")
            self.assertEqual(Path(file_handlers[0].baseFilename).resolve().parent, new_dir.resolve())
            # Append mode is mandatory: a resumed run must continue the SAME log, never truncate it.
            self.assertEqual(file_handlers[0].mode, "a")
            # Console handler must survive the swap.
            self.assertGreaterEqual(len(console_handlers), 1, "console handler must be preserved")
            # The session logs dir is created eagerly.
            self.assertTrue(new_dir.is_dir())
        finally:
            # Close the temp-dir handler and restore a global audit handler before cleanup.
            reconfigure_logging(self._restore_dir)
            td.cleanup()


class LogTokenUsageTests(unittest.TestCase):
    """Gemini telemetry must exclude cached tokens from the budget, mirroring the Claude path."""

    def test_gemini_cached_tokens_excluded_from_budget_and_tracked_separately(self) -> None:
        # Arrange — prompt_token_count INCLUDES cached (2000 = 500 fresh + 1500 cached).
        telemetry = PipelineTelemetry()
        raw = SimpleNamespace(usage_metadata=SimpleNamespace(
            prompt_token_count=2000,
            candidates_token_count=400,
            cached_content_token_count=1500,
            total_token_count=2400,
            prompt_tokens_details=None,
        ))
        # Act — telemetry-first signature; model_name=None keeps cost at 0 and avoids the genai dependency.
        log_token_usage(telemetry, "QA Agent", raw, model_name=None)
        # Assert — budgeted total = fresh(500) + output(400); cache tracked but NOT budgeted.
        self.assertEqual(telemetry.total_tokens, 900)
        self.assertEqual(telemetry.total_cache_read_tokens, 1500)
        qa = telemetry.by_agent["QA Agent"]
        self.assertEqual((qa.input_tokens, qa.output_tokens, qa.cache_read_tokens), (500, 400, 1500))


class DescribeFinishReasonTests(unittest.TestCase):
    """The finish_reason diagnostic must name a content-filter block (the RECITATION crash cause)
    and return None for a normal completion — never raising on odd shapes."""

    @staticmethod
    def _completion(reason: object) -> SimpleNamespace:
        return SimpleNamespace(candidates=[SimpleNamespace(finish_reason=reason)])

    def test_recitation_on_instructor_exception_yields_hint(self) -> None:
        # Mirror instructor's InstructorRetryException carrying the raw genai completion.
        exc = SimpleNamespace(last_completion=self._completion(SimpleNamespace(name="RECITATION")))
        desc = describe_finish_reason(exc)
        self.assertIsNotNone(desc)
        self.assertIn("RECITATION", desc)
        self.assertIn("rephrase", desc.lower())

    def test_enum_string_form_is_parsed(self) -> None:
        # finish_reason rendered as the enum's str form, e.g. "FinishReason.SAFETY".
        desc = describe_finish_reason(self._completion("FinishReason.SAFETY"))
        self.assertIsNotNone(desc)
        self.assertTrue(desc.startswith("SAFETY"))

    def test_stop_returns_none(self) -> None:
        self.assertIsNone(describe_finish_reason(self._completion(SimpleNamespace(name="STOP"))))

    def test_garbage_returns_none(self) -> None:
        self.assertIsNone(describe_finish_reason(object()))
        self.assertIsNone(describe_finish_reason(None))


if __name__ == "__main__":
    unittest.main()
