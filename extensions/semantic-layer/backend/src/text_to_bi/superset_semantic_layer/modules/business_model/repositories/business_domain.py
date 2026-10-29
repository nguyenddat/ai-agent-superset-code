from sqlalchemy.orm import Session

from ....common.base_repo import BaseRepository
from ..models import BusinessDomain


class BusinessDomainRepository(BaseRepository[BusinessDomain]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, BusinessDomain)

    def by_name_order(self) -> list[BusinessDomain]:
        return self.query().order_by(BusinessDomain.name).all()

    def by_name(self, name: str) -> BusinessDomain | None:
        return self.query().filter(BusinessDomain.name == name).first()
