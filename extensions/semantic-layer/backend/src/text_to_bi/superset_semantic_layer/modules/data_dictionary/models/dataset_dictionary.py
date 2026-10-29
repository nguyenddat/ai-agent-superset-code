from sqlalchemy import Column, ForeignKey, Integer, String, Text

from ....common.base_model import AuditedModel


class DatasetDictionary(AuditedModel):
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
    # For a table that keeps one value per indicator, or the table naming the indicators: JSON, see
    # modules/data_dictionary/indicators.py.
    indicator_model = Column(Text, nullable=True)
