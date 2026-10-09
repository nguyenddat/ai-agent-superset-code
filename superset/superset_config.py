import os


SECRET_KEY = os.getenv("SUPERSET_SECRET_KEY", "local-development-secret-change-me")
SQLALCHEMY_DATABASE_URI = (
    "postgresql+psycopg2://"
    f"{os.getenv('SUPERSET_DB_USER', 'superset')}:{os.getenv('SUPERSET_DB_PASSWORD', 'superset_dev_password')}"
    f"@superset-db:5432/{os.getenv('SUPERSET_DB', 'superset')}"
)

FEATURE_FLAGS = {
    "ENABLE_EXTENSIONS": True,
}
EXTENSIONS_PATH = "/app/superset_home/extensions"
