from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from ....common.base_model import BaseModel


class AgentQuestion(BaseModel):
    """One question asked to the AI Agent and what the governed semantic layer resolved it to.

    A question is `resolved` when the agent named at least one metric, every business concept it uses is defined (by
    the Semantic Layer or by the user in this conversation), and a qualitative question (`requires_expert_rule`) has an
    expert rule; otherwise it is `needs_review` and `missing` lists what was not found. A missing term or rule becomes
    a draft in `clarifications` for the user to confirm; a missing metric is proposed in `suggestions` for an
    administrator.
    """

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


class AgentQuestionHandling(BaseModel):
    """How an administrator handled a `needs_review` question; a question without a row has not been handled yet.

    `to_create` means the missing glossary term, metric or expert rule should be added, `created` that it was, and
    `ignored` that the question needs nothing. The row lives apart from the log so the log stays append-only.
    """

    __table_args__ = ({"extend_existing": True},)

    question_id = Column(Integer, ForeignKey("text_to_bi_agent_question.id", ondelete="CASCADE"), primary_key=True)
    status = Column(String(20), nullable=False, index=True)
    note = Column(Text, nullable=True)
    handled_by = Column(Integer, nullable=True)
    handled_on = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
