from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.model_base import BaseModel


ModelType = TypeVar("ModelType", bound=BaseModel)


class RepositoryBase(Generic[ModelType]):
    """Common synchronous SQLAlchemy operations for extension repositories."""

    def __init__(self, session: Session, model: type[ModelType]) -> None:
        self.session = session
        self.model = model

    def get(self, entity_id: int) -> ModelType | None:
        return self.session.get(self.model, entity_id)

    def list(self, *, offset: int = 0, limit: int = 100) -> list[ModelType]:
        statement = select(self.model).offset(offset).limit(limit)
        return list(self.session.scalars(statement).all())

    def add(self, entity: ModelType) -> ModelType:
        self.session.add(entity)
        self.session.flush()
        return entity

    def delete(self, entity: ModelType) -> None:
        self.session.delete(entity)

    def delete_by_id(self, entity_id: int) -> bool:
        entity = self.get(entity_id)
        if entity is None:
            return False
        self.delete(entity)
        return True
