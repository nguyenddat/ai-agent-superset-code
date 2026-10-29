from collections.abc import Iterable
from typing import Any

from sqlalchemy.orm import Query, Session

from ....common.base_repo import BaseRepository
from ..models import DatasetGrain


class DatasetGrainRepository(BaseRepository[DatasetGrain]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, DatasetGrain)

    def list_for_dataset(self, dataset_id: int) -> list[DatasetGrain]:
        return self.query().filter(DatasetGrain.dataset_id == dataset_id).all()

    def by_row_kind(self, dataset_id: int) -> Query:
        return self.query().filter(DatasetGrain.dataset_id == dataset_id).order_by(DatasetGrain.row_kind_value)

    def replace(self, stored: Iterable[DatasetGrain], dataset_id: int, grains: Iterable[dict[str, Any]]) -> None:
        """Swap a dataset's grains for new ones."""
        for item in stored:
            self.delete(item)
        # The unique row kind constraint must see the old rows gone before the new ones arrive.
        self.flush()
        self.add_all(DatasetGrain(dataset_id=dataset_id, **item) for item in grains)
        self.flush()
