from sqlalchemy.orm import Session

from ....common.base_repo import BaseRepository
from ..models import ExpertRuleAuditEvent


class ExpertRuleAuditEventRepository(BaseRepository[ExpertRuleAuditEvent]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, ExpertRuleAuditEvent)

    def for_rule(self, rule_id: int) -> list[ExpertRuleAuditEvent]:
        return self.query().filter_by(rule_id=rule_id).order_by(ExpertRuleAuditEvent.id).all()

    def latest_authoring(self, revision_id: int) -> ExpertRuleAuditEvent | None:
        """The last created or updated event of a revision, whose actor wrote it."""
        return (
            self.query()
            .filter(
                ExpertRuleAuditEvent.revision_id == revision_id,
                ExpertRuleAuditEvent.event_type.in_(("created", "updated")),
            )
            .order_by(ExpertRuleAuditEvent.id.desc())
            .first()
        )
