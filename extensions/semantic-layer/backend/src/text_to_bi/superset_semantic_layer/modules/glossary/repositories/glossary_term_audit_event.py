from sqlalchemy.orm import Session

from ....common.base_repo import BaseRepository
from ..models import GlossaryTermAuditEvent


class GlossaryTermAuditEventRepository(BaseRepository[GlossaryTermAuditEvent]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, GlossaryTermAuditEvent)

    def for_term(self, term_id: int) -> list[GlossaryTermAuditEvent]:
        return self.query().filter_by(term_id=term_id).order_by(GlossaryTermAuditEvent.id).all()

    def latest_authoring(self, revision_id: int) -> GlossaryTermAuditEvent | None:
        """The last created or updated event of a revision, whose actor wrote it."""
        return (
            self.query()
            .filter(GlossaryTermAuditEvent.revision_id == revision_id)
            .filter(GlossaryTermAuditEvent.event_type.in_(("created", "updated")))
            .order_by(GlossaryTermAuditEvent.id.desc())
            .first()
        )
