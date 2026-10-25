"""Turns the model's query plan into governed metric queries, and their answers into one result table.

The model proposes the dataset, metrics, dimensions and filters; nothing it proposes is trusted as is. Columns and
operators are checked against the catalog, and an approved expert rule is never re-typed by the model: its filters
come from the rule's own conditions. A user's own definition has no structured conditions, so the model writes them
as filters, and they are checked like any other.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from typing import Any

OPERATORS = ("==", "!=", "<", "<=", ">", ">=", "IN", "NOT IN")
MAX_METRICS = 3
MAX_DIMENSIONS = 2
MAX_FILTERS = 12
# Rows the final answer reads; the browser receives every row the Semantic Layer returned.
ROWS_FOR_ANSWER = 60
NUMERIC_TYPES = ("INT", "NUMERIC", "DECIMAL", "FLOAT", "DOUBLE", "REAL", "BIGINT", "SMALLINT")


class QueryPlanError(ValueError):
    """The plan cannot be run as asked; the message is safe to show to the user."""


@dataclass
class PlannedQuery:
    dataset_id: int
    metrics: list[dict[str, Any]]
    dimensions: list[dict[str, Any]]
    filters: list[dict[str, Any]]
    presentation: str
    scope: str
    notes: list[str] = field(default_factory=list)

    def request_body(self) -> dict[str, Any]:
        """What the Semantic Layer's execution endpoint accepts: column names and filters, nothing else."""
        return {
            "dimensions": [dimension["name"] for dimension in self.dimensions],
            "filters": [
                {"column": item["column"], "operator": item["operator"], "value": item["value"]}
                for item in self.filters
            ],
        }


def _is_numeric(column: dict[str, Any]) -> bool:
    return any(name in str(column.get("type") or "").upper() for name in NUMERIC_TYPES)


def _coerced(value: Any, column: dict[str, Any]) -> Any:
    """A number the model wrote as text becomes a number on a numeric column; a date stays an ISO string."""
    if isinstance(value, list):
        return [_coerced(item, column) for item in value]
    if not _is_numeric(column):
        return value
    if isinstance(value, str):
        try:
            value = float(value.replace(",", "."))
        except ValueError as ex:
            raise QueryPlanError(f"Giá trị “{value}” của cột {column['name']} phải là số.") from ex
    return int(value) if isinstance(value, float) and value.is_integer() else value


def _value_labels(dataset: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """For each key column with labelled values, the label of each key, so a result says "Ha Noi" rather than 1.

    A key can have several labelling columns (a city's name and its region); the one that tells the most keys apart
    names the key itself.
    """
    labels: dict[str, dict[str, Any]] = {}
    for item in dataset.get("labelled_values", []):
        candidate = {_key(member["value"]): member["label"] for member in item.get("values", [])}
        current = labels.get(item["column"], {}).get("values", {})
        if len(set(candidate.values())) > len(set(current.values())):
            labels[item["column"]] = {"label": item.get("label"), "values": candidate}
    return labels


def _key(value: Any) -> str:
    """A key as text, so 1, 1.0 and "1" find the same label."""
    return str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)


def _shown_value(value: Any, labels: dict[str, str]) -> Any:
    if isinstance(value, list):
        return [labels.get(_key(item), item) for item in value]
    return labels.get(_key(value), value)


def _checked_filter(
    item: dict[str, Any], columns: dict[str, dict[str, Any]], source: str, value_labels: dict[str, dict[str, str]],
) -> dict[str, Any]:
    column = columns.get(item.get("column"))
    if column is None or not column.get("filterable"):
        raise QueryPlanError(f"Không lọc được theo cột “{item.get('column')}”.")
    operator = item.get("operator")
    if operator not in OPERATORS:
        raise QueryPlanError(f"Phép so sánh “{operator}” không được hỗ trợ.")
    value = item.get("value")
    if (operator in ("IN", "NOT IN")) != isinstance(value, list):
        value = value if isinstance(value, list) else [value]
        if operator not in ("IN", "NOT IN"):
            if len(value) != 1:
                raise QueryPlanError(f"Bộ lọc trên cột “{column['name']}” cần một giá trị.")
            value = value[0]
    if value is None or value == [] or value == "":
        raise QueryPlanError(f"Bộ lọc trên cột “{column['name']}” chưa có giá trị.")
    value = _coerced(value, column)
    return {
        "column": column["name"],
        "label": column.get("label") or column["name"],
        "operator": operator,
        "value": value,
        "shown_value": _shown_value(value, value_labels.get(column["name"], {}).get("values", {})),
        "source": source,
    }


