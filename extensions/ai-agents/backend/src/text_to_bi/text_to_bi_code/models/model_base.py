from sqlalchemy import Integer, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ..common.type_formatter import to_iso_text


class BaseModel(DeclarativeBase):
    """Base for extension models, with an integer key and ISO text timestamps."""

    __abstract__ = True

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    created_at: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=to_iso_text,
    )
    updated_at: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=to_iso_text,
        onupdate=to_iso_text,
    )
