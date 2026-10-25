from flask_appbuilder import Model
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
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
