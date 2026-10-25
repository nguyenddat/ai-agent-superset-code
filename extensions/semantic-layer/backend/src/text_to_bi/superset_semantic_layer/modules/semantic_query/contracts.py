"""Build the deliberately narrow preview contracts available from current metadata."""

import hashlib
import json
import re
from typing import Any

_SIMPLE_AGGREGATE = re.compile(
    r'^\s*(?P<aggregation>avg|count|max|min|sum)\s*\(\s*"?(?P<column>[A-Za-z_][A-Za-z0-9_]*)"?\s*\)\s*$',
    re.IGNORECASE,
)
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_DIMENSIONS = 50
MAX_FILTERS = 50
MAX_FILTER_VALUES = 100
MAX_FILTER_STRING_LENGTH = 1024


def _metric_column(dataset: Any, metric: Any) -> Any | None:
    match = _SIMPLE_AGGREGATE.fullmatch(str(getattr(metric, "expression", "") or ""))
    if match is None:
        return None
    column_name = match.group("column")
    return next((column for column in getattr(dataset, "columns", []) if getattr(column, "column_name", None) == column_name), None)


def metric_is_eligible_for_contract(dataset: Any, metric: Any) -> bool:
    """Allow only a physical-table, active, direct-column simple aggregate.

    Superset's ``TableColumn`` does not expose sensitivity metadata.  This layer
    therefore does not invent a non-authoritative ``is_sensitive`` flag; any
    sensitivity policy must be enforced by Superset datasource/RLS permissions.
    """
    column = _metric_column(dataset, metric)
    return bool(
        not getattr(dataset, "sql", None)
        and isinstance(getattr(metric, "metric_name", None), str)
        and _IDENTIFIER.fullmatch(metric.metric_name)
        and column is not None
        and getattr(column, "is_active", None) is True
        and not getattr(column, "expression", None)
    )


def _safe_connection_identity(database: Any) -> dict[str, Any]:
    """Return a stable connection identity without putting credentials in the hash input."""
    return {
        "id": getattr(database, "id", None),
        "name": getattr(database, "database_name", None),
        "uuid": getattr(database, "uuid", None),
        "backend": getattr(database, "backend", None),
    }


# Relationship contracts use the same deliberately credential-free connection identity.
safe_connection_identity = _safe_connection_identity


