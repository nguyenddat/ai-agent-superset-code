from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.model_toolcall import ToolCall
from .repo_base import RepositoryBase


class ToolCallRepository(RepositoryBase[ToolCall]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, ToolCall)

    def list_for_message(self, message_id: int) -> list[ToolCall]:
        statement = (
            select(ToolCall)
            .where(ToolCall.message_id == message_id)
            .order_by(ToolCall.call_index, ToolCall.id)
        )
        return list(self.session.scalars(statement).all())
