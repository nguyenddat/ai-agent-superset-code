from sqlalchemy.orm import Session

from ....common.base_repo import BaseRepository
from ..models import MetricContractEvent


class MetricContractEventRepository(BaseRepository[MetricContractEvent]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, MetricContractEvent)

    def history(self, dataset_id: int, metric_id: int) -> list[MetricContractEvent]:
        """A metric's review events, newest first."""
        return (
            self.query()
            .filter(MetricContractEvent.dataset_id == dataset_id, MetricContractEvent.metric_id == metric_id)
            .order_by(MetricContractEvent.created_at.desc(), MetricContractEvent.id.desc())
            .all()
        )
