from flask_appbuilder import Model
from sqlalchemy import Column, Integer, String, Text
from superset.models.helpers import AuditMixinNullable


class DataLayer(AuditMixinNullable, Model):
    """Admin-defined warehouse layer (e.g. staging, core, mart) that datasets are classified into.

    ``level`` is the direction data flows: a layer feeds the layers on higher levels, while layers on one level (such as
    reference data and technical metadata) sit side by side. ``sort_order`` orders all layers, level by level.
    """

    __tablename__ = "text_to_bi_data_layer"
    __table_args__ = ({"extend_existing": True},)

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    color = Column(String(16), nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    level = Column(Integer, nullable=False, default=0)
