from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from ....common.base_model import AuditedModel, BaseModel


class GlossaryTerm(AuditedModel):
    """Stable identity for a governed business term."""

    __table_args__ = (
        UniqueConstraint("normalized_name", name="uq_text_to_bi_glossary_term_normalized_name"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True)
    canonical_name = Column(String(255), nullable=False)
    normalized_name = Column(String(255), nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True, index=True)
    steward_id = Column(Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True, index=True)



class GlossaryTermRevision(AuditedModel):
    """Versioned glossary content; only one current revision exists per term."""

    __table_args__ = (
        UniqueConstraint("term_id", "revision_number", name="uq_text_to_bi_glossary_revision_number"),
        CheckConstraint("status IN ('draft', 'approved', 'revoked')", name="ck_text_to_bi_glossary_revision_status"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True)
    term_id = Column(Integer, ForeignKey("text_to_bi_glossary_term.id", ondelete="CASCADE"), nullable=False, index=True)
    revision_number = Column(Integer, nullable=False)
    definition = Column(Text, nullable=False)
    synonyms = Column(JSON, nullable=False, default=list)
    provenance = Column(String(32), nullable=False, default="manual")
    source_reference = Column(String(512), nullable=True)
    source_hash = Column(String(64), nullable=True)
    content_hash = Column(String(64), nullable=False, index=True)
    status = Column(String(16), nullable=False, default="draft", index=True)
    is_current = Column(Boolean, nullable=False, default=True, index=True)
    approver_id = Column(Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True, index=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    revoker_id = Column(Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True, index=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    term = relationship("GlossaryTerm")



class GlossaryTermLink(BaseModel):
    """A revision's safe reference to a live dataset, column, or saved metric."""

    __table_args__ = (
        CheckConstraint("kind IN ('dataset', 'column', 'metric')", name="ck_text_to_bi_glossary_link_kind"),
        UniqueConstraint("revision_id", "link_key", name="uq_text_to_bi_glossary_link"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True)
    revision_id = Column(
        Integer, ForeignKey("text_to_bi_glossary_term_revision.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind = Column(String(16), nullable=False)
    link_key = Column(String(512), nullable=False)
    dataset_id = Column(Integer, ForeignKey("tables.id", ondelete="CASCADE"), nullable=False, index=True)
    column_name = Column(String(255), nullable=True)
    metric_id = Column(Integer, ForeignKey("sql_metrics.id", ondelete="CASCADE"), nullable=True, index=True)
    fingerprint = Column(String(64), nullable=False, index=True)



class GlossaryTermAuditEvent(BaseModel):
    """Append-only lifecycle evidence. Application code creates, never mutates, these rows."""

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('created', 'updated', 'approved', 'revoked')", name="ck_text_to_bi_glossary_audit_event"
        ),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True)
    term_id = Column(Integer, ForeignKey("text_to_bi_glossary_term.id", ondelete="CASCADE"), nullable=False, index=True)
    revision_id = Column(
        Integer, ForeignKey("text_to_bi_glossary_term_revision.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type = Column(String(16), nullable=False, index=True)
    actor_id = Column(Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True, index=True)
    reason = Column(String(512), nullable=True)
    revision_number = Column(Integer, nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False, index=True)
