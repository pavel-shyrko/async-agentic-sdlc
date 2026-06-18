import asyncio
from typing import Any, Type

from src.shared.core.config import instructor_client, ROLE_MODELS
from src.shared.core.observability import log, finish_reason_name
from src.shared.utils.api_retry import with_api_retry

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
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: instructor_client.chat.completions.create_with_completion(
                model=model_name,
                response_model=response_model,
                messages=msgs,
            ),
        )

    try:
        return await _invoke(messages)
    except Exception as e:
        if finish_reason_name(e) != "RECITATION":
            raise
        log.warning(f"{agent_name} blocked by RECITATION — retrying once with a paraphrase directive.")
        guarded = messages + [{"role": "user", "content": RECITATION_GUARD}]
        return await _invoke(guarded)
