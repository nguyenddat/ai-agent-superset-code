"""The labelled values of a dataset's key columns, for consumers that filter a metric query by a name.

A governed metric query may filter only physical columns, so a city is filtered by `thanh_pho_key` while people ask
about "Hà Nội". A curated calculated column that labels exactly one physical column of its dataset (`ten_thanh_pho`
reads `dim_thanh_pho` by `fact_tong_hop_thoi_tiet.thanh_pho_key`) gives the key and label pairs. They are read with a
fixed ChartData payload, so Superset's datasource access and row-level security apply to them like to any chart.
"""

import re
from typing import Any

MAX_MEMBERS = 500


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
