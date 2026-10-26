"""What a column means to schema link: its role, the aggregations that make sense on it, and the words people use.

Schema link locates the data a question needs among the base tables' columns, so each column says whether it is a key
to join on, a measure to aggregate, a dimension to group or filter by, a label naming a key, a time, the column telling
kinds of rows apart, or another attribute. A measure lists the aggregations that make sense on it, since summing
temperatures, for one, gives a number that means nothing.

A new column takes a role from its keys, its temporal kind and its type; the administrator corrects it.
"""

import json
import re
from typing import Any

ROLES = ("key", "measure", "dimension", "label", "time", "row_kind", "attribute")
AGGREGATIONS = ("SUM", "AVG", "MIN", "MAX", "COUNT", "COUNT_DISTINCT")
MAX_SYNONYMS = 20
MAX_SYNONYM_LENGTH = 100
MAX_DESCRIPTION_LENGTH = 2000
_NUMERIC_TYPE = re.compile(r"INT|NUMERIC|DECIMAL|FLOAT|DOUBLE|REAL", re.IGNORECASE)


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
    if _NUMERIC_TYPE.search(str(data_type or "")):
        return "measure"
    return "dimension"


def json_list(value: Any) -> list[str]:
    """A list stored as JSON text; anything unreadable reads as empty."""
    if not value:
        return []
    try:
        items = json.loads(value)
    except (TypeError, ValueError):
        return []
    return [item for item in items if isinstance(item, str)] if isinstance(items, list) else []


def checked_column_semantics(item: dict[str, Any], index: int, role_after_save: str | None) -> dict[str, Any]:
    """The semantic fields of one column update, as stored: lists become JSON text, blank text becomes NULL.

    `role_after_save` is the column's role once the update applies, so aggregations are only kept on a measure; None
    when the update leaves the role as stored, which the caller then checks. Raises ValueError with a message for the
    administrator.
    """
    values: dict[str, Any] = {}
    if "semantic_role" in item:
        if item["semantic_role"] not in ROLES:
            raise ValueError(f"columns[{index}].semantic_role must be one of {', '.join(ROLES)}.")
        values["semantic_role"] = item["semantic_role"]
    if "aggregations" in item:
        aggregations = item["aggregations"]
        if not isinstance(aggregations, list) or any(value not in AGGREGATIONS for value in aggregations):
            raise ValueError(f"columns[{index}].aggregations must be a list of {', '.join(AGGREGATIONS)}.")
        if aggregations and role_after_save not in (None, "measure"):
            raise ValueError(f"columns[{index}].aggregations are only declared on a measure.")
        ordered = [value for value in AGGREGATIONS if value in aggregations]
        values["aggregations"] = json.dumps(ordered) if ordered else None
    if "synonyms" in item:
        synonyms = item["synonyms"]
        if not isinstance(synonyms, list) or any(not isinstance(value, str) for value in synonyms):
            raise ValueError(f"columns[{index}].synonyms must be a list of strings.")
        cleaned = list(dict.fromkeys(value.strip() for value in synonyms if value.strip()))
        if len(cleaned) > MAX_SYNONYMS or any(len(value) > MAX_SYNONYM_LENGTH for value in cleaned):
            raise ValueError(
                f"columns[{index}].synonyms may hold {MAX_SYNONYMS} words of at most {MAX_SYNONYM_LENGTH} characters.",
            )
        values["synonyms"] = json.dumps(cleaned, ensure_ascii=False) if cleaned else None
    if "description" in item:
        description = item["description"]
        if description is not None and (not isinstance(description, str) or len(description) > MAX_DESCRIPTION_LENGTH):
            raise ValueError(f"columns[{index}].description must be a string of at most {MAX_DESCRIPTION_LENGTH} characters.")
        values["description"] = description.strip() if isinstance(description, str) and description.strip() else None
    return values
