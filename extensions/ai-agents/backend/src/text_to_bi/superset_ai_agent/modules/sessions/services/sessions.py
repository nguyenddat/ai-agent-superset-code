from datetime import datetime, timezone
from typing import Any

from ....common.utils.type_formatter import iso_datetime
from ...questions.dependencies import question_repository
from ...questions.models import AgentQuestion
from ...superset.services.dashboards import dashboard_titles
from ..dependencies import chat_session_repository
from ..exceptions import ChatSessionNotFoundError, ChatSessionTitleError, ClarificationNotPendingError
from ..models import AgentChatSession

SESSION_LIST_LIMIT = 200
MAX_TITLE_LENGTH = 200
SESSION_TITLE_LENGTH = 80
# What the chat showed for a turn that failed; the stored error is the internal cause, kept for the log.
FAILED_TURN_MESSAGE = "AI Agent không hoàn tất được câu trả lời."


def serialize_session(chat_session: AgentChatSession, titles: dict[int, str] | None = None) -> dict[str, Any]:
    """A conversation as the page lists it; `titles` names the dashboards when several sessions are listed."""
    titles = dashboard_titles({chat_session.dashboard_id}) if titles is None else titles
    return {
        "id": chat_session.id,
        "title": chat_session.title,
        "dashboard_id": chat_session.dashboard_id,
        "dashboard_title": titles.get(chat_session.dashboard_id),
        "created_on": iso_datetime(chat_session.created_on),
        "updated_on": iso_datetime(chat_session.updated_on),
    }


def serialize_turn(question: AgentQuestion) -> dict[str, Any]:
    return {
        "id": question.id,
        "question": question.question,
        "answer": question.answer or "",
        "tool_calls": question.tool_calls or [],
        "status": question.status,
        "missing": question.missing or [],
        "error": FAILED_TURN_MESSAGE if question.error else None,
        "clarifications": question.clarifications or [],
        "clarification_state": question.clarification_state,
        "retry_of": question.retry_of,
        "result": question.query_result,
        "asked_on": iso_datetime(question.created_on),
    }


def recent_sessions(user_id: int) -> list[dict[str, Any]]:
    """The user's conversations, most recently active first."""
    sessions = chat_session_repository().recent_for_user(user_id, SESSION_LIST_LIMIT)
    titles = dashboard_titles({chat_session.dashboard_id for chat_session in sessions})
    return [serialize_session(chat_session, titles) for chat_session in sessions]


def require_own_session(session_id: int, user_id: int) -> AgentChatSession:
    """The user's own conversation; another user's is reported as not found."""
    chat_session = chat_session_repository().own(session_id, user_id)
    if chat_session is None:
        raise ChatSessionNotFoundError()
    return chat_session


def session_turns(session_id: int) -> list[dict[str, Any]]:
    return [serialize_turn(question) for question in question_repository().in_session(session_id)]


def session_title(question: str) -> str:
    """A new conversation is named after its first question, cut at a word boundary."""
    title = " ".join(question.split())
    if len(title) <= SESSION_TITLE_LENGTH:
        return title
    return title[:SESSION_TITLE_LENGTH].rsplit(" ", 1)[0] + "…"


def start_session(user_id: int, dashboard_id: int, question: str) -> AgentChatSession:
    """A new conversation about a dashboard, named after its first question."""
    chat_session = AgentChatSession(user_id=user_id, dashboard_id=dashboard_id, title=session_title(question))
    return chat_session_repository().add(chat_session)


def touch_session(session_id: int) -> None:
    """Mark the conversation as just active, so it lists first."""
    chat_session_repository().touch(session_id, datetime.now(timezone.utc))


def rename_chat_session(chat_session: AgentChatSession, title: Any) -> None:
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > MAX_TITLE_LENGTH:
        raise ChatSessionTitleError()
    chat_session.title = title.strip()


def delete_chat_session(chat_session: AgentChatSession) -> None:
    """Delete a conversation; its questions stay in the log, and the user's definitions stay for the dashboard."""
    question_repository().detach_session(chat_session.id)
    chat_session_repository().delete(chat_session)


def require_pending_clarification(question_id: int, session_id: int) -> AgentQuestion:
    """The conversation's question that is still waiting for the user to confirm its definitions."""
    question = question_repository().one_in_session(question_id, session_id)
    if question is None or question.clarification_state != "pending":
        raise ClarificationNotPendingError()
    return question
