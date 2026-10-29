from superset import db

from .repositories.business_canvas import BusinessCanvasRepository
from .repositories.business_domain import BusinessDomainRepository
from .repositories.data_layer import DataLayerRepository
from .repositories.lineage_canvas import LineageCanvasRepository
from .repositories.lineage_edge import LineageEdgeRepository


def data_layer_repository() -> DataLayerRepository:
    return DataLayerRepository(db.session)


def business_domain_repository() -> BusinessDomainRepository:
    return BusinessDomainRepository(db.session)


def business_canvas_repository() -> BusinessCanvasRepository:
    return BusinessCanvasRepository(db.session)


def lineage_canvas_repository() -> LineageCanvasRepository:
    return LineageCanvasRepository(db.session)


def lineage_edge_repository() -> LineageEdgeRepository:
    return LineageEdgeRepository(db.session)
