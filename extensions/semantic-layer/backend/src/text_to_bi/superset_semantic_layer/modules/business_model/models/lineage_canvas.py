from sqlalchemy import Column, ForeignKey, Integer, Text

from ....common.base_model import AuditedModel


class LineageCanvas(AuditedModel):
    """Lineage-view canvas of one Superset database: the cards the user moved and the edges the user shaped.

    ``layout`` is JSON: ``{"nodes": {"table-<id>" | "metric-<id>": [x, y]}, "edges": {"<edge id>": {"style",
    "coords", "waypoints", "label", "ports"}}}``. Cards and edges not listed keep the automatic layout.
    """

    __table_args__ = ({"extend_existing": True},)

    database_id = Column(Integer, ForeignKey("dbs.id", ondelete="CASCADE"), primary_key=True)
    layout = Column(Text, nullable=False)
