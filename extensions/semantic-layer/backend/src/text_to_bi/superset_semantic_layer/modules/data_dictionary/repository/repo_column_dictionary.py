from sqlalchemy import select
from sqlalchemy.orm import Session

from ....common import BaseRepository
from ....models.column_dictionary import ColumnDictionary


class ColumnDictionaryRepository(BaseRepository[ColumnDictionary]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, ColumnDictionary)

    def list_for_dataset(self, dataset_id: int) -> list[ColumnDictionary]:
        statement = (
            select(ColumnDictionary)
            .where(ColumnDictionary.dataset_id == dataset_id)
            .order_by(ColumnDictionary.id)
        )
        return list(self.session.scalars(statement).all())

    def get_for_dataset_column(self, dataset_id: int, column_name: str) -> ColumnDictionary | None:
        statement = select(ColumnDictionary).where(
            ColumnDictionary.dataset_id == dataset_id,
            ColumnDictionary.column_name == column_name,
        )
        return self.session.scalars(statement).first()
