from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Model every agent step uses.
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_MODEL: str = "openai/gpt-6-luna"

    # Superset as seen from inside its own container, where the agent reads the Semantic Layer's endpoints.
    TEXT_TO_BI_SUPERSET_INTERNAL_URL: str = "http://127.0.0.1:8088"

    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")


settings = Settings()
