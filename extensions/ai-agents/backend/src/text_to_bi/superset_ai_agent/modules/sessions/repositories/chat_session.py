from datetime import datetime

from sqlalchemy.orm import Session

from ....common.base_repo import BaseRepository
from ..models import AgentChatSession


class AgentChatSessionRepository(BaseRepository[AgentChatSession]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, AgentChatSession)

    def own(self, session_id: int, user_id: int) -> AgentChatSession | None:
        return self.query().filter_by(id=session_id, user_id=user_id).one_or_none()

    def recent_for_user(self, user_id: int, limit: int) -> list[AgentChatSession]:
        """The user's conversations, most recently active first."""
        return (
            self.query()
            .filter(AgentChatSession.user_id == user_id)
            .order_by(AgentChatSession.updated_on.desc(), AgentChatSession.id.desc())
            .limit(limit)
            .all()
        )

    def touch(self, session_id: int, moment: datetime) -> None:
        self.query().filter(AgentChatSession.id == session_id).update({AgentChatSession.updated_on: moment})
