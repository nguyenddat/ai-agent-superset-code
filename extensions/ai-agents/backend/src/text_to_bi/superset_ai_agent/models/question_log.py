import threading
from datetime import datetime, timezone

from flask_appbuilder import Model
from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text, text


class AgentChatSession(Model):
    """One conversation a user had with the AI Agent about one dashboard; its turns are the questions it holds."""

    __tablename__ = "text_to_bi_agent_chat_session"
    __table_args__ = ({"extend_existing": True},)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    dashboard_id = Column(Integer, nullable=False)
    title = Column(String(200), nullable=False)
    created_on = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_on = Column(DateTime(timezone=True), nullable=False, index=True, default=lambda: datetime.now(timezone.utc))


class AgentQuestion(Model):
    """One question asked to the AI Agent and what the governed semantic layer resolved it to.

    A question is `resolved` when the agent named at least one metric, every business concept it uses is defined (by
    the Semantic Layer or by the user in this conversation), and a qualitative question (`requires_expert_rule`) has an
    expert rule; otherwise it is `needs_review` and `missing` lists what was not found. A missing term or rule becomes
    a draft in `clarifications` for the user to confirm; a missing metric is proposed in `suggestions` for an
    administrator.
    """

    __tablename__ = "text_to_bi_agent_question"
    __table_args__ = ({"extend_existing": True},)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=True, index=True)
    dashboard_id = Column(Integer, nullable=True)
    question = Column(Text, nullable=False)
    rewritten_question = Column(Text, nullable=True)
    history_turns = Column(Integer, nullable=False, default=0)
    glossary_terms = Column(JSON, nullable=False, default=list)
    metrics = Column(JSON, nullable=False, default=list)
    expert_rules = Column(JSON, nullable=False, default=list)
    missing = Column(JSON, nullable=False, default=list)
    # NULL on questions logged before the agent told qualitative from quantitative questions.
    requires_expert_rule = Column(Boolean, nullable=True)
    suggestions = Column(JSON, nullable=True)
    # resolved, needs_review, or failed when a step errored before the semantic layer could be consulted.
    status = Column(String(20), nullable=False, index=True)
    answer = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    # The conversation the question was asked in, and the steps it took, so the conversation can be shown again.
    # A deleted conversation leaves its questions in the log with no session.
    session_id = Column(Integer, nullable=True, index=True)
    tool_calls = Column(JSON, nullable=True)
    # Definitions the agent drafted for the user to confirm (`clarifications`), whether the user `confirmed` or
    # `dismissed` them, and on the answer given again after a confirmation, the question it answers again.
    clarifications = Column(JSON, nullable=True)
    clarification_state = Column(String(20), nullable=True)
    retry_of = Column(Integer, nullable=True)
    # The table the metric query answered with: its filters, dimensions, metrics and rows.
    query_result = Column(JSON, nullable=True)
    created_on = Column(DateTime(timezone=True), nullable=False, index=True, default=lambda: datetime.now(timezone.utc))


class AgentQuestionHandling(Model):
    """How an administrator handled a `needs_review` question; a question without a row has not been handled yet.

    `to_create` means the missing glossary term, metric or expert rule should be added, `created` that it was, and
    `ignored` that the question needs nothing. The row lives apart from the log so the log stays append-only.
    """

    __tablename__ = "text_to_bi_agent_question_handling"
    __table_args__ = ({"extend_existing": True},)

    question_id = Column(Integer, ForeignKey("text_to_bi_agent_question.id", ondelete="CASCADE"), primary_key=True)
    status = Column(String(20), nullable=False, index=True)
    note = Column(Text, nullable=True)
    handled_by = Column(Integer, nullable=True)
    handled_on = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class AgentUserDefinition(Model):
    """What a user confirmed a glossary term or qualitative concept means to them, on one dashboard.

    The agent uses it in every conversation that user has about that dashboard, unless an approved business term or
    rule covers the concept. Administrators only read these as a signal of what people ask about: they either cover
    the concept with a shared term or rule set by the business's experts (`promoted`) or leave it as the user's own
    sense (`ignored`); editing a definition puts it back to `pending`.
    """

    __tablename__ = "text_to_bi_agent_user_definition"
    __table_args__ = ({"extend_existing": True},)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    dashboard_id = Column(Integer, nullable=False, index=True)
    # glossary or expert_rule
    kind = Column(String(20), nullable=False)
    name = Column(String(200), nullable=False)
    concept = Column(String(200), nullable=True)
    definition = Column(Text, nullable=False)
    # The question that asked the user, and its conversation.
    source_question_id = Column(Integer, nullable=True)
    source_session_id = Column(Integer, nullable=True)
    review_status = Column(String(20), nullable=False, default="pending", index=True)
    reviewed_by = Column(Integer, nullable=True)
    reviewed_on = Column(DateTime(timezone=True), nullable=True)
    created_on = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_on = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


# Columns added after the table first shipped; `create(checkfirst=True)` leaves an existing table as it is.
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
)

_tables_lock = threading.Lock()
_tables_ready = False


def ensure_question_tables(engine) -> None:
    """Create the AI Agent's tables once per process, in Superset's metadata database."""
    global _tables_ready
    if _tables_ready:
        return
    with _tables_lock:
        if not _tables_ready:
            AgentQuestion.__table__.create(bind=engine, checkfirst=True)
            AgentQuestionHandling.__table__.create(bind=engine, checkfirst=True)
            AgentChatSession.__table__.create(bind=engine, checkfirst=True)
            AgentUserDefinition.__table__.create(bind=engine, checkfirst=True)
            with engine.begin() as connection:
                for statement in ADDED_COLUMNS_DDL:
                    connection.execute(text(statement))
            _tables_ready = True
