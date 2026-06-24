import sys
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Any

from src.shared.utils.redaction import RedactionFilter

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

    # Security gate: a logger-level filter runs once in Logger.handle() before EITHER handler formats
    # the record, so secrets (PATs, basic-auth URLs, bearer/API-key values) are scrubbed from BOTH the
    # console and the audit file, and it survives reconfigure_logging() (which only swaps handlers).
    if not any(isinstance(f, RedactionFilter) for f in logger.filters):
        logger.addFilter(RedactionFilter())

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
def log_token_usage(telemetry: Any, agent_name: str, raw_response: Any, model_name: str | None = None):
    """Extracts Gemini token usage, records it (with estimated cost) into telemetry, and logs it.

    Records into ``telemetry`` (a ``PipelineTelemetry``) so the cumulative total feeds the Financial
    Circuit Breaker. Telemetry-first (not ``ctx``) so any caller with a bare telemetry object — the
    executor (``ctx.telemetry``) AND the Nexus control plane — uses the identical logger. When
    ``model_name`` is given, the call's USD cost is estimated (cache-aware + tiered) and accumulated.
    The ``usage_metadata`` guard keeps mocked responses (tests) safe — they record nothing;
    ``model_name=None`` keeps the cost at 0.
    """
    try:
        if hasattr(raw_response, 'usage_metadata') and raw_response.usage_metadata:
            usage = raw_response.usage_metadata
            prompt_tokens = getattr(usage, 'prompt_token_count', 0) or 0
            out_tokens = getattr(usage, 'candidates_token_count', 0) or 0
            cached = getattr(usage, 'cached_content_token_count', 0) or 0
            # Gemini's prompt_token_count INCLUDES cached tokens; split them out so the budget counts
            # only fresh input + output (parity with Claude). Cache is tracked separately, not budgeted.
            fresh_in = max(prompt_tokens - cached, 0)
            cost_usd = 0.0
            if model_name:
                from src.shared.core.config import estimate_gemini_cost_usd  # lazy: avoid config↔observability cycle
                cost_usd = estimate_gemini_cost_usd(model_name, usage)
            # Plane attribution (report-time rollup) + per-call wall-clock — both sourced WITHOUT changing
            # run_structured_llm's return contract (lazy imports avoid the config/llm ↔ observability cycles).
            from src.shared.core.config import AGENT_PLANE
            from src.shared.utils.llm import LAST_LLM_ELAPSED_S
            telemetry.record(
                agent_name, fresh_in, out_tokens, cost_usd, provider="gemini",
                cache_read_tokens=cached,  # Gemini implicit caching reports no separate write count
                plane=AGENT_PLANE.get(agent_name, "development"),
                duration_seconds=LAST_LLM_ELAPSED_S.get(),
            )
            cache_part = f"Cache-read: {cached} | " if cached else ""
            log.info(
                f"   [TOKENS] {agent_name} | Input(fresh): {fresh_in} | {cache_part}"
                f"Output: {out_tokens} | Budgeted: {fresh_in + out_tokens} | "
                f"Cost: ${cost_usd:.4f} | Cumulative: {telemetry.total_tokens}t / "
                f"${telemetry.total_cost_usd:.4f}"
            )
    except Exception as e:
        log.debug(f"Failed to parse token usage for {agent_name}: {e}")


