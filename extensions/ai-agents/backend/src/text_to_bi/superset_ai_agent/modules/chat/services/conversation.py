import time
from typing import Any

from ...questions.dependencies import question_repository
from ...questions.models import AgentQuestion
from ..exceptions import (
    ChatQuestionError,
    ChatSessionIdError,
    DashboardRequiredError,
    RetriedQuestionError,
    RetriedQuestionNotFoundError,
)
from .pipeline import MAX_HISTORY_TURNS, AgentOutcome, recent_history

MAX_QUESTION_LENGTH = 2000


def _is_id(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def parse_chat_request(body: Any) -> dict[str, Any]:
    """`{question, session_id, dashboard_id, retry_of}` checked for type; the IDs are not looked up yet."""
    body = body if isinstance(body, dict) else {}
    session_id, retry_of, dashboard_id = body.get("session_id"), body.get("retry_of"), body.get("dashboard_id")
    if retry_of is not None and (not _is_id(retry_of) or session_id is None):
        raise RetriedQuestionError()
    if session_id is None and not _is_id(dashboard_id):
        # Every conversation is about a dashboard the user may open; the answers and the log are tied to it.
        raise DashboardRequiredError()
    if session_id is not None and not _is_id(session_id):
        raise ChatSessionIdError()
    return {
        "question": body.get("question"), "session_id": session_id, "dashboard_id": dashboard_id, "retry_of": retry_of,
    }


def asked_question(question: Any, session_id: int | None, retry_of: int | None) -> str:
    """The question to answer: the one sent, or with `retry_of`, the conversation's earlier question asked again."""
    if retry_of is not None:
        earlier = question_repository().one_in_session(retry_of, session_id)
        if earlier is None:
            raise RetriedQuestionNotFoundError()
        question = earlier.question
    if not isinstance(question, str) or not question.strip() or len(question) > MAX_QUESTION_LENGTH:
        raise ChatQuestionError()
    return question.strip()


def session_history(session_id: int, excluded_question_id: int | None) -> list[dict[str, str]]:
    """The conversation's last answered turns, which the agent uses to rewrite a follow-up question.

    A question answered again after the user confirmed definitions leaves out its first answer.
    """
    answered = question_repository().answered_in_session(session_id, excluded_question_id, MAX_HISTORY_TURNS)
    return recent_history([
        message
        for question, answer in reversed(answered)
        for message in ({"role": "user", "content": question}, {"role": "assistant", "content": answer})
    ])


def record_tool_call(tool_calls: list[dict[str, Any]], name: str, data: dict[str, Any]) -> None:
    """Keep each step as the browser shows it: the start's arguments merged with the end's status and result."""
    if name == "tool_start":
        tool_calls.append({**data, "status": "running"})
    elif name == "tool_end":
        for tool_call in tool_calls:
            if tool_call["id"] == data["id"]:
                tool_call.update(data)


def log_question(
    *,
    user_id: int,
    session_id: int,
    dashboard_id: int,
    question: str,
    history_turns: int,
    outcome: AgentOutcome,
    tool_calls: list[dict[str, Any]],
    retry_of: int | None,
    started: float,
    error: str | None,
) -> AgentQuestion:
    """Add the question to the log as the conversation's next turn; a failed turn keeps only its error."""
    record = AgentQuestion(
        user_id=user_id,
        session_id=session_id,
        dashboard_id=dashboard_id,
        question=question,
        rewritten_question=outcome.rewritten_question,
        history_turns=history_turns,
        glossary_terms=outcome.glossary_terms,
        metrics=outcome.metrics,
        expert_rules=outcome.expert_rules,
        missing=[] if error else outcome.missing,
        query_result=None if error else outcome.result,
        requires_expert_rule=None if error else outcome.requires_expert_rule,
        suggestions=None if error else outcome.suggestions,
        tool_calls=tool_calls,
        clarifications=None if error else outcome.clarifications or None,
        clarification_state="pending" if outcome.clarifications and not error else None,
        retry_of=retry_of,
        status="failed" if error else outcome.status,
        answer=outcome.answer or None,
        error=error,
        duration_ms=round((time.monotonic() - started) * 1000),
    )
    return question_repository().add(record)
