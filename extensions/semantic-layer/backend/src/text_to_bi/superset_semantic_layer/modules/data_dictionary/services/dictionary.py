import threading
import time
from typing import Any

from superset.connectors.sqla.models import SqlaTable

from ....common.utils.type_formatter import json_list
from ...superset.services.datasets import get_dataset, get_datasets
from ..dependencies import column_dictionary_repository, dataset_grain_repository
from ..exceptions import DataDictionaryValidationError
from ..models import ColumnDictionary, DatasetDictionary
from .column_semantics import checked_column_semantics
from .indicators import stored_indicator_model
from .time_semantics import checked_temporal_kind

DICTIONARY_FIELDS = {
    "aggregations",
    "business_term",
    "default_value",
    "description",
    "display_name",
    "format",
    "is_fk",
    "is_pk",
    "is_unique",
    "nullable",
    "referenced_column",
    "referenced_dataset_id",
    "referenced_column_name",
    "semantic_role",
    "synonyms",
    "temporal_kind",
    "unit",
}

STRING_FIELD_LIMITS = {"display_name": 255}

OPTIONAL_STRING_FIELD_LIMITS = {"format": 128, "unit": 128}

DATASET_DICTIONARY_FIELDS = {
    "display_name", "description", "grain", "create_column", "dataset_type", "layer_id", "indicator_model",
}

# Saved together: the grains are checked against the time column and the column telling kinds of rows apart.
DATASET_TIME_FIELDS = {"time_column", "row_kind_column", "grains"}

# A suggestion run for a dataset older than this is treated as abandoned, so a lost run cannot block the dataset.
SUGGEST_INFLIGHT_TTL_SECONDS = 15 * 60

_suggest_inflight: dict[int, float] = {}

_suggest_inflight_lock = threading.Lock()



def claim_suggestion(dataset_id: int) -> bool:
    """Mark a dataset as being suggested; False when another run for it is still active."""
    now = time.monotonic()
    with _suggest_inflight_lock:
        started = _suggest_inflight.get(dataset_id)
        if started is not None and now - started < SUGGEST_INFLIGHT_TTL_SECONDS:
            return False
        _suggest_inflight[dataset_id] = now
        return True



def release_suggestion(dataset_id: int) -> None:
    with _suggest_inflight_lock:
        _suggest_inflight.pop(dataset_id, None)



def validate_dictionary_payload(payload: Any, actual_column_names: set[str], dataset_id: int) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("columns"), list):
        raise DataDictionaryValidationError("Request body must contain a columns array.")

    normalized: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for index, item in enumerate(payload["columns"]):
        if not isinstance(item, dict):
            raise DataDictionaryValidationError(f"columns[{index}] must be an object.")
        unknown_fields = set(item) - DICTIONARY_FIELDS - {"column_name"}
        if unknown_fields:
            raise DataDictionaryValidationError(
                f"columns[{index}] contains unsupported fields: {', '.join(sorted(unknown_fields))}."
            )
        column_name = item.get("column_name")
        if not isinstance(column_name, str) or not column_name:
            raise DataDictionaryValidationError(f"columns[{index}].column_name must be a non-empty string.")
        if column_name not in actual_column_names:
            raise DataDictionaryValidationError(f"Unknown dataset column: {column_name}.")
        if column_name in seen_names:
            raise DataDictionaryValidationError(f"Duplicate dataset column: {column_name}.")
        seen_names.add(column_name)

        values = {"column_name": column_name}
        for field, max_length in STRING_FIELD_LIMITS.items():
            if field not in item:
                continue
            value = item[field]
            if not isinstance(value, str) or not value.strip():
                raise DataDictionaryValidationError(f"columns[{index}].{field} must be a non-empty string.")
            if len(value) > max_length:
                raise DataDictionaryValidationError(
                    f"columns[{index}].{field} must be at most {max_length} characters."
                )
            values[field] = value
        for field in ("default_value", "business_term"):
            if field in item:
                value = item[field]
                if value is not None and not isinstance(value, str):
                    raise DataDictionaryValidationError(f"columns[{index}].{field} must be a string or null.")
                if field == "business_term" and value is not None and not value.strip():
                    value = None
                values[field] = value
        for field in ("nullable", "is_pk", "is_fk", "is_unique"):
            if field in item:
                if not isinstance(item[field], bool):
                    raise DataDictionaryValidationError(f"columns[{index}].{field} must be a boolean.")
                values[field] = item[field]
        if "referenced_dataset_id" in item or "referenced_column_name" in item:
            referenced_dataset_id = item.get("referenced_dataset_id")
            referenced_column_name = item.get("referenced_column_name")
            if referenced_dataset_id is None and referenced_column_name is None:
                values["referenced_dataset_id"] = None
                values["referenced_column_name"] = None
            elif (
                isinstance(referenced_dataset_id, bool)
                or not isinstance(referenced_dataset_id, int)
                or not isinstance(referenced_column_name, str)
                or not referenced_column_name
            ):
                raise DataDictionaryValidationError(
                    f"columns[{index}] must specify both a referenced dataset and column."
                )
            else:
                referenced_dataset = get_dataset(referenced_dataset_id)
                if referenced_dataset is None:
                    raise DataDictionaryValidationError(f"Unknown referenced dataset: {referenced_dataset_id}.")
                referenced_column_names = {str(column.column_name) for column in referenced_dataset.columns}
                if referenced_column_name not in referenced_column_names:
                    raise DataDictionaryValidationError(f"Unknown referenced column: {referenced_column_name}.")
                if referenced_dataset_id == dataset_id and referenced_column_name == column_name:
                    raise DataDictionaryValidationError("A column cannot reference itself.")
                values["referenced_dataset_id"] = referenced_dataset_id
                values["referenced_column_name"] = referenced_column_name
        elif "referenced_column" in item:
            referenced_column = item["referenced_column"]
            if referenced_column is not None and not isinstance(referenced_column, str):
                raise DataDictionaryValidationError(
                    f"columns[{index}].referenced_column must be a column name or null."
                )
            if referenced_column == column_name:
                raise DataDictionaryValidationError("A column cannot reference itself.")
            if referenced_column is not None and referenced_column not in actual_column_names:
                raise DataDictionaryValidationError(f"Unknown referenced column: {referenced_column}.")
            values["referenced_dataset_id"] = dataset_id if referenced_column else None
            values["referenced_column_name"] = referenced_column
        for field in ("unit", "format"):
            if field in item:
                value = item[field]
                if value is not None and (
                    not isinstance(value, str) or len(value) > OPTIONAL_STRING_FIELD_LIMITS[field]
                ):
                    raise DataDictionaryValidationError(
                        f"columns[{index}].{field} must be a string of at most 128 characters or null."
                    )
                values[field] = value if value is None or value.strip() else None
        if "temporal_kind" in item:
            values["temporal_kind"] = checked_temporal_kind(item["temporal_kind"], index)
        # The stored role is not known here; the save clears aggregations on a column that ends up not a measure.
        values.update(checked_column_semantics(item, index, item.get("semantic_role")))
        normalized.append(values)
    return normalized



