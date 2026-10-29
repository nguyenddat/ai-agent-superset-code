import json
from collections.abc import Iterable

from sqlalchemy.orm import Query

from superset.connectors.sqla.models import SqlaTable
from superset.models.core import Database

from ..dependencies import superset_database_repository, superset_dataset_repository
from ..exceptions import DatabaseNotFoundError, DatasetNotFoundError

# Set in a Superset database's extra JSON by simulation/superset/bootstrap_governance.py for the AI Agent reporting
# views.
INTERNAL_DATABASE_FLAG = "text_to_bi_internal"


def get_dataset(dataset_id: int) -> SqlaTable | None:
    """The Superset dataset with this ID, or None."""
    return superset_dataset_repository().get(dataset_id)


def get_datasets(dataset_ids: Iterable[int]) -> list[SqlaTable]:
    """The Superset datasets with these IDs that still exist, in no particular order."""
    return superset_dataset_repository().get_many(dataset_ids)


def datasets_by_name() -> list[SqlaTable]:
    """Every Superset dataset, by table name."""
    return superset_dataset_repository().by_name()


def datasets_on_database(database_id: int) -> Query:
    """The Superset datasets of one database connection, as a query the caller may narrow further."""
    return superset_dataset_repository().on_database(database_id)


def get_database(database_id: int) -> Database | None:
    return superset_database_repository().get(database_id)


def require_dataset(dataset_id: int) -> SqlaTable:
    dataset = get_dataset(dataset_id)
    if dataset is None:
        raise DatasetNotFoundError()
    return dataset


def require_database(database_id: int) -> Database:
    database = get_database(database_id)
    if database is None:
        raise DatabaseNotFoundError()
    return database


def is_internal_dataset(dataset: SqlaTable) -> bool:
    """Datasets on a connection marked `text_to_bi_internal`, such as the AI Agent reporting views, are not business
    data, so the Semantic Layer leaves them out of its pickers."""
    database = getattr(dataset, "database", None)
    try:
        extra = json.loads(getattr(database, "extra", None) or "{}")
    except (TypeError, ValueError):
        return False
    return isinstance(extra, dict) and extra.get(INTERNAL_DATABASE_FLAG) is True
