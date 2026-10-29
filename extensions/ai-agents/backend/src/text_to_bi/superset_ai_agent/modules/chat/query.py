from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from email.utils import parsedate_to_datetime
from typing import Any

OPERATORS = ("==", "!=", "<", "<=", ">", ">=", "IN", "NOT IN")
MAX_METRICS = 3
MAX_DIMENSIONS = 2
MAX_FILTERS = 12
MAX_LIMIT = 100
# Rows the final answer reads; the browser receives every row the Semantic Layer returned.
ROWS_FOR_ANSWER = 60
NUMERIC_TYPES = ("INT", "NUMERIC", "DECIMAL", "FLOAT", "DOUBLE", "REAL", "BIGINT", "SMALLINT")
TIMESTAMP_TYPES = ("TIMESTAMP", "DATETIME")
COMPARED_SUFFIX = "__compare"
# Decimal places the answer quotes; the page's result card shows numbers the same way (`maximumFractionDigits: 2`).
ANSWER_DECIMALS = Decimal("0.01")


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
    # {metric_name, label, direction}: rows sorted by a metric, then cut to `limit`.
    order: dict[str, Any] | None = None
    limit: int | None = None
    # {label, start, end, filters}: the same query over another period, its time filters replaced.
    comparison: dict[str, Any] | None = None
    # {column, min, max, start, end, status}: which part of the asked period the data covers.
    coverage: dict[str, Any] | None = None
    # Columns holding a time of day, where a filter by date has to cover the whole day.
    timestamp_columns: set[str] = field(default_factory=set)

    def request_body(self, compared: bool = False) -> dict[str, Any]:
        """What the Semantic Layer's execution endpoint accepts: column names and filters, nothing else."""
        filters = self.comparison["filters"] if compared and self.comparison else self.filters
        return {
            "dimensions": [dimension["name"] for dimension in self.dimensions],
            "filters": [
                sent
                for item in filters
                for sent in whole_day_filters(item, item["column"] in self.timestamp_columns)
            ],
        }


def whole_day_filters(item: dict[str, Any], timestamp: bool) -> list[dict[str, Any]]:
    """A filter as sent; on a timestamp column a date means the whole day, so "<= 25/10" keeps 25/10 23:00."""
    sent = {"column": item["column"], "operator": item["operator"], "value": item["value"]}
    day = _date_only(item["value"]) if timestamp else None
    if day is None:
        return [sent]
    next_day = (day + timedelta(days=1)).isoformat()
    if item["operator"] == "==":
        return [{**sent, "operator": ">="}, {**sent, "operator": "<", "value": next_day}]
    if item["operator"] == "<=":
        return [{**sent, "operator": "<", "value": next_day}]
    if item["operator"] == ">":
        return [{**sent, "operator": ">=", "value": next_day}]
    return [sent]


def _date_only(value: Any) -> date | None:
    """The date a value names when it is a bare date such as "2026-10-25", not a moment of a day."""
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _is_timestamp(column: dict[str, Any]) -> bool:
    return any(name in str(column.get("type") or "").upper() for name in TIMESTAMP_TYPES)


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


def _key(value: Any) -> str:
    """A key as text, so 1, 1.0 and "1" find the same label."""
    return str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)


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


def _shown_value(value: Any, labels: dict[str, str]) -> Any:
    if isinstance(value, list):
        return [labels.get(_key(item), item) for item in value]
    return labels.get(_key(value), value)


