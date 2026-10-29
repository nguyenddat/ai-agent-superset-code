from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Model for AI AutoFill in the Data Dictionary.
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_MODEL: str = "openai/gpt-6-luna"

    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")


settings = Settings()
