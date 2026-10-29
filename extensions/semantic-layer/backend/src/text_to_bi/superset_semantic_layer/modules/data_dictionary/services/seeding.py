from typing import Any

from sqlalchemy.exc import IntegrityError
from superset import db
from superset.connectors.sqla.models import SqlaTable

from ..dependencies import column_dictionary_repository, dataset_dictionary_repository
from ..models import ColumnDictionary, DatasetDictionary
from ..repositories.column_dictionary import ColumnDictionaryRepository
from ..repositories.dataset_dictionary import DatasetDictionaryRepository
from .column_semantics import default_semantic_role
from .time_semantics import default_temporal_kind


def _column_metadata_values(column: Any) -> dict[str, Any]:
    column_name = str(column.column_name)
    temporal_kind = default_temporal_kind(getattr(column, "type", None), bool(getattr(column, "is_dttm", False)))
    return {
        "column_name": column_name,
        "display_name": str(getattr(column, "verbose_name", None) or column_name)[:255],
        "data_type": str(getattr(column, "type", None) or "UNKNOWN")[:128],
        "nullable": bool(getattr(column, "nullable", True)),
        "default_value": None,
        "is_pk": False,
        "is_fk": False,
        "referenced_column": None,
        "is_unique": False,
        "unit": None,
        "format": None,
        "business_term": None,
        "temporal_kind": temporal_kind,
        "semantic_role": default_semantic_role(getattr(column, "type", None), temporal_kind, is_key=False),
    }


def _seed_dictionary_columns(
    dataset: SqlaTable,
    repository: ColumnDictionaryRepository,
) -> list[ColumnDictionary]:
    existing = {column.column_name: column for column in repository.list_for_dataset(dataset.id)}
    actual_names = {str(column.column_name) for column in dataset.columns}
    # Columns dropped or renamed in Superset leave dictionary rows behind; references to them are cleared by the FK.
    for stale_name in [name for name in existing if name not in actual_names]:
        repository.delete(existing.pop(stale_name))
    for actual_column in dataset.columns:
        column_name = str(actual_column.column_name)
        if column_name not in existing:
            values = _column_metadata_values(actual_column)
            existing[column_name] = repository.add(ColumnDictionary(dataset_id=dataset.id, **values))
    return list(existing.values())


def _get_or_create_dataset_dictionary(dataset: SqlaTable, repository: DatasetDictionaryRepository) -> DatasetDictionary:
    record = repository.get(dataset.id)
    if record is None:
        record = repository.add(
            DatasetDictionary(
                id=dataset.id,
                dataset_name=dataset.table_name,
                display_name=dataset.table_name,
                description=dataset.description,
            )
        )
    return record


def seed_dictionary(dataset: SqlaTable) -> None:
    """Sync a dataset's dictionary rows with its Superset columns and commit them.

    Committing here leaves no transaction open for what follows. Two requests seeding the same new dataset collide on
    the unique keys; the loser rolls back and retries, which then finds the rows the winner created.
    """
    for attempt in range(2):
        try:
            _get_or_create_dataset_dictionary(dataset, dataset_dictionary_repository())
            _seed_dictionary_columns(dataset, column_dictionary_repository())
            db.session.commit()
            return
        except IntegrityError:
            db.session.rollback()
            if attempt:
                raise