def serialize_dictionary(
    dataset: SqlaTable,
    dictionary: DatasetDictionary,
    columns: list[Any],
) -> dict[str, Any]:
    records = {column.column_name: column for column in columns}
    # One query per kind of record, not one per referenced column.
    referenced_ids = {row.referenced_column for row in columns if row.referenced_column is not None}
    references_by_id = (
        {row.id: row for row in column_dictionary_repository().by_ids(referenced_ids)}
        if referenced_ids
        else {}
    )
    referenced_dataset_ids = {row.dataset_id for row in references_by_id.values()}
    datasets_by_id = {row.id: row for row in get_datasets(referenced_dataset_ids)}

    def reference_values(row: ColumnDictionary) -> dict[str, Any]:
        referenced = references_by_id.get(row.referenced_column)
        referenced_dataset = datasets_by_id.get(referenced.dataset_id) if referenced else None
        database_name = getattr(getattr(referenced_dataset, "database", None), "database_name", None)
        schema_name = getattr(referenced_dataset, "schema", None) if referenced_dataset else None
        table_name = getattr(referenced_dataset, "table_name", None) if referenced_dataset else None
        label = ".".join(part for part in (database_name, schema_name, table_name) if part)
        return {
            "referenced_column": referenced.column_name if referenced else None,
            "referenced_dataset_id": referenced.dataset_id if referenced else None,
            "referenced_column_name": referenced.column_name if referenced else None,
            "referenced_dataset_label": label or (table_name if referenced else None),
        }
    grains = dataset_grain_repository().by_row_kind(dataset.id)
    return {
        "dataset_id": dataset.id,
        "dataset_name": dataset.table_name,
        "display_name": dictionary.display_name,
        "description": dictionary.description,
        "grain": dictionary.grain,
        "create_column": dictionary.create_column,
        "dataset_type": dictionary.dataset_type,
        "layer_id": dictionary.layer_id,
        "time_column": dictionary.time_column,
        "row_kind_column": dictionary.row_kind_column,
        "indicator_model": stored_indicator_model(dictionary.indicator_model),
        "grains": [
            {"row_kind_value": item.row_kind_value, "label": item.label, "grain": item.grain} for item in grains
        ],
        "read_only": False,
        "columns": [
            {
                "id": records[actual.column_name].id,
                "column_name": actual.column_name,
                "display_name": records[actual.column_name].display_name,
                "data_type": str(getattr(actual, "type", None) or "UNKNOWN")[:128],
                "nullable": records[actual.column_name].nullable,
                "default_value": records[actual.column_name].default_value,
                "is_pk": records[actual.column_name].is_pk,
                "is_fk": records[actual.column_name].is_fk,
                **reference_values(records[actual.column_name]),
                "is_unique": records[actual.column_name].is_unique,
                "unit": records[actual.column_name].unit,
                "format": records[actual.column_name].format,
                "business_term": records[actual.column_name].business_term,
                "temporal_kind": records[actual.column_name].temporal_kind,
                "semantic_role": records[actual.column_name].semantic_role,
                "aggregations": json_list(records[actual.column_name].aggregations),
                "synonyms": json_list(records[actual.column_name].synonyms),
                "description": records[actual.column_name].description,
            }
            for actual in dataset.columns
        ],
    }
