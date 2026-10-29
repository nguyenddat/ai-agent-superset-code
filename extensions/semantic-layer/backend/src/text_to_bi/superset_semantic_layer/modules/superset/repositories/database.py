from sqlalchemy.orm import Session

from superset.models.core import Database

from ....common.base_repo import BaseRepository


class SupersetDatabaseRepository(BaseRepository[Database]):
    """Superset's database connections."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, Database)
