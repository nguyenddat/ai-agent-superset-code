from superset import db

from .repositories.metric_contract import MetricContractRepository
from .repositories.metric_contract_event import MetricContractEventRepository
from .repositories.metric_definition import MetricDefinitionRepository
from .repositories.relationship_contract import RelationshipContractRepository


def metric_contract_repository() -> MetricContractRepository:
    return MetricContractRepository(db.session)


def metric_contract_event_repository() -> MetricContractEventRepository:
    return MetricContractEventRepository(db.session)


def metric_definition_repository() -> MetricDefinitionRepository:
    return MetricDefinitionRepository(db.session)


def relationship_contract_repository() -> RelationshipContractRepository:
    return RelationshipContractRepository(db.session)
