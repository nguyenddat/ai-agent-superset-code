from __future__ import annotations

from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..common.type_formatter import to_iso_text
from .model_base import BaseModel


class ToolCall(BaseModel):
    """A tool invocation made while producing an assistant response."""

    __tablename__ = "ai_tool_calls"
    __table_args__ = (
        UniqueConstraint("message_id", "call_index", name="uq_ai_tool_calls_message_index"),
        Index("ix_ai_tool_calls_status_created", "status", "created_at"),
    )

    message_id: Mapped[int] = mapped_column(
        ForeignKey("ai_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    call_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[str] = mapped_column(Text, nullable=False, default=to_iso_text)
    finished_at: Mapped[str | None] = mapped_column(Text, nullable=True)

    message = relationship("Message", back_populates="tool_calls")
