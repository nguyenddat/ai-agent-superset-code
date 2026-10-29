import re

from flask_appbuilder import Model
from sqlalchemy.orm import declared_attr

TABLE_PREFIX = "text_to_bi_"


class BaseModel(Model):
    """Base of every AI Agent table.

    It stays on Superset's declarative base so the tables live in Superset's metadata database beside the Semantic
    Layer's. Each table is named from its class: `AgentChatSession` is `text_to_bi_agent_chat_session`.
    """

    __abstract__ = True

    @declared_attr
    def __tablename__(cls) -> str:
        return TABLE_PREFIX + re.sub(r"(?<!^)(?=[A-Z])", "_", cls.__name__).lower()
