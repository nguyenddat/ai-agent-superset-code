from sqlalchemy import select
from sqlalchemy.orm import Session

from models.model_message import Message
from repositories.repo_base import RepositoryBase


class MessageRepository(RepositoryBase[Message]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Message)

    def list_for_thread(
        self,
        thread_id: int,
        *,
        offset: int = 0,
        limit: int = 500,
    ) -> list[Message]:
        statement = (
            select(Message)
            .where(Message.thread_id == thread_id)
            .order_by(Message.sequence_no, Message.id)
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement).all())

    def get_next_sequence_no(self, thread_id: int) -> int:
        statement = select(Message.sequence_no).where(Message.thread_id == thread_id)
        last_sequence_no = self.session.scalars(statement.order_by(Message.sequence_no.desc())).first()
        return (last_sequence_no or 0) + 1
