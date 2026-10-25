from flask_appbuilder import Model
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from superset.models.helpers import AuditMixinNullable


class ColumnDictionary(AuditMixinNullable, Model):
    __tablename__ = "text_to_bi_column_dictionary"
    __table_args__ = (
        UniqueConstraint("dataset_id", "column_name", name="uq_text_to_bi_column_dataset_column_name"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True)
    dataset_id = Column(
        Integer,
        ForeignKey("text_to_bi_dataset_dictionary.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    column_name = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=False)
    data_type = Column(String(128), nullable=False)
    nullable = Column(Boolean, nullable=False, default=True)
    default_value = Column("default", Text, nullable=True)
    is_pk = Column(Boolean, nullable=False, default=False)
    is_fk = Column(Boolean, nullable=False, default=False)
    referenced_column = Column(
        Integer,
        ForeignKey("text_to_bi_column_dictionary.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_unique = Column(Boolean, nullable=False, default=False)
    unit = Column(String(128), nullable=True)
    format = Column(String(128), nullable=True)
    business_term = Column(Text, nullable=True)

    referenced_column_record = relationship(
        "ColumnDictionary",
        remote_side=[id],
        foreign_keys=[referenced_column],
        uselist=False,
    )