def plan_query(
    plan: dict[str, Any] | None,
    catalog_datasets: list[dict[str, Any]],
    catalog_metrics: list[dict[str, Any]],
    rules: list[dict[str, Any]],
) -> PlannedQuery:
    """Check the model's plan and add the filters of the approved rules the question uses."""
    if not plan:
        raise QueryPlanError("Chưa lập được truy vấn cho câu hỏi.")
    dataset = next((item for item in catalog_datasets if item["id"] == plan.get("dataset_id")), None)
    if dataset is None:
        raise QueryPlanError("Dataset của truy vấn không có trong semantic layer.")
    columns = {column["name"]: column for column in dataset["columns"]}
    value_labels = _value_labels(dataset)
    metrics_by_id = {metric["metric_id"]: metric for metric in catalog_metrics if metric["dataset_id"] == dataset["id"]}
    metric_ids = dict.fromkeys(plan.get("metric_ids") or [])
    metrics = [metrics_by_id[metric_id] for metric_id in metric_ids if metric_id in metrics_by_id]
    if not metrics:
        raise QueryPlanError("Truy vấn chưa có metric đã duyệt nào của dataset này.")
    dimensions = []
    for name in dict.fromkeys(plan.get("dimensions") or []):
        column = columns.get(name)
        if column is None or not column.get("groupby"):
            raise QueryPlanError(f"Không nhóm được theo cột “{name}”.")
        temporal = bool(column.get("temporal"))
        dimension = {"name": name, "label": column.get("label") or name, "temporal": temporal}
        if name in value_labels:
            # A key is shown by its labels, so it is named like them: "Thành phố" rather than "Khóa thành phố".
            dimension["label"] = value_labels[name]["label"] or dimension["label"]
            dimension["value_labels"] = value_labels[name]["values"]
        dimensions.append(dimension)
    notes = []
    filters = []
    for rule in rules:
        if rule.get("dataset_id") != dataset["id"]:
            notes.append(f"Rule “{rule['name']}” thuộc dataset khác nên không áp dụng được vào truy vấn này.")
            continue
        if rule.get("filters") is None:
            raise QueryPlanError(f"Điều kiện của rule “{rule['name']}” chưa chuyển được thành bộ lọc.")
        filters += [_checked_filter(item, columns, "expert_rule", value_labels) for item in rule["filters"]]
    # An approved rule's thresholds come from the rule itself, never from the model's copy of them.
    for item in plan.get("filters") or []:
        source = item.get("source") or "question"
        if source != "expert_rule":
            filters.append(_checked_filter(item, columns, source, value_labels))
    if len(metrics) > MAX_METRICS or len(dimensions) > MAX_DIMENSIONS or len(filters) > MAX_FILTERS:
        raise QueryPlanError("Truy vấn quá rộng; hãy hỏi cụ thể hơn.")
    presentation = plan.get("presentation") if plan.get("presentation") in ("number", "table", "bar", "line") else None
    return PlannedQuery(
        dataset_id=dataset["id"],
        metrics=metrics,
        dimensions=dimensions,
        filters=filters,
        presentation=presentation or ("table" if dimensions else "number"),
        scope=str(plan.get("scope") or "").strip(),
        notes=notes,
    )


def _cell(value: Any, dimension: dict[str, Any]) -> Any:
    """Superset sends dates as HTTP dates and keys as keys; the answer and the chart want ISO dates and labels."""
    if "value_labels" in dimension:
        return dimension["value_labels"].get(_key(value), value)
    if dimension["temporal"] and isinstance(value, str):
        try:
            moment = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return value
        at_midnight = (moment.hour, moment.minute, moment.second) == (0, 0, 0)
        return moment.date().isoformat() if at_midnight else moment.isoformat()
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _number(value: Any) -> Any:
    if isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return value
        return int(number) if number.is_integer() else number
    return value


def combined_result(planned: PlannedQuery, answers: list[dict[str, Any]]) -> dict[str, Any]:
    """One table: a row per dimension value, a column per metric, as each metric query answered."""
    rows: dict[tuple, dict[str, Any]] = {}
    truncated = False
    for metric, answer in zip(planned.metrics, answers):
        truncated = truncated or bool(answer.get("truncated"))
        for raw in answer.get("rows", []):
            cells = {
                dimension["name"]: _cell(raw.get(dimension["name"]), dimension)
                for dimension in planned.dimensions
            }
            key = tuple(cells[dimension["name"]] for dimension in planned.dimensions)
            row = rows.setdefault(key, cells)
            row[metric["metric_name"]] = _number(raw.get(metric["metric_name"]))
    names = [dimension["name"] for dimension in planned.dimensions]
    # An aggregate over no rows comes back as one row of empty values; that is no data, not a value.
    metric_names = [metric["metric_name"] for metric in planned.metrics]
    found = [row for row in rows.values() if any(row.get(name) is not None for name in metric_names)]
    ordered = sorted(found, key=lambda row: tuple(str(row[name]) for name in names))
    return {
        "scope": planned.scope,
        "presentation": planned.presentation,
        "dimensions": [
            {key: value for key, value in dimension.items() if key != "value_labels"}
            for dimension in planned.dimensions
        ],
        "metrics": [
            {
                "name": metric["metric_name"], "label": metric["name"],
                "unit": metric.get("unit"), "format": metric.get("d3format"),
            }
            for metric in planned.metrics
        ],
        "filters": planned.filters,
        "rows": ordered,
        "row_count": len(ordered),
        "truncated": truncated,
        "notes": planned.notes,
        # What was asked of the Semantic Layer for each metric, and the SQL it ran when it shows it (to administrators).
        "queries": [
            {"metric": metric["name"], "dataset_id": planned.dataset_id, "metric_id": metric["metric_id"],
             "request": planned.request_body(), "sql": answer.get("sql")}
            for metric, answer in zip(planned.metrics, answers)
        ],
    }


def result_for_answer(result: dict[str, Any]) -> dict[str, Any]:
    """The result as the final answer reads it: the rows capped, the row count kept, the queries left to the page."""
    shown = result["rows"][:ROWS_FOR_ANSWER]
    answer = {key: value for key, value in result.items() if key != "queries"}
    return {**answer, "rows": shown, "rows_omitted": result["row_count"] - len(shown)}
