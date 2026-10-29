from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from superset.connectors.sqla.models import SqlaTable

from ....common.base_repo import BaseRepository
from ..models import DatasetDictionary


class DatasetDictionaryRepository(BaseRepository[DatasetDictionary]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, DatasetDictionary)

    def all(self) -> list[DatasetDictionary]:
        return self.query().all()

    def of_type(self, dataset_type: str) -> list[DatasetDictionary]:
        return self.query().filter(DatasetDictionary.dataset_type == dataset_type).all()

    def of_types(self, dataset_types: Iterable[str]) -> list[DatasetDictionary]:
        return self.query().filter(DatasetDictionary.dataset_type.in_(dataset_types)).all()

    def datasets_of_type(self, database_id: int, dataset_type: str) -> list[Any]:
        """(Superset dataset, dictionary) of each dataset of this type on one database."""
        return (
            self.session.query(SqlaTable, DatasetDictionary)
            .join(DatasetDictionary, DatasetDictionary.id == SqlaTable.id)
            .filter(SqlaTable.database_id == database_id, DatasetDictionary.dataset_type == dataset_type)
            .all()
        )

    def list_by_ids(self, dataset_ids: Iterable[int]) -> list[DatasetDictionary]:
        return self.query().filter(DatasetDictionary.id.in_(dataset_ids)).all()

    def existing_ids(self, dataset_ids: Iterable[int]) -> set[int]:
        statement = select(DatasetDictionary.id).where(DatasetDictionary.id.in_(list(dataset_ids)))
        return set(self.session.scalars(statement))

    def classifications(self, dataset_ids: Iterable[int]) -> list[Any]:
        """(dataset ID, data layer ID, dataset type) of each dataset."""
        return self.session.execute(
            select(DatasetDictionary.id, DatasetDictionary.layer_id, DatasetDictionary.dataset_type).where(
                DatasetDictionary.id.in_(list(dataset_ids))
            )
        ).all()

    def unclassify_layer(self, layer_id: int) -> None:
        """Leave the datasets of a data layer without one."""
        self.query().filter(DatasetDictionary.layer_id == layer_id).update(
            {DatasetDictionary.layer_id: None}, synchronize_session=False
        )
