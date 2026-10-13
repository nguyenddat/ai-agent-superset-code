from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[1]
EXTENSION_DIR = Path(__file__).resolve().parents[5]
ENV_FILE = EXTENSION_DIR / ".env"

class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Python package directory inside the extension source tree.
    base_dir: Path = BASE_DIR

    # Agent params
    openrouter_api_key: str = ""

    # Superset params
    superset_base_url: str
    superset_username: str
    superset_password: str
    query_timezone: str = "Asia/Ho_Chi_Minh"

config = Config()
