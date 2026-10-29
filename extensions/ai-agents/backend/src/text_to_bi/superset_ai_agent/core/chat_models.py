from functools import lru_cache

from langchain_openai import ChatOpenAI

from .config import settings
from .exceptions import ChatModelNotConfiguredError


@lru_cache(maxsize=1)
def get_chat_model() -> ChatOpenAI:
    """The OpenRouter chat model every agent step uses; raises ChatModelNotConfiguredError without an API key."""
    if not settings.OPENROUTER_API_KEY:
        raise ChatModelNotConfiguredError()
    return ChatOpenAI(
        model=settings.OPENROUTER_MODEL,
        temperature=0.0,
        max_tokens=4096,
        # Each step's instructions spell out what to decide, so long hidden reasoning only adds seconds to the answer.
        reasoning_effort="low",
        api_key=settings.OPENROUTER_API_KEY,
        base_url=settings.OPENROUTER_BASE_URL,
    )
