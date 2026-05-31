import os
import sys
import shutil
import instructor
from google import genai
from google.genai.errors import ClientError

from src.core.observability import log
from src.core.models import ARTIFACTS_DIR, CODE_DIR, TESTS_DIR, LOGS_DIR, REPORTS_DIR  # noqa: F401  (central directory map)

# ==========================================
# MODEL ROUTING (single source of truth)
# ==========================================
ARCHITECT_MODEL = "gemini-2.5-flash"
QA_MODEL = "gemini-2.5-flash"
REVIEWER_MODEL = "gemini-2.5-flash"
DEVELOPER_MODEL_LABEL = "Claude CLI Wrapper"  # real model is managed by the Claude CLI config

# ==========================================
# ENVIRONMENT CHECKER
# ==========================================
def check_environment():
    log.info("🔍 Pre-flight environment check...")
    for tool in ["docker", "claude", "bandit"]:
        if not shutil.which(tool):
            log.error(f"🚨 CRITICAL: Binary '{tool}' not found in PATH.")
            sys.exit(1)

    if not os.environ.get("GEMINI_API_KEY"):
        log.error("🚨 CRITICAL: GEMINI_API_KEY is not set.")
        sys.exit(1)

    # Container hardening: in docker mode the framework source must be immutable so the
    # Developer agent cannot mutate the pipeline itself (mount src/ :ro or run as non-root).
    if os.environ.get("RUNTIME_ENV") == "docker":
        if os.access("src", os.W_OK):
            log.error("🚨 CRITICAL: RUNTIME_ENV=docker but 'src/' is writable. "
                      "Mount it read-only (:ro) or run as a non-root user to prevent self-mutation.")
            sys.exit(1)
        log.info("  ✓ src/ confirmed read-only (container hardening).")

    log.info("  ✓ Environment verified.\n")

# ==========================================
# GENAI / INSTRUCTOR CLIENT SINGLETONS
# ==========================================
def get_genai_client() -> genai.Client:
    """Returns the module-level Google AI Studio client singleton."""
    return _genai_client


def _build_genai_client() -> genai.Client:
    log.debug("Initializing Google AI Studio client via GEMINI_API_KEY")
    return genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))


_genai_client: genai.Client = _build_genai_client()

instructor_client: instructor.Instructor = instructor.from_genai(
    client=_genai_client,
    mode=instructor.Mode.GENAI_STRUCTURED_OUTPUTS,
)

# ==========================================
# HELPER FOR GRACEFUL QUOTA ERROR HANDLING
# ==========================================
def handle_quota_error(e: ClientError):
    log.error("\n🚨 RATE LIMIT EXHAUSTED (429) DETECTED!")
    log.error("   Your project is currently hitting the Google AI Studio quota limit.")
    log.error("   Ensure your AI Studio project is on a Pay-as-you-go plan.")
    log.error("\n   Details:")
    log.error(f"   {e}")
