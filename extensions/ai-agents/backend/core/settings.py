from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = BASE_DIR.parents[0] / ".env"

class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Backend package directory (extensions/ai-agents/backend).
    base_dir: Path = BASE_DIR

    # Agent params
    openrouter_api_key: str = ""
    model_temperature: float = 0.0

    # Superset params
    superset_base_url: str
    superset_username: str
    superset_password: str

config = Config()
