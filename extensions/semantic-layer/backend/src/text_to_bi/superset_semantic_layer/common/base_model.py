import re

from flask_appbuilder import Model
from sqlalchemy.orm import declared_attr
from superset.models.helpers import AuditMixinNullable

TABLE_PREFIX = "text_to_bi_"


class BaseModel(Model):
    """Base of every Semantic Layer table.

    It stays on Superset's declarative base, not a DeclarativeBase of its own, so the tables share Superset's metadata
    and can reference `tables`, `dbs` and `ab_user`. Each table is named from its class: `GlossaryTermLink` is
    `text_to_bi_glossary_term_link`. Primary keys stay per model, because the canvases key on `database_id` and a
    dataset dictionary reuses its Superset dataset ID.
    """

    __abstract__ = True

    @declared_attr
    def __tablename__(cls) -> str:
        return TABLE_PREFIX + re.sub(r"(?<!^)(?=[A-Z])", "_", cls.__name__).lower()


class AuditedModel(AuditMixinNullable, BaseModel):
    """A Semantic Layer table that also records who created and last changed each row, and when."""

    __abstract__ = True
