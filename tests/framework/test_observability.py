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
from src.shared.core.observability import (
    reconfigure_logging,
    log_token_usage,
    describe_finish_reason,
    finish_reason_name,
    NON_RETRYABLE_FINISH_REASONS,
)
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
        # E5 — plane is derived from AGENT_PLANE (no per-agent-call change); QA is a development-plane role.
        self.assertEqual(qa.plane, "development")

    def test_plane_and_duration_recorded_from_contextvar(self) -> None:
        # E5 — log_token_usage attributes the plane (via AGENT_PLANE) and reads the per-call wall-clock from
        # the ContextVar set by run_structured_llm, WITHOUT any change to its 2-tuple return.
        from src.shared.utils.llm import LAST_LLM_ELAPSED_S
        telemetry = PipelineTelemetry()
        raw = SimpleNamespace(usage_metadata=SimpleNamespace(
            prompt_token_count=100, candidates_token_count=20,
            cached_content_token_count=0, total_token_count=120, prompt_tokens_details=None,
        ))
        token = LAST_LLM_ELAPSED_S.set(3.5)
        try:
            log_token_usage(telemetry, "Product Owner Agent", raw, model_name=None)
        finally:
            LAST_LLM_ELAPSED_S.reset(token)
        po = telemetry.by_agent["Product Owner Agent"]
        self.assertEqual(po.plane, "nexus")               # PO is a control-plane role
        self.assertAlmostEqual(po.duration_seconds, 3.5)  # wall-clock sourced from the ContextVar
        self.assertAlmostEqual(telemetry.total_duration_seconds, 3.5)

    def test_duration_defaults_to_zero_when_contextvar_unset(self) -> None:
        # The mocked-call path (no run_structured_llm) leaves the var at its default → duration 0.0,
        # so existing agent-node tests that mock the LLM are unaffected (no return-shape regression).
        from src.shared.utils.llm import LAST_LLM_ELAPSED_S
        LAST_LLM_ELAPSED_S.set(0.0)
        telemetry = PipelineTelemetry()
        raw = SimpleNamespace(usage_metadata=SimpleNamespace(
            prompt_token_count=10, candidates_token_count=5,
            cached_content_token_count=0, total_token_count=15, prompt_tokens_details=None,
        ))
        log_token_usage(telemetry, "Reviewer Agent", raw, model_name=None)
        self.assertEqual(telemetry.by_agent["Reviewer Agent"].duration_seconds, 0.0)


class FinopsSummaryWallClockTests(unittest.TestCase):
    """The GRAND TOTAL must surface infra (gate/SAST/git) wall-clock + a REAL end-to-end TOTAL — not the
    LLM-only figure it printed before. Degrades to LLM-only when no infra phase was recorded."""

    def test_summary_prints_infra_phases_and_real_wall_total(self) -> None:
        from src.shared.core.observability import log_finops_summary
        tel = PipelineTelemetry()
        tel.record("QA Agent", 50, 10, 0.01, provider="gemini", plane="development", duration_seconds=2.0)
        tel.record_phase("qa+sast", 130.0)
        with self.assertLogs("SDLC", level="INFO") as cm:
            log_finops_summary(tel, 1.0)
        out = "\n".join(cm.output)
        self.assertIn("qa+sast", out)          # the per-phase infra line
        self.assertIn("infra", out)            # Σ infra time + the TOTAL's infra term
        self.assertIn("132.0s wall", out)      # 2.0 LLM + 130.0 infra = real wall-clock

    def test_summary_degrades_to_llm_only_without_phases(self) -> None:
        from src.shared.core.observability import log_finops_summary
        tel = PipelineTelemetry()
        tel.record("QA Agent", 50, 10, 0.01, provider="gemini", plane="development", duration_seconds=2.0)
        with self.assertLogs("SDLC", level="INFO") as cm:
            log_finops_summary(tel, 1.0)
        out = "\n".join(cm.output)
        self.assertIn("2.0s wall", out)        # wall == LLM time when no infra phases were recorded


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


class FinishReasonNameTests(unittest.TestCase):
    """The bare-name classifier feeds the retry layer's non-retryable decision; it must extract the
    raw reason (no hint) and return None for normal/odd completions."""

    @staticmethod
    def _completion(reason: object) -> SimpleNamespace:
        return SimpleNamespace(candidates=[SimpleNamespace(finish_reason=reason)])

    def test_recitation_name_from_instructor_exception(self) -> None:
        exc = SimpleNamespace(last_completion=self._completion(SimpleNamespace(name="RECITATION")))
        self.assertEqual(finish_reason_name(exc), "RECITATION")

    def test_enum_string_form_normalised(self) -> None:
        self.assertEqual(finish_reason_name(self._completion("FinishReason.SAFETY")), "SAFETY")

    def test_stop_and_garbage_return_none(self) -> None:
        self.assertIsNone(finish_reason_name(self._completion(SimpleNamespace(name="STOP"))))
        self.assertIsNone(finish_reason_name(object()))
        self.assertIsNone(finish_reason_name(None))

    def test_content_filters_are_non_retryable_max_tokens_is_not(self) -> None:
        # Deterministic content-filter blocks fail fast; MAX_TOKENS is a retryable truncation, not a block.
        self.assertIn("RECITATION", NON_RETRYABLE_FINISH_REASONS)
        self.assertIn("SAFETY", NON_RETRYABLE_FINISH_REASONS)
        self.assertNotIn("MAX_TOKENS", NON_RETRYABLE_FINISH_REASONS)
        self.assertNotIn("STOP", NON_RETRYABLE_FINISH_REASONS)


if __name__ == "__main__":
    unittest.main()
