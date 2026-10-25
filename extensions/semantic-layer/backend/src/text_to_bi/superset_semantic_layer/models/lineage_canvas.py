from flask_appbuilder import Model
from sqlalchemy import Column, ForeignKey, Integer, Text
from superset.models.helpers import AuditMixinNullable


class LineageCanvas(AuditMixinNullable, Model):
    """Lineage-view canvas of one Superset database: the cards the user moved and the edges the user shaped.

    ``layout`` is JSON: ``{"nodes": {"table-<id>" | "metric-<id>": [x, y]}, "edges": {"<edge id>": {"style",
    "coords", "waypoints", "label", "ports"}}}``. Cards and edges not listed keep the automatic layout.
    """

    __tablename__ = "text_to_bi_lineage_canvas"
    __table_args__ = ({"extend_existing": True},)

    database_id = Column(Integer, ForeignKey("dbs.id", ondelete="CASCADE"), primary_key=True)
    layout = Column(Text, nullable=False)
