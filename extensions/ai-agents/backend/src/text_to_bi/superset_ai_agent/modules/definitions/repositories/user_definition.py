from typing import Any

from sqlalchemy.orm import Session

from ....common.base_repo import BaseRepository
from ..models import AgentUserDefinition


class AgentUserDefinitionRepository(BaseRepository[AgentUserDefinition]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, AgentUserDefinition)

    def for_dashboard(self, user_id: int, dashboard_id: int) -> list[AgentUserDefinition]:
        """What one user confirmed concepts mean on one dashboard, oldest first."""
        return (
            self.query()
            .filter(AgentUserDefinition.user_id == user_id, AgentUserDefinition.dashboard_id == dashboard_id)
            .order_by(AgentUserDefinition.id)
            .all()
        )

    def own(self, definition_id: int, user_id: int) -> AgentUserDefinition | None:
        return self.query().filter_by(id=definition_id, user_id=user_id).one_or_none()

    def recently_changed(self) -> list[AgentUserDefinition]:
        """Every user's definitions, most recently changed first."""
        return self.query().order_by(AgentUserDefinition.updated_on.desc(), AgentUserDefinition.id.desc()).all()

    def update_by_ids(self, definition_ids: list[int], values: dict[str, Any]) -> int:
        """Set `values` on the named definitions; returns how many rows changed."""
        return self.query().filter(AgentUserDefinition.id.in_(definition_ids)).update(
            {getattr(AgentUserDefinition, attribute): value for attribute, value in values.items()},
            synchronize_session=False,
        )