def metric_contract_hash(dataset: Any, metric: Any) -> str:
    """Hash the live identity of a saved metric, including its datasource location.

    The JSON encoding deliberately distinguishes a physical table from a virtual
    dataset SQL definition.  Approval is invalid as soon as any of these values
    changes.
    """
    database = getattr(dataset, "database", None)
    metric_column = _metric_column(dataset, metric)
    payload = {
        "dataset_id": getattr(dataset, "id", None),
        "metric_id": getattr(metric, "id", None),
        "metric_name": str(getattr(metric, "metric_name", "")),
        "expression": str(getattr(metric, "expression", "")),
        "catalog": getattr(dataset, "catalog", None),
        "schema": getattr(dataset, "schema", None),
        "table": getattr(dataset, "table_name", None),
        "sql": getattr(dataset, "sql", None),
        "datasource_type": "virtual" if getattr(dataset, "sql", None) else "physical",
        "database": _safe_connection_identity(database),
        "metric_column_expression": getattr(metric_column, "expression", None),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def contract_is_approved_current(contract: Any, dataset: Any, metric: Any) -> bool:
    """Return true only for an approved record bound to this live dataset/metric."""
    return bool(
        contract
        and getattr(contract, "status", None) == "approved"
        and getattr(contract, "dataset_id", None) == getattr(dataset, "id", None)
        and getattr(contract, "metric_id", None) == getattr(metric, "id", None)
        and metric_is_eligible_for_contract(dataset, metric)
        and getattr(contract, "expression_hash", None) == metric_contract_hash(dataset, metric)
    )


def build_metric_chart_payload(dataset: Any, metric: Any, query: Any, max_rows: int) -> dict[str, Any]:
    """Make the only ChartData payload accepted by metric execution.

    This admits names from live TableColumn metadata only; it intentionally has
    no SQL, join, expression, arbitrary metric, or client-controlled row-limit
    escape hatch.
    """
    if isinstance(query, dict) and "joins" in query:
        raise ValueError("Multi-dataset joins are not supported at execution time.")
    if not isinstance(query, dict) or set(query) - {"dimensions", "filters"}:
        raise ValueError("Request may contain only dimensions and filters.")
    dimensions = query.get("dimensions", [])
    filters = query.get("filters", [])
    if not isinstance(dimensions, list) or not isinstance(filters, list):
        raise ValueError("dimensions and filters must be arrays.")  # noqa: TRY004
    if len(dimensions) > MAX_DIMENSIONS or len(filters) > MAX_FILTERS:
        raise ValueError("Too many dimensions or filters.")
    columns = {str(getattr(column, "column_name", "")): column for column in getattr(dataset, "columns", [])}

    def allowed(name: Any, capability: str) -> str:
        if not isinstance(name, str) or name not in columns:
            raise ValueError("Unknown dataset column.")
        column = columns[name]
        # These are the capability fields actually present on Superset
        # TableColumn. Datasource/RLS access remains ChartData's responsibility.
        if (
            getattr(column, "is_active", None) is not True
            or getattr(column, capability, None) is not True
        ):
            raise ValueError("Column is not available for this operation.")
        if getattr(column, "expression", None):
            raise ValueError("calculated columns are not available for this operation.")
        return name

    selected = [allowed(name, "groupby") for name in dimensions]
    if len(set(selected)) != len(selected):
        raise ValueError("Duplicate dimensions are not allowed.")
    chart_filters = []
    allowed_operators = {"==", "!=", "<", "<=", ">", ">=", "IN", "NOT IN"}
    for item in filters:
        if not isinstance(item, dict) or set(item) != {"column", "operator", "value"}:
            raise ValueError("Each filter requires column, operator, and value.")
        operator = item["operator"]
        if operator not in allowed_operators:
            raise ValueError("Unsupported filter operator.")
        value = item["value"]
        is_membership_operator = operator in {"IN", "NOT IN"}
        if is_membership_operator != isinstance(value, list):
            raise ValueError("IN and NOT IN require a list; scalar operators require a scalar value.")
        values = value if is_membership_operator else [value]
        if not values or len(values) > MAX_FILTER_VALUES or any(not _scalar_filter_value(item) for item in values):
            raise ValueError("Filter value must be a bounded non-null scalar or list of scalars.")
        chart_filters.append({"col": allowed(item["column"], "filterable"), "op": operator, "val": value})
    return {
        "datasource": {"id": dataset.id, "type": "table"},
        "queries": [{"columns": selected, "metrics": [metric.metric_name], "filters": chart_filters, "row_limit": max_rows + 1}],
        "result_type": "full",
        "result_format": "json",
    }


def execute_approved_chart_query(
    contract: Any, dataset: Any, metric: Any, query: Any, max_rows: int, runner: Any
) -> Any:
    """Gate the ChartData runner before it can validate or execute anything."""
    if not contract_is_approved_current(contract, dataset, metric):
        raise PermissionError("A current approved metric contract is required.")
    return runner(build_metric_chart_payload(dataset, metric, query, max_rows))


def _scalar_filter_value(value: Any) -> bool:
    if isinstance(value, str):
        return len(value) <= MAX_FILTER_STRING_LENGTH
    return isinstance(value, (int, float, bool))


def build_preview_contract(dataset: Any, dictionary_columns: list[Any]) -> dict[str, Any]:
    """Return safe ephemeral contracts from a dataset's curated Superset metadata.

    There is not yet a persisted metric-contract approval model. The caller must
    therefore treat this as preview-only and never execute its compiled SQL.
    """
    dataset_name = str(dataset.table_name)
    schema = getattr(dataset, "schema", None)
    table_name = f"{schema}.{dataset_name}" if schema else dataset_name
    engine = str(dataset.database.db_engine_spec.engine).lower()
    live_columns = {str(column.column_name) for column in dataset.columns}
    dictionary_column_names = {str(column.column_name) for column in dictionary_columns}
    metrics = []
    for metric in dataset.metrics:
        match = _SIMPLE_AGGREGATE.fullmatch(str(metric.expression or ""))
        metric_name = getattr(metric, "metric_name", None)
        if match is None or not isinstance(metric_name, str) or _IDENTIFIER.fullmatch(metric_name) is None:
            continue
        column = match.group("column")
        if column not in live_columns:
            continue
        metrics.append(
            {
                "name": metric_name,
                "dataset": dataset_name,
                "eligible_for_preview": True,
                "aggregation": match.group("aggregation").lower(),
                "column": column,
            }
        )
    dimensions = [
        {"name": column, "dataset": dataset_name, "eligible_for_preview": True, "column": column}
        for column in sorted(live_columns & dictionary_column_names)
    ]
    return {
        "dataset": {"name": dataset_name, "table": table_name, "dialect": engine},
        "metrics": metrics,
        "dimensions": dimensions,
        "contract_source": "curated_superset_metric_and_dictionary",
    }
