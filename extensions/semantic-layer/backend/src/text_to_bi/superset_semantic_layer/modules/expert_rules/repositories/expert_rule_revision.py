from sqlalchemy.orm import Session

from ....common.base_repo import BaseRepository
from ..models import ExpertRuleRevision


class ExpertRuleRevisionRepository(BaseRepository[ExpertRuleRevision]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, ExpertRuleRevision)

    def current_for(self, rule_id: int) -> ExpertRuleRevision | None:
        return self.query().filter_by(rule_id=rule_id, is_current=True).one_or_none()

    def lock_current(self, rule_id: int) -> ExpertRuleRevision | None:
        """Re-read a rule's current revision and hold its row lock until the transaction ends."""
        current = self.query().filter_by(rule_id=rule_id, is_current=True)
        return current.populate_existing().with_for_update().one_or_none()

    def by_revision_number(self) -> list[ExpertRuleRevision]:
        return self.query().order_by(ExpertRuleRevision.revision_number).all()

    def approved_current(self) -> list[ExpertRuleRevision]:
        return self.query().filter_by(status="approved", is_current=True).all()
