from typing import Any, Generic, TypeVar

from flask_appbuilder import Model
from sqlalchemy import select
from sqlalchemy.orm import Session

ModelType = TypeVar("ModelType", bound=Model)


class BaseRepository(Generic[ModelType]):
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

    def update(self, entity: ModelType, values: dict[str, Any]) -> ModelType:
        for attribute, value in values.items():
            setattr(entity, attribute, value)
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
