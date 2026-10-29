from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from ....common.base_model import AuditedModel


class RelationshipContract(AuditedModel):
    """Approval record for a dictionary foreign-key relationship.

    An approved, current contract on base tables is an edge the AI Agent's schema link may join on. ``verification``
    holds, as JSON, what the last data check found; it counts only while ``verified_hash`` equals ``contract_hash``.
    """

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
    # Where the relationship was found: `database`, `dictionary` or `naming`.
    source = Column(String(16), nullable=True)
    verification = Column(Text, nullable=True)
    verified_hash = Column(String(64), nullable=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)
