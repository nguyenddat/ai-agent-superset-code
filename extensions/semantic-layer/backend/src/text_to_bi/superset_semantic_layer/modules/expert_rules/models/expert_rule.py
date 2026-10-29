from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from ....common.base_model import AuditedModel, BaseModel


class ExpertRule(AuditedModel):
    __table_args__ = (
        UniqueConstraint("normalized_name", name="uq_text_to_bi_expert_rule_name"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True)
    normalized_name = Column(String(255), nullable=False, index=True)
    dataset_id = Column(Integer, ForeignKey("tables.id", ondelete="CASCADE"), nullable=False, index=True)



class ExpertRuleRevision(AuditedModel):
    __table_args__ = (
        UniqueConstraint("rule_id", "revision_number", name="uq_text_to_bi_expert_rule_revision"),
        CheckConstraint("status IN ('draft', 'approved', 'revoked')", name="ck_text_to_bi_expert_rule_status"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True)
    rule_id = Column(Integer, ForeignKey("text_to_bi_expert_rule.id", ondelete="CASCADE"), nullable=False, index=True)
    revision_number = Column(Integer, nullable=False)
    # Monotonic optimistic-concurrency token.  It deliberately differs from
    # immutable content revision_number because approve/revoke do not create
    # content revisions.
    lifecycle_version = Column(Integer, nullable=False, default=1)
    name = Column(String(255), nullable=False)
    conditions = Column(JSON, nullable=False)
    exceptions = Column(JSON, nullable=False)
    examples = Column(JSON, nullable=False)
    content_hash = Column(String(64), nullable=False, index=True)
    status = Column(String(16), nullable=False, default="draft", index=True)
    is_current = Column(Boolean, nullable=False, default=True, index=True)
    approver_id = Column(Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    revoker_id = Column(Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    rule = relationship("ExpertRule")



class ExpertRuleLink(BaseModel):
    __table_args__ = (
        CheckConstraint("kind IN ('dataset', 'glossary', 'metric')", name="ck_text_to_bi_expert_rule_link_kind"),
        UniqueConstraint("revision_id", "kind", "target_id", name="uq_text_to_bi_expert_rule_link"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True)
    revision_id = Column(
        Integer, ForeignKey("text_to_bi_expert_rule_revision.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind = Column(String(16), nullable=False)
    target_id = Column(Integer, nullable=False)
    dataset_id = Column(Integer, ForeignKey("tables.id", ondelete="CASCADE"), nullable=False, index=True)
    fingerprint = Column(String(64), nullable=False, index=True)



class ExpertRuleAuditEvent(BaseModel):
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('created', 'updated', 'approved', 'revoked')", name="ck_text_to_bi_expert_rule_audit"
        ),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True)
    # Audit evidence deliberately prevents parent deletion. Retention policy is
    # enforced by the metadata database rather than application-side cascades.
    rule_id = Column(Integer, ForeignKey("text_to_bi_expert_rule.id", ondelete="RESTRICT"), nullable=False, index=True)
    revision_id = Column(
        Integer, ForeignKey("text_to_bi_expert_rule_revision.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    event_type = Column(String(16), nullable=False, index=True)
    actor_id = Column(Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True)
    reason = Column(String(512), nullable=True)
    revision_number = Column(Integer, nullable=False)
    lifecycle_version = Column(Integer, nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False, index=True)
