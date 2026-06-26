import asyncio
import json
import re
import time
from contextvars import ContextVar
from decimal import Decimal
from typing import Any, Type

from src.shared.core.config import (
    instructor_client, structured_role_routing,
    PROVIDER_CLAUDE,
    DEVELOPER_CLI_TIMEOUT, DEVELOPER_CLI_IDLE_TIMEOUT,
)
from src.shared.core.observability import log, finish_reason_name
from src.shared.utils.api_retry import with_api_retry
from src.shared.utils.subprocess_helpers import run_claude_cli_oneshot

# Wall-clock (s) of the most recent run_structured_llm call, published per-task so log_token_usage can
# attribute time to the agent WITHOUT changing run_structured_llm's 2-tuple return (which dozens of agent
# tests hard-mock). ContextVars are copied per asyncio task, so the QA fan-out (one task per module) stays
# isolated; the set→read pair runs sequentially in the same coroutine. Defaults to 0.0 when unset (e.g.
# under a mocked run_structured_llm), so existing mocked tests are unaffected. See E5 / ADR 0022.
LAST_LLM_ELAPSED_S: ContextVar[float] = ContextVar("LAST_LLM_ELAPSED_S", default=0.0)

# instructor's Google-GenAI path hard-rejects a SYSTEM message containing Jinja-style markers
# ({{ }} / {% %}) — extract_genai_system_message in instructor/providers/gemini/utils.py raises
# unconditionally on a match. A few of our agents legitimately teach a templated-config language in
# their system prompt (the DevOps agent's GitHub Actions `${{ secrets.* }}` / `${{ vars.* }}`
# expressions). We never pass a Jinja `context`, so instructor renders nothing (templating short-circuits
# on an empty context) — the markers are pure literals and the guard is the only obstacle. Since the
# guard inspects ONLY system-role content, relocating such a system message into a user turn (where it is
# neither guard-checked nor rendered) lets the literal `{{ }}` reach the model verbatim. The pattern
# mirrors the guard's exactly (no DOTALL) so we relocate precisely the messages it would reject.
_JINJA_MARKER = re.compile(r"{{.*?}}|{%.*?%}")


def _relocate_jinja_system_messages(messages: list[dict]) -> list[dict]:
    """Demote any Jinja-marker-bearing system message to a user turn (see note above).

    Fast-path no-op for every role whose system prompt is marker-free (the list is returned unchanged),
    so existing structured calls are byte-identical; only a config-generating role is rewritten.
    """
    def _tainted(m: dict) -> bool:
        return m.get("role") == "system" and bool(_JINJA_MARKER.search(m.get("content") or ""))

    if not any(_tainted(m) for m in messages):
        return messages
    return [{**m, "role": "user"} if _tainted(m) else m for m in messages]

# Appended as an extra user turn after a RECITATION block: Gemini refused because the output reproduced
# text verbatim, so the only useful recovery is to redo the task without copying. Follows the hint in
# the RECITATION finish-reason rather than retrying the identical (and identically-blocked) prompt.
RECITATION_GUARD = (
    "IMPORTANT — RECITATION GUARD: your previous response was blocked by the recitation filter for "
    "reproducing text verbatim. Redo the task WITHOUT copying any text word-for-word: paraphrase all "
    "narrative content in your own words, and reference long canonical/boilerplate blocks (licenses, "
    ".gitignore, scaffolds) rather than reproducing them in full."
)


async def run_structured_llm(
    role: str,
    response_model: Type[Any],
    messages: list[dict],
) -> tuple:
    """Run a structured (instructor) LLM call for the given agent role.

    Resolves model + retry label from ROLE_MODELS, retries transient errors with backoff, and
    bridges the blocking instructor call onto a worker thread. Returns the
    (parsed_model, raw_response) tuple from create_with_completion.

    The client/model are resolved per the active provider (``structured_role_routing``): Gemini via the
    shared ``instructor_client`` (default/gemini); or the **Claude Code CLI** one-shot JSON adapter
    (provider=claude — see ``_run_structured_via_claude_cli``). The RECITATION recovery below is
    Gemini-specific and never triggers on the Claude path.

    On a Gemini RECITATION block (deterministic — ``with_api_retry`` fails it fast), makes ONE
    paraphrase-guarded retry that appends ``RECITATION_GUARD`` to the messages. A second block (or any
    other failure) propagates so the caller halts with the actionable hint.
    """
    model_name, agent_name, provider = structured_role_routing(role)

    # provider=claude: the subscription Claude Code CLI answers the structured roles in a one-shot JSON
    # mode — no API key, no instructor. Timed the same way so log_token_usage attributes wall-clock.
    if provider == PROVIDER_CLAUDE:
        start = time.perf_counter()
        try:
            return await _run_structured_via_claude_cli(agent_name, response_model, messages, model_name)
        finally:
            LAST_LLM_ELAPSED_S.set(time.perf_counter() - start)

    # Gemini uses the module-global instructor_client (also the patch point for the unit tests).

    @with_api_retry(max_retries=3, agent_name=agent_name)
    async def _invoke(msgs: list[dict]) -> tuple:
        safe_msgs = _relocate_jinja_system_messages(msgs)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: instructor_client.chat.completions.create_with_completion(
                model=model_name,
                response_model=response_model,
                messages=safe_msgs,
            ),
        )

    start = time.perf_counter()
    try:
        try:
            return await _invoke(messages)
        except Exception as e:
            if finish_reason_name(e) != "RECITATION":
                raise
            log.warning(f"{agent_name} blocked by RECITATION — retrying once with a paraphrase directive.")
            guarded = messages + [{"role": "user", "content": RECITATION_GUARD}]
            return await _invoke(guarded)
    finally:
        # Publish total wall-clock (incl. retries/backoff) for log_token_usage to attribute to this role.
        LAST_LLM_ELAPSED_S.set(time.perf_counter() - start)


