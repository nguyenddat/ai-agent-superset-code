"""The schema graph the AI Agent's schema link searches: base tables as nodes, approved relationships as edges.

Only physical datasets classified as base are nodes, and only those the caller may read without a row-level security
rule; schema link writes its own SQL, which Superset's dataset RLS would not filter. An edge is a current approved
relationship contract whose both ends are nodes, so a hidden table takes its edges with it; the route picks those.

Each node carries what linking needs to find data in it: column roles, aggregations, synonyms, coded values, the time
column and grain of each kind of row, the indicators of an indicator catalog, and the table's data layer for drawing.
The graph holds metadata only; building it runs no query of the caller's data beyond the coded values and indicators.
"""

from typing import Any

from ..data_dictionary.column_semantics import json_list

GRAPH_VERSION = 1


def column_node(live: Any, entry: Any | None, values: list[str] | None) -> dict[str, Any]:
    """A column as schema link sees it; a column the dictionary has not seeded yet carries only its live facts."""
    name = str(live.column_name)

    def field(attribute: str, default: Any = None) -> Any:
        return getattr(entry, attribute, default) if entry is not None else default

    return {
        "name": name,
        "label": field("display_name") or getattr(live, "verbose_name", None) or name,
        "type": str(getattr(live, "type", None) or ""),
        "role": field("semantic_role"),
        "aggregations": json_list(field("aggregations")),
        "synonyms": json_list(field("synonyms")),
        "description": field("description") or field("business_term"),
        "unit": field("unit"),
        "temporal_kind": field("temporal_kind"),
        "is_pk": bool(field("is_pk", False)),
        "is_unique": bool(field("is_unique", False)),
        "is_fk": bool(field("is_fk", False)),
        "values": values or [],
    }


def table_node(
    dataset: Any,
    dictionary: Any | None,
    entries: dict[str, Any],
    grains: list[Any],
    coded_values: dict[str, list[str]],
    indicator_model: dict[str, Any] | None,
    indicators: dict[str, Any] | None,
    layer: Any | None,
) -> dict[str, Any]:
    """A base table with its columns, time, grains, indicators and layer; `indicator_model` as already read.

    Calculated and inactive columns are left out: schema link joins and filters physical columns only.
    """
    live_columns = [
        column for column in getattr(dataset, "columns", [])
        if getattr(column, "is_active", None) is True and not getattr(column, "expression", None)
    ]
    return {
        "dataset_id": dataset.id,
        "schema": getattr(dataset, "schema", None),
        "table": dataset.table_name,
        "label": getattr(dictionary, "display_name", None) or dataset.table_name,
        "description": getattr(dictionary, "description", None) or getattr(dataset, "description", None),
        "grain_description": getattr(dictionary, "grain", None),
        "layer": {"id": layer.id, "name": layer.name, "level": layer.level} if layer is not None else None,
        "time": {
            "column": getattr(dictionary, "time_column", None),
            "row_kind_column": getattr(dictionary, "row_kind_column", None),
            "row_kinds": [
                {"value": item.row_kind_value, "label": item.label, "grain": item.grain} for item in grains
            ],
        },
        "columns": [
            column_node(column, entries.get(str(column.column_name)), coded_values.get(str(column.column_name)))
            for column in live_columns
        ],
        "indicator_model": indicator_model,
        "indicators": indicators,
    }


def graph_edges(contracts: list[Any]) -> list[dict[str, Any]]:
    """The edges of approved, current contracts between nodes, in contract order."""
    return [
        {
            "id": contract.id,
            "from": {"dataset_id": contract.from_dataset_id, "column": contract.from_column},
            "to": {"dataset_id": contract.to_dataset_id, "column": contract.to_column},
            "cardinality": contract.cardinality,
        }
        for contract in sorted(contracts, key=lambda contract: contract.id)
    ]
