import os
from functools import lru_cache

from langchain_openai import ChatOpenAI


@lru_cache(maxsize=1)
def get_chat_model() -> ChatOpenAI:
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY chưa được cấu hình. Đặt biến này trong extensions/ai-agents/.env "
            "rồi khởi động lại dịch vụ superset."
        )
    return ChatOpenAI(
        model="openai/gpt-6-luna",
        temperature=0.0,
        max_tokens=4096,
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
    )
