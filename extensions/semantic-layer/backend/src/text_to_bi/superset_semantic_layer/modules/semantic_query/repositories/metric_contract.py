from collections.abc import Iterable

from sqlalchemy.orm import Session

from ....common.base_repo import BaseRepository
from ..models import MetricContract


class MetricContractRepository(BaseRepository[MetricContract]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, MetricContract)

    def for_metric(self, metric_id: int) -> list[MetricContract]:
        return self.query().filter_by(metric_id=metric_id).all()

    def for_dataset_metric(self, dataset_id: int, metric_id: int) -> MetricContract | None:
        return (
            self.query()
            .filter(MetricContract.dataset_id == dataset_id, MetricContract.metric_id == metric_id)
            .one_or_none()
        )

    def for_datasets(self, dataset_ids: Iterable[int]) -> list[MetricContract]:
        return self.query().filter(MetricContract.dataset_id.in_(dataset_ids)).all()

    def approved(self) -> list[MetricContract]:
        return self.query().filter(MetricContract.status == "approved").all()

    def first_approved_on(self, dataset_id: int) -> MetricContract | None:
        return self.query().filter(MetricContract.dataset_id == dataset_id, MetricContract.status == "approved").first()

    def count_on(self, dataset_id: int, *, origin: str, status: str) -> int:
        return (
            self.query()
            .filter(
                MetricContract.dataset_id == dataset_id,
                MetricContract.origin == origin,
                MetricContract.status == status,
            )
            .count()
        )
