from collections.abc import Mapping, Sequence
from math import isfinite
from typing import Any

from ..exceptions import SemanticQueryError

_IDENTIFIER_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
_AGGREGATIONS = frozenset({"avg", "count", "max", "min", "sum"})
_REQUEST_FIELDS = frozenset({"metric", "dimensions", "filters", "joins"})
_FILTER_FIELDS = frozenset({"dimension", "operator", "value"})


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SemanticQueryError(f"{label} must be an object")
    return value


def _identifier(value: Any, label: str, *, qualified: bool = False) -> str:
    if not isinstance(value, str) or not value:
        raise SemanticQueryError(f"{label} identifier is required")
    parts = value.split(".") if qualified else [value]
    if any(not part or part[0].isdigit() or any(char not in _IDENTIFIER_CHARS for char in part) for part in parts):
        raise SemanticQueryError(f"invalid {label} identifier")
    return value


def _quote(identifier: str) -> str:
    return ".".join(f'"{part}"' for part in identifier.split("."))


def _reject_unknown_fields(value: Mapping[str, Any], allowed_fields: frozenset[str], label: str) -> None:
    if any(field not in allowed_fields for field in value):
        raise SemanticQueryError(f"unknown {label} field")


def _filter_value(value: Any) -> str | int | float | bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (str, int)):
        return value
    if isinstance(value, float) and isfinite(value):
        return value
    raise SemanticQueryError("filter value must be a safe scalar")


def _named_definitions(
    definitions: Sequence[Mapping[str, Any]], label: str, dataset_name: str
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for item in definitions:
        definition = _mapping(item, label)
        if definition.get("approved") is not True or definition.get("dataset") != dataset_name:
            continue
        name = _identifier(definition.get("name"), label)
        _identifier(definition.get("column"), f"{label} column")
        if name in result:
            raise SemanticQueryError(f"duplicate {label} definition: {name}")
        result[name] = definition
    return result


def compile_semantic_query(
    dataset: Mapping[str, Any],
    approved_metrics: Sequence[Mapping[str, Any]],
    approved_dimensions: Sequence[Mapping[str, Any]],
    request: Mapping[str, Any],
) -> dict[str, Any]:
    """Compile one approved metric, optional dimensions, and bound equality filters.

    PostgreSQL ``pyformat`` placeholders are emitted and the result declares
    ``paramstyle: pyformat``. SQL text is constructed exclusively from validated
    server-side contract identifiers; request values are returned separately as parameters.
    """
    dataset = _mapping(dataset, "dataset")
    request = _mapping(request, "request")
    _reject_unknown_fields(request, _REQUEST_FIELDS, "request")
    dataset_name = _identifier(dataset.get("name"), "dataset")
    table = _identifier(dataset.get("table"), "dataset table", qualified=True)
    dialect = dataset.get("dialect")
    if dialect not in {"postgres", "postgresql"}:
        raise SemanticQueryError("unsupported SQL dialect")
    if request.get("joins"):
        raise SemanticQueryError("only a single dataset is supported; joins are unsupported")

    metrics = _named_definitions(approved_metrics, "metric", dataset_name)
    dimensions = _named_definitions(approved_dimensions, "dimension", dataset_name)
    metric_name = request.get("metric")
    metric = metrics.get(metric_name) if isinstance(metric_name, str) else None
    if metric is None:
        raise SemanticQueryError("request must name an approved metric")
    aggregation = metric.get("aggregation")
    if not isinstance(aggregation, str) or aggregation.lower() not in _AGGREGATIONS:
        raise SemanticQueryError("metric has an unsupported aggregation")
    aggregation = aggregation.upper()
    metric_column = _identifier(metric["column"], "metric column")

    requested_dimensions = request.get("dimensions", [])
    if not isinstance(requested_dimensions, list):
        raise SemanticQueryError("dimensions must be a list")
    selected_dimensions: list[Mapping[str, Any]] = []
    seen_dimensions: set[str] = set()
    for requested in requested_dimensions:
        if isinstance(requested, Mapping) and requested.get("dataset") != dataset_name:
            raise SemanticQueryError("only a single dataset is supported")
        if not isinstance(requested, str) or requested not in dimensions:
            raise SemanticQueryError("request must name an approved dimension")
        if requested in seen_dimensions:
            raise SemanticQueryError("dimensions must not be repeated")
        seen_dimensions.add(requested)
        selected_dimensions.append(dimensions[requested])

    filters = request.get("filters", [])
    if not isinstance(filters, list):
        raise SemanticQueryError("filters must be a list")
    parameters: dict[str, Any] = {}
    where_clauses: list[str] = []
    filter_provenance: list[dict[str, str]] = []
    for index, raw_filter in enumerate(filters):
        filter_item = _mapping(raw_filter, "filter")
        _reject_unknown_fields(filter_item, _FILTER_FIELDS, "filter")
        dimension_name = filter_item.get("dimension")
        if not isinstance(dimension_name, str) or dimension_name not in dimensions:
            raise SemanticQueryError("filter must name an approved dimension")
        if "value" not in filter_item:
            raise SemanticQueryError("filter value is required")
        operator = filter_item.get("operator", "=")
        if operator != "=":
            raise SemanticQueryError("unsupported filter operator")
        dimension = dimensions[dimension_name]
        column = _identifier(dimension["column"], "dimension column")
        parameter_name = f"p{index}"
        parameters[parameter_name] = _filter_value(filter_item["value"])
        where_clauses.append(f"{_quote(column)} = %({parameter_name})s")
        filter_provenance.append({"dimension": dimension_name, "column": column, "operator": operator})

    dimension_sql = [
        f'{_quote(_identifier(dimension["column"], "dimension column"))} AS "{dimension["name"]}"'
        for dimension in selected_dimensions
    ]
    select_items = dimension_sql + [f'{aggregation}({_quote(metric_column)}) AS "{metric_name}"']
    sql = [f"SELECT {', '.join(select_items)}", f"FROM {_quote(table)}"]
    if where_clauses:
        sql.append(f"WHERE {' AND '.join(where_clauses)}")
    if selected_dimensions:
        sql.append(
            "GROUP BY "
            + ", ".join(
                _quote(_identifier(dimension["column"], "dimension column")) for dimension in selected_dimensions
            )
        )

    return {
        "sql": "\n".join(sql),
        "parameters": parameters,
        "paramstyle": "pyformat",
        "provenance": {
            "dataset": dataset_name,
            "metric": {"name": metric_name, "aggregation": aggregation, "column": metric_column},
            "dimensions": [
                {"name": dimension["name"], "column": dimension["column"]} for dimension in selected_dimensions
            ],
            "filters": filter_provenance,
        },
    }
