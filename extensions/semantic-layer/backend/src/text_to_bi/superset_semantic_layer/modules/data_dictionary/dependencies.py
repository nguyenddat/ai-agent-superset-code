from superset import db

from .repositories.column_dictionary import ColumnDictionaryRepository
from .repositories.dataset_dictionary import DatasetDictionaryRepository
from .repositories.dataset_grain import DatasetGrainRepository


def column_dictionary_repository() -> ColumnDictionaryRepository:
    return ColumnDictionaryRepository(db.session)


def dataset_dictionary_repository() -> DatasetDictionaryRepository:
    return DatasetDictionaryRepository(db.session)


def dataset_grain_repository() -> DatasetGrainRepository:
    return DatasetGrainRepository(db.session)
