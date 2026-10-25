from flask_appbuilder import Model
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from superset.models.helpers import AuditMixinNullable


class MetricContract(AuditMixinNullable, Model):
    """The explicit approval record required before a saved Superset metric can run."""

    __tablename__ = "text_to_bi_metric_contract"
    __table_args__ = (
        UniqueConstraint("dataset_id", "metric_id", name="uq_text_to_bi_metric_contract_dataset_metric"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True)
    dataset_id = Column(Integer, ForeignKey("tables.id", ondelete="CASCADE"), nullable=False, index=True)
    metric_id = Column(Integer, ForeignKey("sql_metrics.id", ondelete="CASCADE"), nullable=False, index=True)
    metric_name = Column(String(255), nullable=False)
    expression = Column(Text, nullable=False)
    expression_hash = Column(String(64), nullable=False, index=True)
    status = Column(String(16), nullable=False, default="candidate", index=True)
    owner_id = Column(Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True, index=True)
    approver_id = Column(Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True, index=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    revoker_id = Column(Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True, index=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)


class MetricContractEvent(Model):
    """Append-only history of a metric's review: proposals, approvals, revocations and definition edits.

    A contract row only keeps its latest state, so this table is the evidence of who decided what and when.
    """

    __tablename__ = "text_to_bi_metric_contract_event"
    __table_args__ = (
        CheckConstraint(
            "action IN ('candidate', 'approve', 'revoke', 'definition')", name="ck_text_to_bi_metric_event_action"
        ),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True)
    dataset_id = Column(Integer, ForeignKey("tables.id", ondelete="CASCADE"), nullable=False, index=True)
    metric_id = Column(Integer, ForeignKey("sql_metrics.id", ondelete="CASCADE"), nullable=False, index=True)
    action = Column(String(16), nullable=False)
    actor_id = Column(Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True, index=True)
    reason = Column(Text, nullable=True)
    expression = Column(Text, nullable=True)
    expression_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class MetricDefinition(AuditMixinNullable, Model):
    """What a metric means to the business: its definition, unit and the person answerable for it."""

    __tablename__ = "text_to_bi_metric_definition"
    __table_args__ = (
        UniqueConstraint("dataset_id", "metric_id", name="uq_text_to_bi_metric_definition_dataset_metric"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True)
    dataset_id = Column(Integer, ForeignKey("tables.id", ondelete="CASCADE"), nullable=False, index=True)
    metric_id = Column(Integer, ForeignKey("sql_metrics.id", ondelete="CASCADE"), nullable=False, index=True)
    business_definition = Column(Text, nullable=False)
    unit = Column(String(64), nullable=True)
    steward_id = Column(Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True, index=True)
