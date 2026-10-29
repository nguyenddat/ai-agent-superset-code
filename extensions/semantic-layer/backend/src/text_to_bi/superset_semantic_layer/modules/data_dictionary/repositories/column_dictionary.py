from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Query, Session, aliased

from ....common.base_repo import BaseRepository
from ..models import ColumnDictionary


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

    def in_dataset(self, dataset_id: int) -> Query:
        return self.query().filter_by(dataset_id=dataset_id)

    def get_in_dataset(self, dataset_id: int, column_id: int) -> ColumnDictionary | None:
        return (
            self.query()
            .filter(ColumnDictionary.id == column_id, ColumnDictionary.dataset_id == dataset_id)
            .one_or_none()
        )

    def primary_keys(self, dataset_id: int) -> Query:
        return self.query().filter(ColumnDictionary.dataset_id == dataset_id, ColumnDictionary.is_pk.is_(True))

    def referencing(self, column_ids: Iterable[int]) -> list[ColumnDictionary]:
        """The foreign key columns that reference one of these columns."""
        return (
            self.query()
            .filter(ColumnDictionary.referenced_column.in_(column_ids), ColumnDictionary.is_fk.is_(True))
            .all()
        )

    def get_for_dataset_column(self, dataset_id: int, column_name: str) -> ColumnDictionary | None:
        statement = select(ColumnDictionary).where(
            ColumnDictionary.dataset_id == dataset_id,
            ColumnDictionary.column_name == column_name,
        )
        return self.session.scalars(statement).first()

    def list_for_datasets(self, dataset_ids: Iterable[int]) -> list[ColumnDictionary]:
        return self.query().filter(ColumnDictionary.dataset_id.in_(list(dataset_ids))).all()

    def key_columns(self) -> Query:
        """Columns declared a primary key or unique, which a foreign key may reference."""
        return self.query().filter((ColumnDictionary.is_pk.is_(True)) | (ColumnDictionary.is_unique.is_(True)))

    def by_ids(self, column_ids: Iterable[int]) -> Query:
        return self.query().filter(ColumnDictionary.id.in_(column_ids))

    def references(self, dataset_ids: Iterable[int]) -> list[Any]:
        """(referencing column, referenced column) for each foreign key declared on these datasets."""
        referenced = aliased(ColumnDictionary)
        return self.session.execute(
            select(ColumnDictionary, referenced)
            .join(referenced, ColumnDictionary.referenced_column == referenced.id)
            .where(ColumnDictionary.dataset_id.in_(list(dataset_ids)))
        ).all()

    def primary_key_columns(self, dataset_ids: Iterable[int]) -> Any:
        """(dataset ID, column name) of each primary key column of these datasets."""
        return self.session.execute(
            select(ColumnDictionary.dataset_id, ColumnDictionary.column_name).where(
                ColumnDictionary.dataset_id.in_(list(dataset_ids)), ColumnDictionary.is_pk.is_(True)
            )
        )
