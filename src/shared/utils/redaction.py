"""Central secret-redaction gate.

One place that scrubs credentials (PATs, basic-auth URLs, bearer tokens, known env-var secret values)
out of any text before it is logged or persisted, so a token embedded in a clone URL like
``https://ghp_xxx@github.com/owner/repo.git`` can never reach the audit log or an incident report.

Used by the logging ``RedactionFilter`` (covers every console + file log record) and by explicit
call sites that write to disk outside the logging layer (e.g. the incident report).
"""
import logging
import os
import re
from functools import lru_cache
from typing import Iterable

# Order matters: URL credentials first (keeps the host), then bare tokens, then auth headers.
_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    # scheme://<token>@host  or  scheme://user:pass@host  -> scheme://***@host
    # The `[^/\s@]+` (no slash) before `@` keeps this anchored to the userinfo, never a path `@handle`.
    (re.compile(r"(https?://)[^/\s@]+@"), r"\1***@"),
    # GitHub PATs: ghp_/gho_/ghu_/ghs_/ghr_ classic tokens and fine-grained github_pat_ tokens.
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "***"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "***"),
    # Bearer tokens and Authorization headers.
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"), "Bearer ***"),
    (re.compile(r"(?i)(authorization:\s*)\S.*"), r"\1***"),
)

# Env vars whose VALUES are secret and must be scrubbed wherever they appear (e.g. an API key that
# surfaces inside a third-party exception trace). Matched by name suffix/exact name.
_SECRET_NAME_RE = re.compile(r"(_TOKEN|_KEY|_SECRET|_PASSWORD)$|^(GITHUB_TOKEN|GH_TOKEN|GEMINI_API_KEY)$")
_MIN_SECRET_LEN = 8


@lru_cache(maxsize=1)
def secret_env_values() -> frozenset[str]:
    """Non-empty values (len >= 8) of env vars whose NAME marks them secret. Cached on first use so the
    process env (including a late-loaded ``.env``) is fully populated by the time it is read."""
    return frozenset(
        v for name, v in os.environ.items()
        if v and len(v) >= _MIN_SECRET_LEN and _SECRET_NAME_RE.search(name)
    )


def redact(text: str, extra_secrets: Iterable[str] = ()) -> str:
    """Return *text* with credentials/tokens replaced by ``***``. Idempotent; safe on non-secret text."""
    if not text:
        return text
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    for secret in extra_secrets:
        if secret and len(secret) >= _MIN_SECRET_LEN:
            text = text.replace(secret, "***")
    return text


class RedactionFilter(logging.Filter):
    """Logger-level filter that scrubs secrets from every record before any handler formats it.

    Mutates ``record.msg`` to the fully-rendered, redacted message and clears ``record.args`` (the
    standard mutate-in-filter pattern), so both the console and the audit-file handler emit redacted
    text. Non-string ``msg`` (rare) is left untouched.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.getMessage(), secret_env_values())
            record.args = ()
        return True