def log_finops_summary(telemetry: Any, budget_usd: Any) -> None:
    """Print the end-of-run ``📊 [FINOPS] GRAND TOTAL`` block: per-agent (tokens/cost/time), per-plane and
    per-provider subtotals, and the money budget utilisation. Telemetry-first + explicit budget so the
    executor, the Nexus control plane, and the E3 batch render the identical block from the same code.

    Budget is money-only (E5): tokens + time are reported, the USD ceiling is the sole gate.
    """
    tel = telemetry
    log.info("📊 [FINOPS] GRAND TOTAL")
    for name, u in tel.by_agent.items():
        log.info(
            f"   ├─ {name} ({u.provider}, {u.plane}) | {u.total_tokens}t | ${u.cost_usd:.4f} "
            f"| {u.duration_seconds:.1f}s | calls: {u.calls}"
        )
    for plane, agg in tel.by_plane().items():
        log.info(
            f"   ├─ Σ plane:{plane} | {int(agg['tokens'])}t | ${agg['cost_usd']:.4f} "
            f"| {agg['duration_seconds']:.1f}s | calls: {agg['calls']}"
        )
    for prov, agg in tel.by_provider().items():
        label = "Gemini (est.)" if prov == "gemini" else "Claude (actual)"
        log.info(f"   ├─ Σ {label} | {int(agg['tokens'])}t | ${agg['cost_usd']:.4f}")
    if tel.total_cache_read_tokens or tel.total_cache_write_tokens:
        log.info(
            f"   ├─ cache (not budgeted) | read {tel.total_cache_read_tokens}t "
            f"| write {tel.total_cache_write_tokens}t"
        )
    # Infra (non-LLM) wall-clock: docker gates / SAST / git / PR — previously invisible in this summary,
    # which counted LLM time only. by_phase/total_infra_seconds default to {}/0.0 on older checkpoints.
    by_phase = getattr(tel, "by_phase", {})
    infra_seconds = getattr(tel, "total_infra_seconds", 0.0)
    for phase, p in by_phase.items():
        log.info(f"   ├─ ⛁ {phase} | {p.duration_seconds:.1f}s | runs: {p.calls}")
    if by_phase:
        log.info(f"   ├─ Σ LLM time | {tel.total_duration_seconds:.1f}s")
        log.info(f"   ├─ Σ infra time (gates/sast/git) | {infra_seconds:.1f}s")
    used_pct_usd = (100.0 * float(tel.total_cost_usd) / float(budget_usd)) if budget_usd else 0.0
    wall_seconds = getattr(tel, "total_wall_seconds", tel.total_duration_seconds)
    log.info(
        f"   └─ TOTAL | ${tel.total_cost_usd:.4f} / ${budget_usd:.2f} budget ({used_pct_usd:.1f}%) "
        f"| {tel.total_tokens}t (reported) | {tel.total_duration_seconds:.1f}s LLM "
        f"+ {infra_seconds:.1f}s infra = {wall_seconds:.1f}s wall"
    )


# Genai finish-reason → operator hint. The content-filter reasons are DETERMINISTIC (a retry produces
# the same block), so the hint says so. Keys are matched case-insensitively against the reason name.
_FINISH_REASON_HINTS = {
    "RECITATION": "Gemini blocked the output (recitation filter — generated text matched training "
                  "data). Retrying won't help; rephrase the idea/prompt or reduce verbatim quoting.",
    "SAFETY": "Gemini blocked the output (safety filter). Retrying won't help; rephrase the request.",
    "BLOCKLIST": "Gemini blocked the output (term blocklist). Retrying won't help; rephrase the request.",
    "PROHIBITED_CONTENT": "Gemini blocked the output (prohibited content). Retrying won't help; rephrase.",
    "SPII": "Gemini blocked the output (sensitive personal info). Retrying won't help; rephrase.",
    "MAX_TOKENS": "Gemini hit the output token cap before finishing — the response was truncated.",
}

# Content-filter finish_reasons that a plain retry CANNOT recover (the same prompt yields the same
# block). The retry layer fails fast on these instead of burning the full backoff budget; RECITATION
# alone is additionally given one paraphrase-guarded retry in ``run_structured_llm``.
NON_RETRYABLE_FINISH_REASONS = frozenset(
    {"RECITATION", "SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"}
)


def finish_reason_name(obj: Any) -> str | None:
    """Best-effort, never-raising extraction of the bare genai ``finish_reason`` NAME from either a raw
    response or an ``instructor`` exception.

    Accepts: a genai ``GenerateContentResponse`` (``.candidates[0].finish_reason``) or an
    ``InstructorRetryException`` (``.last_completion`` / the last of ``.failed_attempts``). Returns the
    upper-cased reason name (e.g. ``"RECITATION"``) for a non-trivial block, else ``None`` (normal
    ``STOP`` / empty / missing). This is the classification primitive; ``describe_finish_reason`` adds
    the operator hint on top.
    """
    try:
        candidates = getattr(obj, "candidates", None)
        if candidates is None:
            # instructor exception: dig out the underlying completion it carried.
            completion = getattr(obj, "last_completion", None)
            if completion is None:
                attempts = getattr(obj, "failed_attempts", None) or []
                if attempts:
                    completion = getattr(attempts[-1], "completion", None)
            candidates = getattr(completion, "candidates", None)
        if not candidates:
            return None
        reason = getattr(candidates[0], "finish_reason", None)
        if reason is None:
            return None
        # FinishReason may be an enum (``FinishReason.RECITATION``) or a string.
        name = getattr(reason, "name", None) or str(reason).rsplit(".", 1)[-1]
        name = name.upper()
        if name in ("STOP", ""):  # normal completion — nothing to report
            return None
        return name
    except Exception:
        return None


def describe_finish_reason(obj: Any) -> str | None:
    """Best-effort, never-raising extraction of a genai ``finish_reason`` (+ a hint) from either a raw
    response or an ``instructor`` exception, for logging WHY a structured call failed.

    Returns a string like ``"RECITATION — <hint>"`` when a non-trivial reason is found, else ``None``.
    """
    name = finish_reason_name(obj)
    if name is None:
        return None
    hint = _FINISH_REASON_HINTS.get(name)
    return f"{name} — {hint}" if hint else name
