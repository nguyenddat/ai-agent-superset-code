from sqlalchemy.orm import Session

from ....common.base_repo import BaseRepository
from ..models import DatasetProposal


class DatasetProposalRepository(BaseRepository[DatasetProposal]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, DatasetProposal)

    def pending_with_fingerprint(self, sql_fingerprint: str) -> DatasetProposal | None:
        """A proposal of the same SQL still waiting for review."""
        return (
            self.query()
            .filter(DatasetProposal.sql_fingerprint == sql_fingerprint, DatasetProposal.status == "pending")
            .first()
        )

    def pending_count(self) -> int:
        return self.query().filter(DatasetProposal.status == "pending").count()

    def newest_first(self) -> list[DatasetProposal]:
        return self.query().order_by(DatasetProposal.created_on.desc()).all()
