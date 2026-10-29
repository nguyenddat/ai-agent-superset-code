from collections.abc import Iterable

from sqlalchemy.orm import Query, Session

from superset.connectors.sqla.models import SqlaTable

from ....common.base_repo import BaseRepository


class SupersetDatasetRepository(BaseRepository[SqlaTable]):
    """Superset's own datasets; the Semantic Layer reads them and never changes them."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, SqlaTable)

    def by_name(self) -> list[SqlaTable]:
        return self.query().order_by(SqlaTable.table_name, SqlaTable.id).all()

    def on_database(self, database_id: int) -> Query:
        """The datasets of one database connection, as a query the caller may narrow further."""
        return self.query().filter(SqlaTable.database_id == database_id)

    def get_many(self, dataset_ids: Iterable[int]) -> list[SqlaTable]:
        """The datasets with these IDs that still exist, in no particular order."""
        dataset_ids = list(dataset_ids)
        if not dataset_ids:
            return []
        return self.query().filter(SqlaTable.id.in_(dataset_ids)).all()
