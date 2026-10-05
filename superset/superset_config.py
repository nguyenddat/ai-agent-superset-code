import os
import sys


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


def configure_ai_agent_frontend(app):
    """Load the local frontend using Superset's custom template hook."""
    from flask import Blueprint
    from jinja2 import ChoiceLoader, FileSystemLoader

    frontend = os.path.join(EXTENSIONS_PATH, "ai-agents", "frontend")
    app.register_blueprint(Blueprint(
        "ai_agent_assets", __name__,
        static_folder=os.path.join(frontend, "dist"),
        static_url_path="/ai-agent-assets",
    ))

    backend = os.path.join(EXTENSIONS_PATH, "ai-agents", "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from modules.chat.route import chat_bp

    app.register_blueprint(chat_bp)

    def ai_agent_asset_version():
        assets = ("ai-agent.css", "ai-agent.js")
        return str(max(
            os.stat(os.path.join(frontend, "dist", asset)).st_mtime_ns
            for asset in assets
        ))

    app.jinja_env.globals["ai_agent_asset_version"] = ai_agent_asset_version
    app.jinja_loader = ChoiceLoader([
        FileSystemLoader(os.path.join(frontend, "templates")),
        app.jinja_loader,
    ])


FLASK_APP_MUTATOR = configure_ai_agent_frontend
