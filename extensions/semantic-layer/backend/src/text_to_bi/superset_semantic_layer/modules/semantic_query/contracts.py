"""Build the deliberately narrow preview contracts available from current metadata."""

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

_SIMPLE_AGGREGATE = re.compile(
    r'^\s*(?P<aggregation>avg|count|max|min|sum)\s*\(\s*"?(?P<column>[A-Za-z_][A-Za-z0-9_]*)"?\s*\)\s*$',
    re.IGNORECASE,
)
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_AGGREGATES = (exp.Avg, exp.Count, exp.Max, exp.Min, exp.Sum)
# Every node a contract metric may contain. Anything else, such as a subquery, another function, DISTINCT, FILTER or
# a window, makes the metric ineligible.
_CONTRACT_METRIC_NODES = (
    *_AGGREGATES,
    exp.Case,
    exp.If,
    exp.And,
    exp.Or,
    exp.Not,
    exp.Paren,
    exp.EQ,
    exp.NEQ,
    exp.GT,
    exp.GTE,
    exp.LT,
    exp.LTE,
    exp.In,
    exp.Is,
    exp.Column,
    exp.Identifier,
    exp.Literal,
    exp.Null,
    exp.Boolean,
    exp.Neg,
)
METRIC_CONTRACT_RULE = (
    "Công thức phải là đúng một AVG, COUNT, MAX, MIN hoặc SUM trên cột của dataset, có thể ở dạng "
    "CASE WHEN <so sánh cột với hằng số> THEN <cột hoặc số> END."
)
MAX_DIMENSIONS = 50
MAX_FILTERS = 50
MAX_FILTER_VALUES = 100
MAX_FILTER_STRING_LENGTH = 1024


@dataclass(frozen=True)
class ContractMetricFormula:
    """The parts of a metric formula that contracts accept, for review and for binding to live columns."""

    aggregation: str
    measure_column: str | None
    measure_constant: str | None
    condition: str | None
    columns: frozenset[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "aggregation": self.aggregation,
            "measure_column": self.measure_column,
            "measure_constant": self.measure_constant,
            "condition": self.condition,
            "columns": sorted(self.columns),
        }


def parse_contract_metric(expression: str) -> ContractMetricFormula | None:
    """Parse ``AGG(column)`` or ``AGG(CASE WHEN condition THEN column-or-number END)``; None for any other formula.

    The condition may only compare unqualified columns with constants.
    """
    try:
        tree = sqlglot.parse_one(expression)
    except SqlglotError:
        return None
    if not isinstance(tree, _AGGREGATES):
        return None
    nodes = list(tree.walk())
    if any(not isinstance(node, _CONTRACT_METRIC_NODES) for node in nodes):
        return None
    if any(isinstance(node, _AGGREGATES) for node in nodes if node is not tree):
        return None
    columns = list(tree.find_all(exp.Column))
    if not columns or any(column.table for column in columns):
        return None
    measure = tree.this
    condition = None
    if isinstance(measure, exp.Case):
        branches = measure.args.get("ifs") or []
        default = measure.args.get("default")
        if len(branches) != 1 or not (default is None or isinstance(default, exp.Null)):
            return None
        condition = branches[0].this.sql(dialect="postgres")
        measure = branches[0].args.get("true")
        if not isinstance(measure, (exp.Column, exp.Literal, exp.Neg)):
            return None
    elif not isinstance(measure, exp.Column):
        return None
    return ContractMetricFormula(
        aggregation=tree.key.upper(),
        measure_column=measure.name if isinstance(measure, exp.Column) else None,
        measure_constant=None if isinstance(measure, exp.Column) else measure.sql(dialect="postgres"),
        condition=condition,
        columns=frozenset(column.name for column in columns),
    )


def _live_columns(dataset: Any) -> dict[Any, Any]:
    return {getattr(column, "column_name", None): column for column in getattr(dataset, "columns", [])}


def _metric_column(dataset: Any, metric: Any) -> Any | None:
    """The live column a contract metric measures, or None for a constant measure or an ineligible formula."""
    formula = parse_contract_metric(str(getattr(metric, "expression", "") or ""))
    return _live_columns(dataset).get(formula.measure_column) if formula and formula.measure_column else None


def metric_contract_ineligibility(dataset: Any, metric: Any) -> str | None:
    """Why a metric cannot have a contract, or None when it can.

    Superset's ``TableColumn`` does not expose sensitivity metadata.  This layer
    therefore does not invent a non-authoritative ``is_sensitive`` flag; any
    sensitivity policy must be enforced by Superset datasource/RLS permissions.

    A virtual dataset is eligible: its SQL is part of the contract hash, so editing it voids an approval.
    """
    metric_name = getattr(metric, "metric_name", None)
    if not isinstance(metric_name, str) or not _IDENTIFIER.fullmatch(metric_name):
        return "Tên metric chỉ được gồm chữ cái không dấu, chữ số và dấu gạch dưới."
    formula = parse_contract_metric(str(getattr(metric, "expression", "") or ""))
    if formula is None:
        return METRIC_CONTRACT_RULE
    live_columns = _live_columns(dataset)
    for column_name in sorted(formula.columns):
        column = live_columns.get(column_name)
        if column is None:
            return f"Cột {column_name} không có trong dataset."
        if getattr(column, "is_active", None) is not True:
            return f"Cột {column_name} đang bị tắt (không active)."
        if getattr(column, "expression", None):
            return f"Cột {column_name} là cột tính toán."
    return None


def metric_is_eligible_for_contract(dataset: Any, metric: Any) -> bool:
    return metric_contract_ineligibility(dataset, metric) is None


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


def metric_contract_state(contract: Any, dataset: Any, metric: Any) -> str:
    """The review state an administrator sees for a metric.

    ``outdated`` is a candidate or approval whose metric changed after it was recorded, so it can be neither
    approved nor executed until a new candidate is created.
    """
    eligible = metric_is_eligible_for_contract(dataset, metric)
    status = getattr(contract, "status", None)
    if contract is None:
        return "not_started" if eligible else "ineligible"
    if status == "revoked":
        return "revoked"
    if status == "approved":
        return "approved" if contract_is_approved_current(contract, dataset, metric) else "outdated"
    unchanged = eligible and getattr(contract, "expression_hash", None) == metric_contract_hash(dataset, metric)
    return "candidate" if unchanged else "outdated"


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
    contract: Any, dataset: Any, metric: Any, query: Any, max_rows: int, runner: Any, allow_candidate: bool = False
) -> Any:
    """Gate the ChartData runner before it can validate or execute anything.

    ``allow_candidate`` lets a candidate whose metric is unchanged since it was proposed run: callers grant it to
    administrators, as a review preview, and to a candidate the AI Agent built, as a provisional figure. Any other
    metric runs only once approved.
    """
    previewable = (
        allow_candidate and contract is not None and metric_contract_state(contract, dataset, metric) == "candidate"
    )
    if not previewable and not contract_is_approved_current(contract, dataset, metric):
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
