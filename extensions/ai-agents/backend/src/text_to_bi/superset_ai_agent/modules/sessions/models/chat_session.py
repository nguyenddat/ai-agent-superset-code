from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String

from ....common.base_model import BaseModel


class AgentChatSession(BaseModel):
    """One conversation a user had with the AI Agent about one dashboard; its turns are the questions it holds."""

    __table_args__ = ({"extend_existing": True},)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    dashboard_id = Column(Integer, nullable=False)
    title = Column(String(200), nullable=False)
    created_on = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_on = Column(DateTime(timezone=True), nullable=False, index=True, default=lambda: datetime.now(timezone.utc))
