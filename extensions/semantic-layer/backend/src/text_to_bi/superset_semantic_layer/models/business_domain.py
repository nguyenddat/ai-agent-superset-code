from flask_appbuilder import Model
from sqlalchemy import Column, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import relationship
from superset.models.helpers import AuditMixinNullable

# A dataset can belong to several business domains, e.g. a shared dimension used by two domains.
business_domain_dataset = Table(
    "text_to_bi_business_domain_dataset",
    Model.metadata,
    Column(
        "domain_id",
        Integer,
        ForeignKey("text_to_bi_business_domain.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "dataset_id",
        Integer,
        ForeignKey("text_to_bi_dataset_dictionary.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    ),
    extend_existing=True,
)


class BusinessDomain(AuditMixinNullable, Model):
    __tablename__ = "text_to_bi_business_domain"
    __table_args__ = ({"extend_existing": True},)

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    color = Column(String(16), nullable=True)

    datasets = relationship("DatasetDictionary", secondary=business_domain_dataset, lazy="selectin")
