from functools import lru_cache

from langchain_openai import ChatOpenAI

from ..core.config import settings


@lru_cache(maxsize=1)
def get_chat_model() -> ChatOpenAI:
    if not settings.OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY chưa được cấu hình. Đặt biến này trong file .env ở thư mục gốc repo "
            "rồi khởi động lại dịch vụ superset."
        )
    return ChatOpenAI(
        model=settings.OPENROUTER_MODEL,
        temperature=0.0,
        max_tokens=4096,
        api_key=settings.OPENROUTER_API_KEY,
        base_url=settings.OPENROUTER_BASE_URL,
    )
