from collections.abc import Iterable

from sqlalchemy.orm import Session

from ....common.base_repo import BaseRepository
from ..models import RelationshipContract


class RelationshipContractRepository(BaseRepository[RelationshipContract]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, RelationshipContract)

    def from_column(self, from_dataset_id: int, from_column: str) -> RelationshipContract | None:
        return (
            self.query()
            .filter(
                RelationshipContract.from_dataset_id == from_dataset_id,
                RelationshipContract.from_column == from_column,
            )
            .one_or_none()
        )

    def approved(self) -> list[RelationshipContract]:
        return self.query().filter(RelationshipContract.status == "approved").all()

    def approved_between(self, dataset_ids: Iterable[int]) -> list[RelationshipContract]:
        """Approved contracts whose both ends are among these datasets."""
        return (
            self.query()
            .filter(
                RelationshipContract.status == "approved",
                RelationshipContract.from_dataset_id.in_(dataset_ids),
                RelationshipContract.to_dataset_id.in_(dataset_ids),
            )
            .all()
        )
