"""The labelled values of a dataset's key columns, for consumers that filter a metric query by a name.

A governed metric query may filter only physical columns, so a city is filtered by `thanh_pho_key` while people ask
about "Hà Nội". A curated calculated column that labels exactly one physical column of its dataset (`ten_thanh_pho`
reads `dim_thanh_pho` by `fact_tong_hop_thoi_tiet.thanh_pho_key`) gives the key and label pairs. They are read with a
fixed ChartData payload, so Superset's datasource access and row-level security apply to them like to any chart.

The first and last date of each date column are read the same way, so a consumer can tell "no data for that period"
from "nothing matched".
"""

import re
from datetime import date, datetime, timezone
from typing import Any

MAX_MEMBERS = 500
SIMPLE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _physical_columns(dataset: Any) -> list[str]:
    return [
        str(column.column_name)
        for column in getattr(dataset, "columns", [])
        if getattr(column, "is_active", None) is True and not getattr(column, "expression", None)
        and getattr(column, "filterable", None) is True
    ]


def labelled_key_columns(dataset: Any) -> list[tuple[str, str]]:
    """`(key_column, label_column)` for each groupable calculated column that reads exactly one physical column."""
    table = re.escape(str(dataset.table_name))
    physical = _physical_columns(dataset)
    pairs = []
    for column in getattr(dataset, "columns", []):
        expression = getattr(column, "expression", None)
        groupable = getattr(column, "is_active", None) is True and getattr(column, "groupby", None) is True
        if not groupable or not expression:
            continue
        referenced = [name for name in physical if re.search(rf"\b{table}\.{re.escape(name)}\b", expression)]
        if len(referenced) == 1:
            pairs.append((referenced[0], str(column.column_name)))
    return pairs


def build_members_payload(dataset: Any, key_column: str, label_column: str) -> dict[str, Any]:
    """The only ChartData query this lookup runs: distinct key and label pairs, counted so they are grouped."""
    return {
        "datasource": {"id": dataset.id, "type": "table"},
        "queries": [{
            "columns": [key_column, label_column],
            "metrics": [{"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "row_count"}],
            "row_limit": MAX_MEMBERS + 1,
        }],
        "result_type": "full",
        "result_format": "json",
    }


def members_from_rows(rows: list[dict[str, Any]], key_column: str, label_column: str) -> list[dict[str, Any]]:
    """The pairs sorted by label; a row without a key or a label names nothing a user could ask about."""
    members = {
        row[key_column]: str(row[label_column])
        for row in rows[:MAX_MEMBERS]
        if row.get(key_column) is not None and row.get(label_column) not in (None, "")
    }
    return [{"value": value, "label": label} for value, label in sorted(members.items(), key=lambda item: item[1])]


def temporal_columns(dataset: Any) -> list[str]:
    """Physical date columns a metric query can filter, named simply enough to read their range with MIN and MAX."""
    dated = {getattr(column, "column_name", None) for column in dataset.columns if getattr(column, "is_dttm", False)}
    return [name for name in _physical_columns(dataset) if name in dated and SIMPLE_IDENTIFIER.match(name)]


def build_time_range_payload(dataset: Any, columns: list[str]) -> dict[str, Any]:
    """One aggregate row: the first and last value of each date column."""
    metrics = [
        {"expressionType": "SQL", "sqlExpression": f"{function}({name})", "label": f"{function.lower()}__{name}"}
        for name in columns for function in ("MIN", "MAX")
    ]
    return {
        "datasource": {"id": dataset.id, "type": "table"},
        "queries": [{"columns": [], "metrics": metrics, "row_limit": 1}],
        "result_type": "full",
        "result_format": "json",
    }


def _iso_date(value: Any) -> str | None:
    """ChartData gives a date as a date, a timestamp, or epoch milliseconds, depending on the driver."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date().isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and value:
        return value[:10]
    return None


def time_ranges_from_rows(rows: list[dict[str, Any]], columns: list[str]) -> list[dict[str, Any]]:
    row = rows[0] if rows else {}
    ranges = [
        {"column": name, "min": _iso_date(row.get(f"min__{name}")), "max": _iso_date(row.get(f"max__{name}"))}
        for name in columns
    ]
    return [item for item in ranges if item["min"] and item["max"]]


MAX_CODED_VALUES = 20
MAX_CODE_LENGTH = 60
_TEXT_TYPE = re.compile(r"CHAR|TEXT|STRING", re.IGNORECASE)


def coded_value_columns(dataset: Any, entries: dict[str, Any]) -> list[str]:
    """Text columns that hold codes such as a status, whose stored values a formula must spell exactly.

    Keys and unique columns are left out: their values identify rows rather than name a kind of row.
    """
    text_columns = {
        str(column.column_name) for column in getattr(dataset, "columns", []) if _TEXT_TYPE.search(str(column.type or ""))
    }
    coded = []
    for name in _physical_columns(dataset):
        entry = entries.get(name)
        if name not in text_columns or not SIMPLE_IDENTIFIER.match(name):
            continue
        if any(getattr(entry, flag, False) for flag in ("is_pk", "is_fk", "is_unique")):
            continue
        coded.append(name)
    return coded


def build_values_payload(dataset: Any, columns: list[str]) -> dict[str, Any]:
    """One grouped query per column, each stopping one row past the limit so a free-text column shows as too many."""
    return {
        "datasource": {"id": dataset.id, "type": "table"},
        "queries": [
            {
                "columns": [name],
                "metrics": [{"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "row_count"}],
                "row_limit": MAX_CODED_VALUES + 1,
            }
            for name in columns
        ],
        "result_type": "full",
        "result_format": "json",
    }


def coded_values_from_rows(rows: list[dict[str, Any]], column: str) -> list[str] | None:
    """The column's distinct values, sorted; None when it has more, or longer ones, than a code list would."""
    values = {str(row[column]) for row in rows if row.get(column) not in (None, "")}
    if len(rows) > MAX_CODED_VALUES or any(len(value) > MAX_CODE_LENGTH for value in values):
        return None
    return sorted(values)
