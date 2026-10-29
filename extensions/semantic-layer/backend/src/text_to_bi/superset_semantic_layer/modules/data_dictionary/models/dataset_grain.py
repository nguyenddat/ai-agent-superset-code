from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint

from ....common.base_model import AuditedModel


class DatasetGrain(AuditedModel):
    """The grain of one kind of row of a dataset, such as hourly forecasts in a table that also holds daily ones.

    ``row_kind_value`` is a value of the dataset dictionary's ``row_kind_column``; a dataset whose rows all share one
    grain has a single row with no value.
    """

    __table_args__ = (
        UniqueConstraint("dataset_id", "row_kind_value", name="uq_text_to_bi_dataset_grain_row_kind"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True)
    dataset_id = Column(
        Integer, ForeignKey("text_to_bi_dataset_dictionary.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    row_kind_value = Column(String(255), nullable=True)
    label = Column(String(255), nullable=True)
    grain = Column(String(16), nullable=False)
