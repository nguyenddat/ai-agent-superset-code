from superset import db

from .repositories.question import AgentQuestionHandlingRepository, AgentQuestionRepository


def question_repository() -> AgentQuestionRepository:
    return AgentQuestionRepository(db.session)


def question_handling_repository() -> AgentQuestionHandlingRepository:
    return AgentQuestionHandlingRepository(db.session)
