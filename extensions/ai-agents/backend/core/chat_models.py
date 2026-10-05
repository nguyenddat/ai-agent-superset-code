from langchain_openai import ChatOpenAI

from .settings import config

model_names = ["openai/gpt-6-luna"]
model_cache = {}

def get_chat_model(model_name: str = model_names[0]) -> ChatOpenAI:
    if model_name not in model_cache:
        if model_name not in model_names:
            raise ValueError(f"Model '{model_name}' not found. Available models: {model_names}")

        model_cache[model_name] = ChatOpenAI(
            model=model_name,
            temperature=config.model_temperature,
            api_key=config.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
        )
    return model_cache[model_name]
