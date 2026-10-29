from superset.connectors.sqla.models import SqlaTable

from ...agent_ladder.services.agent_ladder import BASE_DATASET
from ...data_dictionary.dependencies import column_dictionary_repository, dataset_dictionary_repository
from ...data_dictionary.models import ColumnDictionary
from ...superset.services.datasets import get_dataset
from .relationships import RelationshipEnd


def relationship_ends(fk_entry: ColumnDictionary) -> tuple[RelationshipEnd, RelationshipEnd] | None:
    """Resolve a dictionary FK to live datasets, retaining composite-key information."""
    if not fk_entry.referenced_column:
        return None
    column_repository = column_dictionary_repository()
    target_entry = column_repository.get(fk_entry.referenced_column)
    if target_entry is None:
        return None
    source = get_dataset(fk_entry.dataset_id)
    target = get_dataset(target_entry.dataset_id)
    if source is None or target is None:
        return None

    def end(dataset: SqlaTable, entry: ColumnDictionary) -> RelationshipEnd:
        live_names = {str(column.column_name) for column in dataset.columns}
        pk_count = sum(1 for row in column_repository.primary_keys(dataset.id) if row.column_name in live_names)
        return RelationshipEnd(dataset=dataset, entry=entry, pk_count=pk_count)

    return end(source, fk_entry), end(target, target_entry)


def base_tables(database_id: int) -> list[SqlaTable]:
    """Physical datasets classified as base on one database: the tables schema link may join."""
    rows = dataset_dictionary_repository().datasets_of_type(database_id, BASE_DATASET)
    return [dataset for dataset, _dictionary in rows if not dataset.sql]