# ==========================================
# STRUCTURED OUTPUT VIA THE CLAUDE CODE CLI (provider=claude — subscription, no API key)
# ==========================================
# How many times the CLI is re-prompted to return schema-valid JSON before giving up (each retry feeds the
# validation error back). Small: the CLI almost always complies on the first or second try.
_CLI_STRUCTURED_MAX_ATTEMPTS = 3

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class _ClaudeCliRaw:
    """Raw-response stand-in for a Claude-CLI structured call: carries the (authoritative) usage dict so
    ``observability.log_token_usage`` records it via its ``claude_cli_usage`` branch — letting the existing
    agent nodes' ``log_token_usage(...)`` calls work unchanged on the CLI path."""
    def __init__(self, usage: dict | None):
        self.claude_cli_usage = usage


def _messages_to_prompt(messages: list[dict]) -> str:
    """Flatten the chat messages into a single prompt for the CLI's ``-p`` print mode (no roles channel)."""
    return "\n\n".join(f"{(m.get('role') or 'user').upper()}:\n{m.get('content') or ''}" for m in messages)


def _extract_json_object(text: str) -> str:
    """Best-effort pull of the single JSON object out of the CLI's free-text answer: prefer a fenced
    block, else slice from the first ``{`` to the last ``}``. Returns the raw candidate (validated upstream)."""
    if not text:
        return ""
    fenced = _JSON_FENCE_RE.search(text)
    if fenced:
        return fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if 0 <= start < end else text.strip()


async def _run_structured_via_claude_cli(
    agent_name: str, response_model: Type[Any], messages: list[dict], model: str,
) -> tuple:
    """Drive one structured role through the Claude Code CLI: embed the model's JSON Schema in the prompt,
    one-shot the CLI, extract + validate the JSON, and re-prompt with the validation error on a miss.

    Primary path: the CLI's native ``--json-schema`` structured output (the validated object arrives in
    the result envelope's ``structured_output``) — reliable, no free-text JSON parsing. Fallback (if the
    CLI didn't honor the schema, e.g. an unsupported `$ref`): extract + validate the JSON from the answer
    text. Either way the validation error is fed back and the call retried.

    Returns ``(parsed_model, _ClaudeCliRaw)`` — the raw carries the summed usage across attempts so the
    caller's ``log_token_usage`` bills the role authoritatively. Raises after the attempt budget."""
    schema = response_model.model_json_schema()
    schema_str = json.dumps(schema, ensure_ascii=False)
    base = _messages_to_prompt(messages)
    directive = (
        "\n\n=== OUTPUT FORMAT (STRICT) ===\n"
        "Respond with ONE single, COMPLETE JSON object and NOTHING else — no prose, no explanation, no "
        "markdown code fences. Emit it as minified JSON on a single line. Inside every string value you "
        "MUST escape each double quote as \\\" and each newline as \\n (never an unescaped \" or a literal "
        "newline). Finish the object — the final character must be the closing }. Do NOT truncate. It MUST "
        "validate against this JSON Schema:\n" + schema_str
    )
    agg = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
           "cache_write_tokens": 0, "cost_usd": Decimal(0)}
    prompt = base + directive
    last_err: Exception | None = None
    last_text = ""
    for attempt in range(1, _CLI_STRUCTURED_MAX_ATTEMPTS + 1):
        text, structured, usage = await run_claude_cli_oneshot(
            prompt, model=model, json_schema=schema,
            timeout=DEVELOPER_CLI_TIMEOUT, idle_timeout=DEVELOPER_CLI_IDLE_TIMEOUT,
        )
        last_text = text
        if usage:
            for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"):
                agg[k] += usage.get(k, 0)
            agg["cost_usd"] += usage.get("cost_usd", Decimal(0))
        try:
            # Prefer the CLI's native schema-validated object; fall back to parsing the free-text answer.
            parsed = (response_model.model_validate(structured) if structured is not None
                      else response_model.model_validate_json(_extract_json_object(text)))
            return parsed, _ClaudeCliRaw(agg)
        except Exception as e:  # validation / JSON parse error → feed it back and retry
            last_err = e
            log.warning(f"{agent_name} (Claude CLI) returned invalid output on attempt "
                        f"{attempt}/{_CLI_STRUCTURED_MAX_ATTEMPTS}: {e}")
            prompt = (base + directive + f"\n\n=== CORRECTION (attempt {attempt} was rejected) ===\n"
                      f"Your previous reply did not validate against the schema: {e}\n"
                      "Output ONLY the corrected single JSON object.")
    raise ValueError(
        f"{agent_name}: Claude Code CLI did not return schema-valid output after "
        f"{_CLI_STRUCTURED_MAX_ATTEMPTS} attempts (last error: {last_err}). "
        f"Last answer tail: …{last_text[-200:]!r}"
    )
