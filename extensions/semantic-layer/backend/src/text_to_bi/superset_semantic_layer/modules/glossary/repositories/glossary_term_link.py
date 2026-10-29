from sqlalchemy.orm import Session

from ....common.base_repo import BaseRepository
from ..models import GlossaryTermLink


class GlossaryTermLinkRepository(BaseRepository[GlossaryTermLink]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, GlossaryTermLink)

    def for_revision(self, revision_id: int) -> list[GlossaryTermLink]:
        return self.query().filter(GlossaryTermLink.revision_id == revision_id).all()

    def for_revision_in_order(self, revision_id: int) -> list[GlossaryTermLink]:
        return self.query().filter_by(revision_id=revision_id).order_by(GlossaryTermLink.id).all()

    def for_revision_dataset(self, revision_id: int, dataset_id: int) -> list[GlossaryTermLink]:
        return self.query().filter_by(revision_id=revision_id, dataset_id=dataset_id).all()
