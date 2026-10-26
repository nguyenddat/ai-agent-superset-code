from flask_appbuilder import Model
from sqlalchemy import Column, ForeignKey, Integer, String, Text
from superset.models.helpers import AuditMixinNullable


class DatasetDictionary(AuditMixinNullable, Model):
    __tablename__ = "text_to_bi_dataset_dictionary"
    __table_args__ = ({"extend_existing": True},)

    id = Column(Integer, ForeignKey("tables.id", ondelete="CASCADE"), primary_key=True)
    dataset_name = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    grain = Column(Text, nullable=True)
    create_column = Column(String(255), nullable=True)
    dataset_type = Column(String(32), nullable=True)
    layer_id = Column(Integer, ForeignKey("text_to_bi_data_layer.id", ondelete="SET NULL"), nullable=True, index=True)
    # The column that places a row in time, and the one that tells kinds of rows of different grains apart.
    time_column = Column(String(255), nullable=True)
    row_kind_column = Column(String(255), nullable=True)
