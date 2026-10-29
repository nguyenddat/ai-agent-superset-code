from sqlalchemy.orm import Session

from ....common.base_repo import BaseRepository
from ..models import GlossaryTermRevision


class GlossaryTermRevisionRepository(BaseRepository[GlossaryTermRevision]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, GlossaryTermRevision)

    def current_for(self, term_id: int) -> GlossaryTermRevision | None:
        return self.query().filter_by(term_id=term_id, is_current=True).one_or_none()

    def lock_current(self, term_id: int) -> GlossaryTermRevision | None:
        """Re-read a term's current revision and hold its row lock until the transaction ends."""
        current = self.query().filter_by(term_id=term_id, is_current=True)
        return current.populate_existing().with_for_update().one_or_none()

    def for_term(self, term_id: int) -> list[GlossaryTermRevision]:
        return self.query().filter_by(term_id=term_id).order_by(GlossaryTermRevision.revision_number).all()

    def approved_current_for(self, term_id: int) -> GlossaryTermRevision | None:
        return self.query().filter_by(term_id=term_id, status="approved", is_current=True).one_or_none()

    def approved_current(self) -> list[GlossaryTermRevision]:
        return self.query().filter_by(status="approved", is_current=True).all()
