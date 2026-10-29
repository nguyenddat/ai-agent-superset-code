from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ....common.base_repo import BaseRepository
from ...data_dictionary.models import DatasetDictionary
from ..models import DataLayer


class DataLayerRepository(BaseRepository[DataLayer]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, DataLayer)

    def all(self) -> list[DataLayer]:
        return self.query().all()

    def in_flow_order(self) -> list[DataLayer]:
        """Layers level by level, as data flows, and in their saved order within a level."""
        return self.query().order_by(DataLayer.level, DataLayer.sort_order, DataLayer.id).all()

    def by_name(self, name: str) -> DataLayer | None:
        return self.query().filter(DataLayer.name == name).first()

    def last_in_order(self) -> DataLayer | None:
        return self.query().order_by(DataLayer.sort_order.desc()).first()

    def on_top_level(self) -> DataLayer | None:
        return self.query().order_by(DataLayer.level.desc()).first()

    def levels_for_datasets(self, dataset_ids: Iterable[int]) -> dict[int, int]:
        """Level of the data layer each dataset is classified into in the data dictionary."""
        rows = self.session.execute(
            select(DatasetDictionary.id, DataLayer.level)
            .join(DataLayer, DatasetDictionary.layer_id == DataLayer.id)
            .where(DatasetDictionary.id.in_(list(dataset_ids)))
        ).all()
        return {dataset_id: level for dataset_id, level in rows}
