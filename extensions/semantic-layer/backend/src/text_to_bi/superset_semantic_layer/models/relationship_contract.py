from flask_appbuilder import Model
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from superset.models.helpers import AuditMixinNullable


class RelationshipContract(AuditMixinNullable, Model):
    """Approval record for a dictionary foreign-key relationship; it is never executable yet."""

    __tablename__ = "text_to_bi_relationship_contract"
    __table_args__ = (
        UniqueConstraint("from_dataset_id", "from_column", name="uq_text_to_bi_relationship_contract_from"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True)
    from_dataset_id = Column(Integer, ForeignKey("tables.id", ondelete="CASCADE"), nullable=False, index=True)
    from_column = Column(String(255), nullable=False)
    to_dataset_id = Column(Integer, ForeignKey("tables.id", ondelete="CASCADE"), nullable=False, index=True)
    to_column = Column(String(255), nullable=False)
    cardinality = Column(String(16), nullable=False)
    contract_hash = Column(String(64), nullable=False, index=True)
    status = Column(String(16), nullable=False, default="candidate", index=True)
    owner_id = Column(Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True, index=True)
    approver_id = Column(Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True, index=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    revoker_id = Column(Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True, index=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
