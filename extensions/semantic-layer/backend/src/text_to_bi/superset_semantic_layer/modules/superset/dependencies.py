from superset import db

from .repositories.database import SupersetDatabaseRepository
from .repositories.dataset import SupersetDatasetRepository
from .repositories.user import SupersetUserRepository


def superset_dataset_repository() -> SupersetDatasetRepository:
    return SupersetDatasetRepository(db.session)


def superset_database_repository() -> SupersetDatabaseRepository:
    return SupersetDatabaseRepository(db.session)


def superset_user_repository() -> SupersetUserRepository:
    return SupersetUserRepository(db.session)
