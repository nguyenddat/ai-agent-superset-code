from superset import db

from .repositories.chat_session import AgentChatSessionRepository


def chat_session_repository() -> AgentChatSessionRepository:
    return AgentChatSessionRepository(db.session)
