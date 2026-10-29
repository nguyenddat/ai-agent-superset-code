import hashlib
from dataclasses import dataclass
from typing import Any

from ....common.utils.type_formatter import canonical_json
from ..exceptions import RelationshipValidationError
from .contracts import safe_connection_identity

CARDINALITIES = frozenset({"many_to_one", "one_to_one"})


@dataclass(frozen=True)
class RelationshipEnd:
    dataset: Any
    entry: Any
    pk_count: int


def _live_column(end: RelationshipEnd) -> Any:
    column = next(
        (
            item
            for item in getattr(end.dataset, "columns", [])
            if getattr(item, "column_name", None) == end.entry.column_name
        ),
        None,
    )
    if column is None or getattr(column, "is_active", None) is not True or getattr(column, "expression", None):
        raise RelationshipValidationError("Relationship columns must be active live physical columns.")
    return column


def _unique_alone(end: RelationshipEnd) -> bool:
    return bool(getattr(end.entry, "is_unique", False) or (getattr(end.entry, "is_pk", False) and end.pk_count == 1))


def relationship_cardinality(source: RelationshipEnd, target: RelationshipEnd) -> str:
    """Validate an FK relationship that cannot introduce a many-to-many join."""
    if getattr(source.dataset, "id", None) == getattr(target.dataset, "id", None):
        raise RelationshipValidationError("A relationship cannot connect a dataset to itself.")
    if getattr(source.dataset, "sql", None) or getattr(target.dataset, "sql", None):
        raise RelationshipValidationError("Relationship contracts require physical datasets.")
    if getattr(getattr(source.dataset, "database", None), "id", None) != getattr(
        getattr(target.dataset, "database", None), "id", None
    ):
        raise RelationshipValidationError("Relationship contracts require datasets on the same database.")
    _live_column(source)
    _live_column(target)
    if getattr(source.entry, "is_fk", None) is not True:
        raise RelationshipValidationError("The source column must be a declared foreign key.")
    if not _unique_alone(target):
        raise RelationshipValidationError("The relationship target must be a unique or single-column primary key.")
    return "one_to_one" if _unique_alone(source) else "many_to_one"


def _end_hash_payload(end: RelationshipEnd) -> dict[str, Any]:
    column = _live_column(end)
    dataset = end.dataset
    return {
        "dataset_id": getattr(dataset, "id", None),
        "catalog": getattr(dataset, "catalog", None),
        "schema": getattr(dataset, "schema", None),
        "table": getattr(dataset, "table_name", None),
        "sql": getattr(dataset, "sql", None),
        "datasource_type": "virtual" if getattr(dataset, "sql", None) else "physical",
        "database": safe_connection_identity(getattr(dataset, "database", None)),
        "column_name": getattr(end.entry, "column_name", None),
        "live_column_type": str(getattr(column, "type", None)),
        "live_column_expression": getattr(column, "expression", None),
        "dictionary_data_type": getattr(end.entry, "data_type", None),
        "is_pk": bool(getattr(end.entry, "is_pk", False)),
        "is_unique": bool(getattr(end.entry, "is_unique", False)),
        "is_fk": bool(getattr(end.entry, "is_fk", False)),
        "pk_count": end.pk_count,
    }


def relationship_contract_hash(source: RelationshipEnd, target: RelationshipEnd, cardinality: str) -> str:
    """Hash every live property that determines relationship safety, excluding credentials."""
    if cardinality not in CARDINALITIES:
        raise RelationshipValidationError("Unsupported relationship cardinality.")
    payload = {"source": _end_hash_payload(source), "target": _end_hash_payload(target), "cardinality": cardinality}
    canonical = canonical_json(payload)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def relationship_is_approved_current(contract: Any, source: RelationshipEnd, target: RelationshipEnd) -> bool:
    """Return true only if the contract remains an approved snapshot of the live FK."""
    try:
        cardinality = relationship_cardinality(source, target)
    except ValueError:
        return False
    return bool(
        contract
        and getattr(contract, "status", None) == "approved"
        and getattr(contract, "from_dataset_id", None) == getattr(source.dataset, "id", None)
        and getattr(contract, "from_column", None) == getattr(source.entry, "column_name", None)
        and getattr(contract, "to_dataset_id", None) == getattr(target.dataset, "id", None)
        and getattr(contract, "to_column", None) == getattr(target.entry, "column_name", None)
        and getattr(contract, "cardinality", None) == cardinality
        and getattr(contract, "contract_hash", None) == relationship_contract_hash(source, target, cardinality)
    )
