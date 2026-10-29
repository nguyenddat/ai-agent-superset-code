from collections.abc import Iterable

from sqlalchemy.orm import Session

from ....common.base_repo import BaseRepository
from ..models import MetricDefinition


class MetricDefinitionRepository(BaseRepository[MetricDefinition]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, MetricDefinition)

    def for_dataset_metric(self, dataset_id: int, metric_id: int) -> MetricDefinition | None:
        return (
            self.query()
            .filter(MetricDefinition.dataset_id == dataset_id, MetricDefinition.metric_id == metric_id)
            .one_or_none()
        )

    def for_datasets(self, dataset_ids: Iterable[int]) -> list[MetricDefinition]:
        return self.query().filter(MetricDefinition.dataset_id.in_(dataset_ids)).all()
