import logging
import threading
import time

from sqlalchemy import text
from superset import db

from .modules.definitions.models import AgentUserDefinition
from .modules.questions.models import AgentQuestion, AgentQuestionHandling
from .modules.sessions.models import AgentChatSession

logger = logging.getLogger(__name__)

# Arbitrary key shared by every Superset worker so only one of them migrates the AI Agent tables at a time.
AGENT_MIGRATION_LOCK_KEY = 74_116_202
AGENT_MIGRATION_RETRY_SECONDS = 30
_agent_tables_ready = False
_agent_migration_failed_at: float | None = None
_agent_tables_lock = threading.Lock()

# Columns added after the tables first shipped; `create(checkfirst=True)` leaves an existing table as it is.
ADDED_COLUMNS_DDL = (
    "ALTER TABLE text_to_bi_agent_question ADD COLUMN IF NOT EXISTS requires_expert_rule BOOLEAN",
    "ALTER TABLE text_to_bi_agent_question ADD COLUMN IF NOT EXISTS suggestions JSON",
    "ALTER TABLE text_to_bi_agent_question ADD COLUMN IF NOT EXISTS session_id INTEGER",
    "ALTER TABLE text_to_bi_agent_question ADD COLUMN IF NOT EXISTS tool_calls JSON",
    "CREATE INDEX IF NOT EXISTS ix_text_to_bi_agent_question_session_id ON text_to_bi_agent_question (session_id)",
    "ALTER TABLE text_to_bi_agent_question ADD COLUMN IF NOT EXISTS clarifications JSON",
    "ALTER TABLE text_to_bi_agent_question ADD COLUMN IF NOT EXISTS clarification_state VARCHAR(20)",
    "ALTER TABLE text_to_bi_agent_question ADD COLUMN IF NOT EXISTS retry_of INTEGER",
    "ALTER TABLE text_to_bi_agent_question ADD COLUMN IF NOT EXISTS query_result JSON",
    "ALTER TABLE text_to_bi_agent_user_definition ADD COLUMN IF NOT EXISTS conditions JSON",
)


def ensure_agent_tables() -> None:
    """Create and upgrade the AI Agent's tables in Superset's metadata database, once per process.

    ALTER TABLE takes ACCESS EXCLUSIVE locks, so the workers take turns under an advisory lock, and a failed run is not
    retried for `AGENT_MIGRATION_RETRY_SECONDS`.
    """
    global _agent_tables_ready, _agent_migration_failed_at
    if _agent_tables_ready:
        return
    with _agent_tables_lock:
        if _agent_tables_ready:
            return
        failed_at = _agent_migration_failed_at
        if failed_at is not None and time.monotonic() - failed_at < AGENT_MIGRATION_RETRY_SECONDS:
            raise RuntimeError("The AI Agent table migration failed recently; see the earlier error in the log.")
        try:
            if db.engine.dialect.name != "postgresql":
                _migrate_agent_tables()
            else:
                with db.engine.connect() as lock_connection:
                    lock_connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": AGENT_MIGRATION_LOCK_KEY})
                    try:
                        _migrate_agent_tables()
                    finally:
                        lock_connection.execute(
                            text("SELECT pg_advisory_unlock(:key)"), {"key": AGENT_MIGRATION_LOCK_KEY}
                        )
        except Exception:
            _agent_migration_failed_at = time.monotonic()
            logger.exception("AI Agent table migration failed; next attempt in %ss", AGENT_MIGRATION_RETRY_SECONDS)
            raise
        _agent_migration_failed_at = None
        _agent_tables_ready = True


def _migrate_agent_tables() -> None:
    for model in (AgentQuestion, AgentQuestionHandling, AgentChatSession, AgentUserDefinition):
        model.__table__.create(bind=db.engine, checkfirst=True)
    with db.engine.begin() as connection:
        for statement in ADDED_COLUMNS_DDL:
            connection.execute(text(statement))
