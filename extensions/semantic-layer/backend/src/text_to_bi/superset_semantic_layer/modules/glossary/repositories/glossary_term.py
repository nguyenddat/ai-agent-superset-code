from sqlalchemy.orm import Session

from ....common.base_repo import BaseRepository
from ..models import GlossaryTerm


class GlossaryTermRepository(BaseRepository[GlossaryTerm]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, GlossaryTerm)

    def by_canonical_name(self) -> list[GlossaryTerm]:
        return self.query().order_by(GlossaryTerm.canonical_name).all()

    def by_normalized_name(self, normalized_name: str) -> GlossaryTerm | None:
        return self.query().filter_by(normalized_name=normalized_name).one_or_none()

    def lock(self, term_id: int) -> GlossaryTerm | None:
        """Re-read a term and hold its row lock until the transaction ends."""
        return self.query().filter(GlossaryTerm.id == term_id).populate_existing().with_for_update().one_or_none()
