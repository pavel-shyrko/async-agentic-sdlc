import asyncio
from typing import Any, Type

from src.shared.core.config import instructor_client, ROLE_MODELS
from src.shared.utils.api_retry import with_api_retry


async def run_structured_llm(
    role: str,
    response_model: Type[Any],
    messages: list[dict],
) -> tuple:
    """Run a structured (instructor) LLM call for the given agent role.

    Resolves model + retry label from ROLE_MODELS, retries with backoff, and
    bridges the blocking instructor call onto a worker thread. Returns the
    (parsed_model, raw_response) tuple from create_with_completion.
    """
    model_name, agent_name = ROLE_MODELS[role]

    @with_api_retry(max_retries=3, agent_name=agent_name)
    async def _invoke() -> tuple:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: instructor_client.chat.completions.create_with_completion(
                model=model_name,
                response_model=response_model,
                messages=messages,
            ),
        )

    return await _invoke()
