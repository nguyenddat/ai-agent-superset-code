from sqlalchemy.orm import Session

from ....common.base_repo import BaseRepository
from ..models import ExpertRuleLink


class ExpertRuleLinkRepository(BaseRepository[ExpertRuleLink]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, ExpertRuleLink)

    def for_revision(self, revision_id: int) -> list[ExpertRuleLink]:
        return self.query().filter_by(revision_id=revision_id).all()
