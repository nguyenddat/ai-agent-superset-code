from sqlalchemy.orm import Session

from ....common.base_repo import BaseRepository
from ..models import BusinessCanvas


class BusinessCanvasRepository(BaseRepository[BusinessCanvas]):
    """Business canvases, one per Superset database, keyed by its database ID."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, BusinessCanvas)
