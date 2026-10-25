from flask_appbuilder import Model
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, UniqueConstraint
from superset.models.helpers import AuditMixinNullable


class LineageEdge(AuditMixinNullable, Model):
    """Manual lineage override between two datasets.

    Edges inferred from the data dictionary are not stored. A row here adds an edge the dictionary does not describe
    (``is_manual``), suppresses an inferred edge (``is_hidden``), or only carries a display ``color`` for an inferred
    edge — such a row disappears from the diagram along with the FK that produced the edge.
    """

    __tablename__ = "text_to_bi_lineage_edge"
    __table_args__ = (
        UniqueConstraint("source_dataset_id", "target_dataset_id", "kind", name="uq_text_to_bi_lineage_edge"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True)
    source_dataset_id = Column(
        Integer,
        ForeignKey("text_to_bi_dataset_dictionary.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_dataset_id = Column(
        Integer,
        ForeignKey("text_to_bi_dataset_dictionary.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # "flow": data moves from source into target; "relation": source references target (dashed in the diagram).
    kind = Column(String(16), nullable=False)
    label = Column(String(32), nullable=True)
    is_hidden = Column(Boolean, nullable=False, default=False)
    is_manual = Column(Boolean, nullable=False, default=True)
    color = Column(String(16), nullable=True)
