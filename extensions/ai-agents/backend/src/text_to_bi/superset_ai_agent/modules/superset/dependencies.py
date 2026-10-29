from superset import db

from .repositories.dashboard import SupersetDashboardRepository


def superset_dashboard_repository() -> SupersetDashboardRepository:
    return SupersetDashboardRepository(db.session)
