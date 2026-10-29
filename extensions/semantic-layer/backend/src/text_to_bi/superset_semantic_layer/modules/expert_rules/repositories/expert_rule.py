from sqlalchemy.orm import Session

from ....common.base_repo import BaseRepository
from ..models import ExpertRule


class ExpertRuleRepository(BaseRepository[ExpertRule]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, ExpertRule)

    def by_normalized_name(self, normalized_name: str) -> ExpertRule | None:
        return self.query().filter_by(normalized_name=normalized_name).one_or_none()

    def find(self, rule_id: int) -> ExpertRule | None:
        """Read a rule with a query rather than the identity map, so it reflects a row just locked."""
        return self.query().filter(ExpertRule.id == rule_id).one_or_none()

    def lock(self, rule_id: int) -> ExpertRule | None:
        """Re-read a rule and hold its row lock until the transaction ends."""
        return self.query().filter(ExpertRule.id == rule_id).populate_existing().with_for_update().one_or_none()
