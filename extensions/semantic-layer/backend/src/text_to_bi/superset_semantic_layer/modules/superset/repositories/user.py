from typing import Any

from sqlalchemy.orm import Session

from superset import security_manager

from ....common.base_repo import BaseRepository


class SupersetUserRepository(BaseRepository[Any]):
    """Superset's users, through the user model its security manager configures."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, security_manager.user_model)

    def active(self) -> list[Any]:
        return self.query().filter(self.model.active.is_(True)).order_by(self.model.username).all()
