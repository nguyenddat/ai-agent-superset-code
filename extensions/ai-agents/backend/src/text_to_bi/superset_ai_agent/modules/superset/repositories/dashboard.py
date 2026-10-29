from sqlalchemy.orm import Session
from superset.models.dashboard import Dashboard

from ....common.base_repo import BaseRepository


class SupersetDashboardRepository(BaseRepository[Dashboard]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Dashboard)

    def titles(self, dashboard_ids: set[int]) -> dict[int, str]:
        if not dashboard_ids:
            return {}
        rows = self.session.query(Dashboard.id, Dashboard.dashboard_title).filter(Dashboard.id.in_(dashboard_ids))
        return {dashboard_id: title for dashboard_id, title in rows}
