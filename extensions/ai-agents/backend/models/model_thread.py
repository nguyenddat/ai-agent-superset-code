from __future__ import annotations

from sqlalchemy import Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.model_base import BaseModel


class Thread(BaseModel):
    """A user's AI conversation scoped to one Superset dashboard."""

    __tablename__ = "ai_threads"
    __table_args__ = (
        Index(
            "ix_ai_threads_user_dashboard_updated",
            "superset_user_id",
            "superset_dashboard_id",
            "updated_at",
        ),
    )

    # These IDs refer to Superset metadata and intentionally have no local FK.
    superset_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    superset_dashboard_id: Mapped[int] = mapped_column(Integer, nullable=False)

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="New conversation",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
    )
    archived_at: Mapped[str | None] = mapped_column(Text, nullable=True)

    messages = relationship(
        "Message",
        back_populates="thread",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Message.sequence_no",
    )
