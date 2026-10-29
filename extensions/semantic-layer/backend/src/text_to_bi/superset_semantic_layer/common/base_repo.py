from typing import Any, Generic, TypeVar

from flask_appbuilder import Model
from sqlalchemy.orm import Query, Session

ModelType = TypeVar("ModelType", bound=Model)


class BaseRepository(Generic[ModelType]):
    """Database access for one model, on the request's session; committing stays with the caller."""

    def __init__(self, session: Session, model: type[ModelType]) -> None:
        self.session = session
        self.model = model

    def query(self) -> Query:
        return self.session.query(self.model)

    def get(self, entity_id: Any) -> ModelType | None:
        return self.session.get(self.model, entity_id)

    def list(self, *, offset: int = 0, limit: int = 100) -> list[ModelType]:
        return self.query().offset(offset).limit(limit).all()

    def add(self, entity: ModelType, *, flush: bool = True) -> ModelType:
        """Add a new row; flushing assigns its ID and surfaces a constraint error now rather than at commit."""
        self.session.add(entity)
        if flush:
            self.session.flush()
        return entity

    def add_all(self, entities: Any) -> None:
        self.session.add_all(entities)

    def update(self, entity: ModelType, values: dict[str, Any]) -> ModelType:
        for attribute, value in values.items():
            setattr(entity, attribute, value)
        self.session.flush()
        return entity

    def delete(self, entity: ModelType) -> None:
        self.session.delete(entity)

    def delete_by_id(self, entity_id: Any) -> bool:
        entity = self.get(entity_id)
        if entity is None:
            return False
        self.delete(entity)
        return True

    def flush(self) -> None:
        self.session.flush()
