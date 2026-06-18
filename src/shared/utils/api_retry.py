import sys
import asyncio
import functools
from typing import TypeVar, Callable, Awaitable, Any

from google.genai.errors import ClientError

from src.shared.core.config import handle_quota_error
from src.shared.core.observability import log, describe_finish_reason

T = TypeVar("T")


def _diagnose(exc: Exception) -> str:
    """One-line cause for the log: the genai finish_reason (e.g. RECITATION + hint) when present,
    else the exception type — so a content-filter block reads clearly and a plain error still does."""
    return describe_finish_reason(exc) or type(exc).__name__


def with_api_retry(max_retries: int = 3, agent_name: str = "Agent") -> Callable:
    """Async decorator encapsulating exponential backoff retry logic for LLM API calls.

    Handles 429 quota errors immediately (no retry). All other errors are retried
    up to max_retries times with 2^attempt second backoff.
    """
    def decorator(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            for attempt in range(1, max_retries + 1):
                try:
                    return await fn(*args, **kwargs)
                except ClientError as e:
                    if e.status_code == 429:
                        handle_quota_error(e)
                        sys.exit(1)
                    reason = _diagnose(e)
                    if attempt == max_retries:
                        log.error(f"🚨 CRITICAL: {agent_name} API call failed after {max_retries} attempts — {reason}.")
                        raise
                    log.warning(f"{agent_name} attempt {attempt}/{max_retries} failed ({reason}) — retrying...")
                    await asyncio.sleep(2 ** attempt)
                except Exception as e:
                    reason = _diagnose(e)
                    if attempt == max_retries:
                        log.error(f"🚨 CRITICAL: {agent_name} API call failed after {max_retries} attempts — {reason}.")
                        raise
                    log.warning(f"{agent_name} attempt {attempt}/{max_retries} failed ({reason}) — retrying...")
                    await asyncio.sleep(2 ** attempt)
        return wrapper
    return decorator
