from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.model_base import BaseModel


class Message(BaseModel):
    """A user, assistant, system, or tool message in a thread."""

    __tablename__ = "ai_messages"
    __table_args__ = (
        UniqueConstraint("thread_id", "sequence_no", name="uq_ai_messages_thread_sequence"),
        Index("ix_ai_messages_thread_created", "thread_id", "created_at"),
    )

    thread_id: Mapped[int] = mapped_column(
        ForeignKey("ai_threads.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="complete")
    extra_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    thread = relationship("Thread", back_populates="messages")
    tool_calls = relationship(
        "ToolCall",
        back_populates="message",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ToolCall.call_index",
    )
