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
from logging.handlers import RotatingFileHandler

from src.core.observability import reconfigure_logging


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


if __name__ == "__main__":
    unittest.main()
