from superset import db

from .repositories.user_definition import AgentUserDefinitionRepository


def user_definition_repository() -> AgentUserDefinitionRepository:
    return AgentUserDefinitionRepository(db.session)
