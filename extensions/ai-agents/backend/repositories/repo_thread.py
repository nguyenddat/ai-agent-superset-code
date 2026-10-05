from sqlalchemy import select
from sqlalchemy.orm import Session

from models.model_thread import Thread
from repositories.repo_base import RepositoryBase


class ThreadRepository(RepositoryBase[Thread]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Thread)

    def list_for_dashboard(
        self,
        *,
        superset_user_id: int,
        superset_dashboard_id: int,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Thread]:
        statement = (
            select(Thread)
            .where(
                Thread.superset_user_id == superset_user_id,
                Thread.superset_dashboard_id == superset_dashboard_id,
            )
            .order_by(Thread.updated_at.desc(), Thread.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement).all())

    def get_for_dashboard_user(
        self,
        *,
        thread_id: int,
        superset_user_id: int,
        superset_dashboard_id: int,
    ) -> Thread | None:
        statement = select(Thread).where(
            Thread.id == thread_id,
            Thread.superset_user_id == superset_user_id,
            Thread.superset_dashboard_id == superset_dashboard_id,
        )
        return self.session.scalars(statement).first()
