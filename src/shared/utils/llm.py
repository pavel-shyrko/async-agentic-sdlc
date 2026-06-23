import asyncio
import re
import time
from contextvars import ContextVar
from typing import Any, Type

from src.shared.core.config import instructor_client, ROLE_MODELS
from src.shared.core.observability import log, finish_reason_name
from src.shared.utils.api_retry import with_api_retry

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

    On a Gemini RECITATION block (deterministic — ``with_api_retry`` fails it fast), makes ONE
    paraphrase-guarded retry that appends ``RECITATION_GUARD`` to the messages. A second block (or any
    other failure) propagates so the caller halts with the actionable hint.
    """
    model_name, agent_name = ROLE_MODELS[role]

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
