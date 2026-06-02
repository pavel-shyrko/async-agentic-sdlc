import sys
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Any

# Shared audit-file handler config — kept in one place so setup and reconfigure stay in sync.
_AUDIT_FILENAME = "sdlc_audit.log"
_AUDIT_MAX_BYTES = 5 * 1024 * 1024
_AUDIT_BACKUPS = 3
_AUDIT_FORMAT = logging.Formatter('[%(asctime)s] [%(levelname)s] [%(funcName)s] %(message)s')


def _build_audit_handler(log_dir: Path) -> RotatingFileHandler:
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        str(log_dir / _AUDIT_FILENAME),
        mode="a",  # append — never truncate, so a resumed run continues the same linear audit log
        maxBytes=_AUDIT_MAX_BYTES,
        backupCount=_AUDIT_BACKUPS,
        encoding="utf-8",
    )
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(_AUDIT_FORMAT)
    return handler

# ==========================================
# OBSERVABILITY & AUDIT LOGGING
# ==========================================
def setup_observability():
    """Configures the CLI (StreamHandler) channel only.

    The persistent audit-file handler is intentionally NOT attached here: doing so at import
    time would create ``sdlc_audit.log`` (and its parent dir) at the project root merely as a
    side effect of importing this module. ``reconfigure_logging`` attaches the
    RotatingFileHandler lazily during ``main()`` once the per-run logs dir is known.
    """
    logger = logging.getLogger("SDLC")
    logger.setLevel(logging.DEBUG)

    # Avoid duplicate handlers on re-runs
    if not logger.handlers:
        # CLI Handler (INFO)
        c_handler = logging.StreamHandler(sys.stdout)
        c_handler.setLevel(logging.INFO)
        c_handler.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(c_handler)

    return logger

log = setup_observability()


def reconfigure_logging(new_log_dir: Path) -> None:
    """Redirects the audit trail to a per-run logs directory.

    Swaps the global RotatingFileHandler for one anchored at ``new_log_dir`` (the console
    StreamHandler is preserved) so each ``runs/run_<uuid>/`` session writes its own audit log
    instead of all instances racing on the single global file. Idempotent across re-entry.
    """
    logger = logging.getLogger("SDLC")
    for handler in list(logger.handlers):
        if isinstance(handler, RotatingFileHandler):
            logger.removeHandler(handler)
            handler.close()
    logger.addHandler(_build_audit_handler(Path(new_log_dir)))

# ==========================================
# TOKEN OBSERVABILITY HELPER
# ==========================================
def log_token_usage(agent_name: str, raw_response: Any):
    """Extracts and logs token usage from Gemini API raw responses."""
    try:
        if hasattr(raw_response, 'usage_metadata') and raw_response.usage_metadata:
            usage = raw_response.usage_metadata
            in_tokens = getattr(usage, 'prompt_token_count', 0)
            out_tokens = getattr(usage, 'candidates_token_count', 0)
            total = getattr(usage, 'total_token_count', in_tokens + out_tokens)
            log.info(f"   [TOKENS] {agent_name} | Input: {in_tokens} | Output: {out_tokens} | Total: {total}")
    except Exception as e:
        log.debug(f"Failed to parse token usage for {agent_name}: {e}")
