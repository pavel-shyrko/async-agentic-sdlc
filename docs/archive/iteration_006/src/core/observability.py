import sys
import logging
from logging.handlers import RotatingFileHandler
from typing import Any

from src.core.models import LOGS_DIR

# ==========================================
# OBSERVABILITY & AUDIT LOGGING
# ==========================================
def setup_observability():
    """Configures dual-channel logging: clean CLI output and verbose file tracing."""
    logger = logging.getLogger("SDLC")
    logger.setLevel(logging.DEBUG)

    # Avoid duplicate handlers on re-runs
    if not logger.handlers:
        # CLI Handler (INFO)
        c_handler = logging.StreamHandler(sys.stdout)
        c_handler.setLevel(logging.INFO)
        c_handler.setFormatter(logging.Formatter('%(message)s'))

        # Persistent Audit Trail (DEBUG)
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        f_handler = RotatingFileHandler(str(LOGS_DIR / "sdlc_audit.log"), maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")
        f_handler.setLevel(logging.DEBUG)
        f_handler.setFormatter(logging.Formatter('[%(asctime)s] [%(levelname)s] [%(funcName)s] %(message)s'))

        logger.addHandler(c_handler)
        logger.addHandler(f_handler)

    return logger

log = setup_observability()

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
