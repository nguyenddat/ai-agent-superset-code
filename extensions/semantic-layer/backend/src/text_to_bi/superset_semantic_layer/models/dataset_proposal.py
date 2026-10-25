from flask_appbuilder import Model
from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text


class DatasetProposal(Model):
    """A dataset the AI Agent drafted over base datasets when no aggregate dataset could answer a question.

    Nothing runs until an administrator reviews the SQL and creates it: creating makes a Superset virtual dataset, an
    aggregate dataset in the data dictionary, with the proposed metric as an AI Agent candidate on it.
    """

    __tablename__ = "text_to_bi_dataset_proposal"
    __table_args__ = ({"extend_existing": True},)

    id = Column(Integer, primary_key=True)
    name = Column(String(250), nullable=False)
    label = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    sql = Column(Text, nullable=False)
    sql_fingerprint = Column(String(64), nullable=False, index=True)
    database_id = Column(Integer, nullable=False)
    schema = Column(String(255), nullable=True)
    # {metric_name, label, expression, definition, unit}: the metric the question needs on the new dataset.
    metric = Column(JSON, nullable=False)
    source_dataset_ids = Column(JSON, nullable=False)
    question = Column(Text, nullable=True)
    # `pending`, then `created` or `rejected`.
    status = Column(String(16), nullable=False, default="pending", index=True)
    proposer_id = Column(Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True, index=True)
    created_on = Column(DateTime(timezone=True), nullable=False)
    reviewer_id = Column(Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True)
    reviewed_on = Column(DateTime(timezone=True), nullable=True)
    review_note = Column(Text, nullable=True)
    dataset_id = Column(Integer, ForeignKey("tables.id", ondelete="SET NULL"), nullable=True)