def _checked_filter(
    item: dict[str, Any], columns: dict[str, dict[str, Any]], source: str, value_labels: dict[str, dict[str, Any]],
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


def checked_conditions(dataset: dict[str, Any], filters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A definition's conditions checked against its dataset, kept as `{column, label, operator, value}`."""
    columns = {column["name"]: column for column in dataset["columns"]}
    value_labels = _value_labels(dataset)
    checked = [_checked_filter(item, columns, "user_definition", value_labels) for item in filters]
    return [{key: item[key] for key in ("column", "label", "operator", "value")} for item in checked]


def _iso_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _shown_date(value: date | str) -> str:
    moment = value if isinstance(value, date) else date.fromisoformat(value)
    return moment.strftime("%d/%m/%Y")


def _period(filters: list[dict[str, Any]], column: str) -> tuple[date | None, date | None]:
    """The first and last day the time filters on `column` allow."""
    start = end = None
    for item in filters:
        if item["column"] != column or item["operator"] not in ("==", ">=", ">", "<=", "<"):
            continue
        moment = _iso_date(item["value"])
        if moment is None:
            continue
        if item["operator"] in ("==", ">=", ">"):
            start = moment if start is None else max(start, moment)
        if item["operator"] in ("==", "<=", "<"):
            end = moment if end is None else min(end, moment)
    return start, end


def _coverage(dataset: dict[str, Any], column: str, start: date | None, end: date | None) -> dict[str, Any] | None:
    """How much of the asked period the data covers: all of it, part of it, or none of it."""
    known = next((item for item in dataset.get("time_ranges", []) if item["column"] == column), None)
    first, last = (_iso_date(known["min"]), _iso_date(known["max"])) if known else (None, None)
    if first is None or last is None:
        return None
    asked_start, asked_end = start or first, end or last
    if asked_end < first or asked_start > last:
        status = "none"
    elif asked_start < first or asked_end > last:
        status = "partial"
    else:
        status = "full"
    return {
        "column": column, "min": first.isoformat(), "max": last.isoformat(),
        "start": asked_start.isoformat(), "end": asked_end.isoformat(), "status": status,
    }


def _coverage_note(coverage: dict[str, Any] | None, label: str = "") -> str | None:
    if coverage is None or coverage["status"] == "full":
        return None
    span = f"từ {_shown_date(coverage['min'])} đến {_shown_date(coverage['max'])}"
    period = f"{label} " if label else ""
    if coverage["status"] == "none":
        return f"Khoảng thời gian {period}nằm ngoài dữ liệu hiện có ({span})."
    return f"Dữ liệu chỉ có {span}, nên khoảng thời gian {period}chỉ được tính phần nằm trong đó."


def _comparison(
    plan: dict[str, Any], filters: list[dict[str, Any]], dimensions: list[dict[str, Any]],
    columns: dict[str, dict[str, Any]], value_labels: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """The same filters with the asked period swapped for the compared one."""
    asked = plan.get("comparison")
    if not asked:
        return None
    start, end = _iso_date(asked.get("start")), _iso_date(asked.get("end"))
    if start is None or end is None or start > end:
        raise QueryPlanError("Kỳ so sánh cần ngày bắt đầu và ngày kết thúc hợp lệ.")
    time_filters = [item for item in filters if item["source"] == "time"]
    if not time_filters:
        raise QueryPlanError("Muốn so sánh hai kỳ thì câu hỏi cần có khoảng thời gian của kỳ hiện tại.")
    column = time_filters[0]["column"]
    if any(dimension["name"] == column for dimension in dimensions):
        raise QueryPlanError("Không so sánh hai kỳ khi kết quả đã chia theo từng ngày; hãy hỏi tổng của mỗi kỳ.")
    kept = [item for item in filters if not (item["source"] == "time" and item["column"] == column)]
    bounds = [
        _checked_filter({"column": column, "operator": operator, "value": moment.isoformat()}, columns, "time", {})
        for operator, moment in ((">=", start), ("<=", end))
    ]
    label = str(asked.get("label") or "").strip() or f"{_shown_date(start)}–{_shown_date(end)}"
    return {
        "label": label, "start": start.isoformat(), "end": end.isoformat(), "column": column, "filters": kept + bounds,
    }


def plan_query(
    plan: dict[str, Any] | None,
    catalog_datasets: list[dict[str, Any]],
    catalog_metrics: list[dict[str, Any]],
    rules: list[dict[str, Any]],
) -> PlannedQuery:
    """Check the model's plan and add the stored conditions of the rules and user definitions the question uses.

    Each of `rules` is `{name, dataset_id, filters, source}`, with source `expert_rule` (the default) or
    `user_definition`.
    """
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
        dimension = {"name": name, "label": column.get("label") or name, "temporal": bool(column.get("temporal"))}
        if name in value_labels:
            # A key is shown by its labels, so it is named like them: "Thành phố" rather than "Khóa thành phố".
            dimension["label"] = value_labels[name]["label"] or dimension["label"]
            dimension["value_labels"] = value_labels[name]["values"]
        dimensions.append(dimension)
    notes = []
    filters = []
    stored_columns = set()
    for rule in rules:
        source = rule.get("source") or "expert_rule"
        if rule.get("dataset_id") != dataset["id"]:
            notes.append(f"Điều kiện “{rule['name']}” thuộc dataset khác nên không áp dụng được vào truy vấn này.")
            continue
        if rule.get("filters") is None:
            raise QueryPlanError(f"Điều kiện của “{rule['name']}” chưa chuyển được thành bộ lọc.")
        filters += [_checked_filter(item, columns, source, value_labels) for item in rule["filters"]]
        if source == "user_definition":
            stored_columns.update(item["column"] for item in rule["filters"])
    # A stored threshold comes from where it was stored, never from the model's copy of it.
    for item in plan.get("filters") or []:
        source = item.get("source") or "question"
        retyped = source == "expert_rule" or (source == "user_definition" and item.get("column") in stored_columns)
        if not retyped:
            filters.append(_checked_filter(item, columns, source, value_labels))
    if len(metrics) > MAX_METRICS or len(dimensions) > MAX_DIMENSIONS or len(filters) > MAX_FILTERS:
        raise QueryPlanError("Truy vấn quá rộng; hãy hỏi cụ thể hơn.")

    order = None
    asked_order = plan.get("order_by") or {}
    if asked_order.get("metric_id") is not None:
        ordered_metric = next((metric for metric in metrics if metric["metric_id"] == asked_order["metric_id"]), None)
        if ordered_metric is None:
            raise QueryPlanError("Chỉ sắp xếp được theo một metric có trong truy vấn.")
        direction = "asc" if asked_order.get("direction") == "asc" else "desc"
        order = {"metric_name": ordered_metric["metric_name"], "label": ordered_metric["name"], "direction": direction}
    limit = plan.get("limit")
    if limit is not None:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_LIMIT:
            raise QueryPlanError(f"Số dòng giới hạn phải từ 1 đến {MAX_LIMIT}.")
        if not dimensions:
            limit = None

    comparison = _comparison(plan, filters, dimensions, columns, value_labels)
    time_column = next((item["column"] for item in filters if item["source"] == "time"), None)
    time_column = time_column or next((dimension["name"] for dimension in dimensions if dimension["temporal"]), None)
    coverage = _coverage(dataset, time_column, *_period(filters, time_column)) if time_column else None
    notes += [note for note in (_coverage_note(coverage),) if note]
    if comparison:
        compared_period = (_iso_date(comparison["start"]), _iso_date(comparison["end"]))
        compared_coverage = _coverage(dataset, comparison["column"], *compared_period)
        notes += [note for note in (_coverage_note(compared_coverage, comparison["label"]),) if note]
        comparison["coverage"] = compared_coverage

    presentation = plan.get("presentation") if plan.get("presentation") in ("number", "table", "bar", "line") else None
    return PlannedQuery(
        dataset_id=dataset["id"],
        metrics=metrics,
        dimensions=dimensions,
        filters=filters,
        presentation=presentation or ("table" if dimensions else "number"),
        scope=str(plan.get("scope") or "").strip(),
        notes=notes,
        order=order,
        limit=limit,
        comparison=comparison,
        coverage=coverage,
        timestamp_columns={name for name, column in columns.items() if _is_timestamp(column)},
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
        return moment.isoformat()
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


def _merge(
    rows: dict[tuple, dict[str, Any]], planned: PlannedQuery, answers: list[dict[str, Any]], suffix: str = "",
) -> bool:
    """Fold each metric's rows into one row per dimension value; True when the Semantic Layer cut any of them."""
    truncated = False
    for metric, answer in zip(planned.metrics, answers):
        truncated = truncated or bool(answer.get("truncated"))
        for raw in answer.get("rows", []):
            cells = {
                dimension["name"]: _cell(raw.get(dimension["name"]), dimension) for dimension in planned.dimensions
            }
            key = tuple(cells[dimension["name"]] for dimension in planned.dimensions)
            row = rows.setdefault(key, cells)
            row[metric["metric_name"] + suffix] = _number(raw.get(metric["metric_name"]))
    return truncated


def _days_when_daily(rows: list[dict[str, Any]], planned: PlannedQuery) -> None:
    """A time column whose every value falls at midnight holds days, shown as dates; an hourly one keeps its times."""
    for dimension in planned.dimensions:
        if not dimension["temporal"]:
            continue
        moments = []
        for row in rows:
            try:
                moments.append(datetime.fromisoformat(row[dimension["name"]]))
            except (TypeError, ValueError):
                moments.append(None)
        if all(moment is not None and moment.time() == datetime.min.time() for moment in moments):
            for row, moment in zip(rows, moments):
                row[dimension["name"]] = moment.date().isoformat()


def _ordered(rows: list[dict[str, Any]], planned: PlannedQuery) -> list[dict[str, Any]]:
    names = [dimension["name"] for dimension in planned.dimensions]
    ordered = sorted(rows, key=lambda row: tuple(str(row[name]) for name in names))
    if planned.order:
        metric_name, descending = planned.order["metric_name"], planned.order["direction"] == "desc"
        valued = [row for row in ordered if isinstance(row.get(metric_name), (int, float))]
        empty = [row for row in ordered if not isinstance(row.get(metric_name), (int, float))]
        ordered = sorted(valued, key=lambda row: row[metric_name], reverse=descending) + empty
    return ordered[:planned.limit] if planned.limit else ordered


def combined_result(
    planned: PlannedQuery, answers: list[dict[str, Any]], compared_answers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """One table: a row per dimension value, a column per metric, and per metric its value in the compared period."""
    rows: dict[tuple, dict[str, Any]] = {}
    truncated = _merge(rows, planned, answers)
    if planned.comparison and compared_answers is not None:
        truncated = _merge(rows, planned, compared_answers, COMPARED_SUFFIX) or truncated
    # An aggregate over no rows comes back as one row of empty values; that is no data, not a value.
    value_names = [metric["metric_name"] + suffix for metric in planned.metrics for suffix in ("", COMPARED_SUFFIX)]
    found = [row for row in rows.values() if any(row.get(name) is not None for name in value_names)]
    _days_when_daily(found, planned)
    shown = _ordered(found, planned)
    notes = list(planned.notes)
    if truncated and planned.order:
        notes.append("Semantic Layer đã giới hạn số dòng trả về, nên thứ hạng chỉ tính trên phần dữ liệu đã nhận.")
    compared = planned.comparison is not None and compared_answers is not None
    queries = [
        {
            "metric": metric["name"], "dataset_id": planned.dataset_id, "metric_id": metric["metric_id"],
            "period": period, "request": planned.request_body(compared=period is not None), "sql": answer.get("sql"),
        }
        for period, period_answers in ((None, answers), ((planned.comparison or {}).get("label"), compared_answers))
        if period_answers is not None and (period is None or compared)
        for metric, answer in zip(planned.metrics, period_answers)
    ]
    return {
        "scope": planned.scope,
        "presentation": planned.presentation,
        "dimensions": [
            {key: value for key, value in dimension.items() if key != "value_labels"}
            for dimension in planned.dimensions
        ],
        "metrics": [
            {
                "name": metric["metric_name"], "label": metric["name"], "unit": metric.get("unit"),
                "format": metric.get("d3format"),
                "compared_name": metric["metric_name"] + COMPARED_SUFFIX if compared else None,
            }
            for metric in planned.metrics
        ],
        "filters": planned.filters,
        "order": planned.order,
        "limit": planned.limit,
        "comparison": (
            {key: planned.comparison[key] for key in ("label", "start", "end", "coverage")} if compared else None
        ),
        "coverage": planned.coverage,
        "rows": shown,
        "row_count": len(shown),
        "total_rows": len(found),
        "truncated": truncated,
        "notes": notes,
        # What was asked of the Semantic Layer for each metric, and the SQL it ran when it shows it (to administrators).
        "queries": queries,
    }


def shown_number(value: Any) -> Any:
    """A float rounded as the result card shows it, half away from zero, so the answer quotes the same figure."""
    if isinstance(value, float):
        return float(Decimal(value).quantize(ANSWER_DECIMALS, rounding=ROUND_HALF_UP))
    return value


def result_for_answer(result: dict[str, Any]) -> dict[str, Any]:
    """The result as the final answer reads it: the rows capped and rounded, the row count kept, the queries left out."""
    shown = [{key: shown_number(value) for key, value in row.items()} for row in result["rows"][:ROWS_FOR_ANSWER]]
    answer = {key: value for key, value in result.items() if key != "queries"}
    return {**answer, "rows": shown, "rows_omitted": result["row_count"] - len(shown)}
