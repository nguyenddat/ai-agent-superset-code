import json
from typing import Any

from ...semantic_query.services.relationship_discovery import type_family
from ..exceptions import DataDictionaryValidationError

ROLES = ("key", "measure", "dimension", "label", "time", "row_kind", "attribute")
AGGREGATIONS = ("SUM", "AVG", "MIN", "MAX", "COUNT", "COUNT_DISTINCT")
MAX_SYNONYMS = 20
MAX_SYNONYM_LENGTH = 100
MAX_DESCRIPTION_LENGTH = 2000


def default_semantic_role(
    data_type: Any, temporal_kind: str | None, is_key: bool, is_row_kind: bool = False,
) -> str:
    """The role a column most likely plays, read from what the dictionary already knows about it."""
    if is_key:
        return "key"
    if is_row_kind:
        return "row_kind"
    if temporal_kind:
        return "time"
    if type_family(data_type) == "number":
        return "measure"
    return "dimension"


def checked_column_semantics(item: dict[str, Any], index: int, role_after_save: str | None) -> dict[str, Any]:
    """The semantic fields of one column update, as stored: lists become JSON text, blank text becomes NULL.

    `role_after_save` is the column's role once the update applies, so aggregations are only kept on a measure; None
    when the update leaves the role as stored, which the caller then checks. Raises ValueError with a message for the
    administrator.
    """
    values: dict[str, Any] = {}
    if "semantic_role" in item:
        if item["semantic_role"] not in ROLES:
            raise DataDictionaryValidationError(f"columns[{index}].semantic_role must be one of {', '.join(ROLES)}.")
        values["semantic_role"] = item["semantic_role"]
    if "aggregations" in item:
        aggregations = item["aggregations"]
        if not isinstance(aggregations, list) or any(value not in AGGREGATIONS for value in aggregations):
            raise DataDictionaryValidationError(
                f"columns[{index}].aggregations must be a list of {', '.join(AGGREGATIONS)}."
            )
        if aggregations and role_after_save not in (None, "measure"):
            raise DataDictionaryValidationError(f"columns[{index}].aggregations are only declared on a measure.")
        ordered = [value for value in AGGREGATIONS if value in aggregations]
        values["aggregations"] = json.dumps(ordered) if ordered else None
    if "synonyms" in item:
        synonyms = item["synonyms"]
        if not isinstance(synonyms, list) or any(not isinstance(value, str) for value in synonyms):
            raise DataDictionaryValidationError(f"columns[{index}].synonyms must be a list of strings.")
        cleaned = list(dict.fromkeys(value.strip() for value in synonyms if value.strip()))
        if len(cleaned) > MAX_SYNONYMS or any(len(value) > MAX_SYNONYM_LENGTH for value in cleaned):
            raise DataDictionaryValidationError(
                f"columns[{index}].synonyms may hold {MAX_SYNONYMS} words of at most {MAX_SYNONYM_LENGTH} characters.",
            )
        values["synonyms"] = json.dumps(cleaned, ensure_ascii=False) if cleaned else None
    if "description" in item:
        description = item["description"]
        if description is not None and (not isinstance(description, str) or len(description) > MAX_DESCRIPTION_LENGTH):
            raise DataDictionaryValidationError(
                f"columns[{index}].description must be a string of at most {MAX_DESCRIPTION_LENGTH} characters."
            )
        values["description"] = description.strip() if isinstance(description, str) and description.strip() else None
    return values
