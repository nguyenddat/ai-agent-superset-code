import json
import re
import threading
import unicodedata
from datetime import datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from langchain.tools import ToolRuntime, tool
from pydantic import BaseModel, Field

from ...core.superset_client import superset_client
from ...core.settings import config
from ..context.dashboard import DatasetDTO, get_dashboard_datasets

_chart_query_lock = threading.RLock()


def _resolve_relative_day(time_range: str | None) -> str | None:
    """Resolve day-relative filters in the configured user timezone, not UTC."""
    if not time_range:
        return time_range
    normalized = time_range.strip().casefold()
    has_today = normalized in {"today", "hôm nay"} or bool(re.search(r"\btoday\b", normalized)) or "hôm nay" in normalized
    has_yesterday = normalized in {"yesterday", "hôm qua"} or bool(re.search(r"\byesterday\b", normalized)) or "hôm qua" in normalized
    if not has_today and not has_yesterday:
        return time_range

    local_today = datetime.now(ZoneInfo(config.query_timezone)).date()
    first_day = local_today - timedelta(days=1 if has_yesterday else 0)
    day_after_last = local_today + timedelta(days=1) if has_today else local_today
    zone = ZoneInfo(config.query_timezone)
    start = datetime.combine(first_day, datetime.min.time(), zone)
    end = datetime.combine(day_after_last, datetime.min.time(), zone)
    return f"{start.isoformat()} : {end.isoformat()}"


class MetricRequest(BaseModel):
    name: str = Field(description="Metric hoặc cột số đã có trong catalog của dataset.")
    aggregation: Literal["sum", "avg", "count", "min", "max"] | None = Field(
        default=None,
        description="Phép tổng hợp cho cột; để trống nếu dùng metric đã định nghĩa sẵn.",
    )


class FilterRequest(BaseModel):
    field: str = Field(description="Cột trong catalog dùng làm điều kiện lọc.")
    operator: Literal[
        "=", "!=", ">", ">=", "<", "<=", "in", "not_in", "contains", "between", "relative_time"
    ]
    value: str | list[str] = Field(description="Giá trị lọc; between nhận đúng hai giá trị.")


class QueryDatasetInput(BaseModel):
    dataset_id: int = Field(description="ID dataset trong catalog của dashboard hiện tại.")
    columns: list[str] = Field(
        default_factory=list,
        description=(
            "Các cột catalog cần lấy ở dạng bản ghi. Dùng ['*'] để lấy tất cả "
            "cột được phép truy vấn; không dùng '*' trong group_by, filters hoặc order_by."
        ),
    )
    metrics: list[MetricRequest] = Field(default_factory=list, description="Các metric cần tính.")
    filters: list[FilterRequest] = Field(default_factory=list, description="Điều kiện lọc.")
    group_by: list[str] = Field(default_factory=list, description="Các cột dùng để nhóm kết quả.")
    time_range: str | None = Field(
        default=None,
        description=(
            "Khoảng thời gian theo cú pháp Superset, ví dụ 'Today', 'Yesterday', "
            "'Last week' hoặc '2026-10-04 : 2026-10-05'. Bắt buộc đặt khi câu hỏi "
            "hoặc analysis context có giới hạn thời gian."
        ),
    )
    order_by: list[str] = Field(default_factory=list, description="Cột sắp xếp; thêm dấu '-' ở đầu để sắp xếp giảm dần.")
    limit: int = Field(default=100, ge=1, le=100, description="Số dòng tối đa, từ 1 đến 100.")


def _find_column(dataset: DatasetDTO, requested_name: str):
    requested = requested_name.strip().casefold()
    exact = [
        column for column in dataset.columns
        if requested in {column.column_name.casefold(), (column.verbose_name or "").casefold()}
    ]
    if exact:
        return exact[0]

    def tokens(value: str) -> set[str]:
        normalized = unicodedata.normalize("NFKD", value.casefold())
        normalized = "".join(char for char in normalized if not unicodedata.combining(char))
        return set(re.findall(r"[a-z0-9]+", normalized))

    requested_tokens = tokens(requested_name)
    if not requested_tokens:
        return None
    candidates = [
        column for column in dataset.columns
        if requested_tokens.issubset(tokens(column.column_name) | tokens(column.verbose_name or ""))
    ]
    return candidates[0] if len(candidates) == 1 else None


def _invalid_field(dataset: DatasetDTO, field: str, kind: str = "cột") -> dict[str, Any]:
    available = [
        {"column_name": column.column_name, "verbose_name": column.verbose_name}
        for column in dataset.columns
        if column.is_queryable is not False and column.is_sensitive is not True
    ]
    return {
        "error": f"Không tìm thấy {kind} '{field}' trong catalog dataset.",
        "available_columns": available,
        "next_step": "Dùng đúng column_name trong danh sách; nếu cần, gọi get_column_catalog rồi thử lại.",
    }


def _filter_value(value: str | list[str], operator: str) -> Any:
    if operator in {"in", "not_in"}:
        return value if isinstance(value, list) else [part.strip() for part in value.split(",")]
    return value


@tool(args_schema=QueryDatasetInput)
def query_dataset(
    dataset_id: int,
    columns: list[str],
    metrics: list[MetricRequest],
    filters: list[FilterRequest],
    group_by: list[str],
    time_range: str | None,
    order_by: list[str],
    limit: int,
    runtime: ToolRuntime,
) -> dict[str, Any]:
    """Thực thi một truy vấn dữ liệu có cấu trúc trên dataset thuộc dashboard hiện tại.

    Dùng tool này cho câu hỏi cần giá trị hàng dữ liệu hoặc kết quả retrieve/filter/
    aggregate/compare. Trước khi gọi, phải xác định dataset_id và tên field từ catalog;
    chỉ gửi cột, metric, filter và group_by có trong catalog. Tool thực thi truy vấn,
    khác với các tool catalog chỉ đọc metadata. Không truyền SQL.

    columns lấy dữ liệu chi tiết; metrics tính metric đã lưu hoặc phép tổng hợp trên cột;
    filters giới hạn bản ghi; group_by chia kết quả theo dimension; time_range giới hạn
    theo thời gian. Kết quả tối đa 100 dòng.
    """
    allowed_ids = runtime.context["allowed_dataset_ids"]
    if dataset_id not in allowed_ids:
        return {
            "error": f"Dataset ID {dataset_id} không thuộc dashboard hiện tại.",
            "allowed_dataset_ids": allowed_ids,
            "next_step": "Gọi get_dataset_catalog và thử lại bằng đúng ID trong kết quả.",
        }

    analysis_time_expression = runtime.context.get("analysis_time_expression")
    if analysis_time_expression and not time_range:
        return {"error": f"Cần đặt time_range='{analysis_time_expression}' theo phạm vi thời gian trong câu hỏi."}

    resolved_time_range = _resolve_relative_day(time_range)

    datasets = get_dashboard_datasets(runtime.context["dashboard_id"], superset_client)
    dataset = next((item for item in datasets if item.id == dataset_id), None)
    if dataset is None:
        return {
            "error": f"Dataset ID {dataset_id} hiện không có trong catalog dashboard.",
            "allowed_dataset_ids": allowed_ids,
            "next_step": "Gọi get_dataset_catalog để làm mới danh sách và thử lại.",
        }

    selected_columns = []
    requested_columns = [name.strip() for name in columns]
    if any(name == "*" for name in requested_columns):
        # A wildcard means all fields that this tool is allowed to expose. Keep
        # the normal queryability and sensitivity checks applied to explicit fields.
        requested_columns = [
            column.column_name
            for column in dataset.columns
            if column.is_queryable is not False and column.is_sensitive is not True
        ]
    for name in [*requested_columns, *group_by]:
        column = _find_column(dataset, name)
        if column is None:
            return _invalid_field(dataset, name)
        if column.is_queryable is False or column.is_sensitive is True:
            return {"error": f"Cột '{name}' không được phép truy vấn."}
        if column.column_name not in selected_columns:
            selected_columns.append(column.column_name)

    query_metrics: list[Any] = []
    metric_order_names: dict[str, str] = {}
    for requested_metric in metrics:
        column = _find_column(dataset, requested_metric.name)
        saved_metric = next(
            (
                item
                for item in dataset.metrics
                if requested_metric.name in {item.metric_name, item.verbose_name}
            ),
            None,
        )
        if column is not None:
            if column.is_queryable is False or column.is_sensitive is True:
                return {"error": f"Metric '{requested_metric.name}' không được phép truy vấn."}
            if requested_metric.aggregation is None:
                return {"error": f"Cần chỉ rõ phép tổng hợp cho cột '{requested_metric.name}'."}
            query_metrics.append({
                "expressionType": "SIMPLE",
                "column": {"column_name": column.column_name, "type": column.type or ""},
                "aggregate": requested_metric.aggregation.upper(),
                "label": f"{requested_metric.aggregation.upper()}({column.verbose_name or column.column_name})",
                "hasCustomLabel": True,
            })
            # Superset orders aggregate queries by the metric label/expression,
            # not by the underlying source column (which is not grouped).
            metric_order_names[column.column_name.casefold()] = f"{requested_metric.aggregation.upper()}({column.verbose_name or column.column_name})"
            metric_order_names[requested_metric.name.casefold()] = f"{requested_metric.aggregation.upper()}({column.verbose_name or column.column_name})"
        elif saved_metric is not None and requested_metric.aggregation is None:
            query_metrics.append(saved_metric.metric_name)
            metric_order_names[saved_metric.metric_name.casefold()] = saved_metric.metric_name
            if saved_metric.verbose_name:
                metric_order_names[saved_metric.verbose_name.casefold()] = saved_metric.metric_name
        elif saved_metric is not None:
            return {"error": "Không áp dụng phép tổng hợp khác lên metric đã định nghĩa sẵn."}
        else:
            return _invalid_field(dataset, requested_metric.name, "metric hoặc cột")

    query_filters = []
    for requested_filter in filters:
        column = _find_column(dataset, requested_filter.field)
        if column is None:
            return _invalid_field(dataset, requested_filter.field, "cột lọc")
        if column.is_queryable is False or column.is_sensitive is True:
            return {"error": f"Cột lọc '{requested_filter.field}' không được phép truy vấn."}
        if requested_filter.operator == "between":
            if not isinstance(requested_filter.value, list) or len(requested_filter.value) != 2:
                return {"error": "Bộ lọc between cần đúng hai giá trị."}
            query_filters.extend([
                {"col": column.column_name, "op": ">=", "val": requested_filter.value[0]},
                {"col": column.column_name, "op": "<=", "val": requested_filter.value[1]},
            ])
            continue
        operator = {
            "=": "==", "in": "IN", "not_in": "NOT IN",
            "contains": "ILIKE", "relative_time": "TEMPORAL_RANGE",
        }.get(requested_filter.operator, requested_filter.operator)
        value = _filter_value(requested_filter.value, requested_filter.operator)
        if requested_filter.operator == "contains":
            value = f"%{value}%"
        query_filters.append({"col": column.column_name, "op": operator, "val": value})

    if not selected_columns and not query_metrics:
        return {"error": "Cần chỉ định ít nhất một cột hoặc metric cần truy vấn."}

    query_orderby = []
    grouped_column_names = {
        column.column_name.casefold()
        for name in group_by
        if (column := _find_column(dataset, name)) is not None
    }
    for name in order_by:
        descending = name.startswith("-")
        field_name = name[1:] if descending else name
        metric_name = metric_order_names.get(field_name.casefold())
        if metric_name:
            query_orderby.append([metric_name, descending])
            continue
        column = _find_column(dataset, field_name)
        resolved_name = column.column_name if column else field_name
        if column is None and field_name not in {metric.get("label") for metric in query_metrics}:
            return _invalid_field(dataset, field_name, "trường sắp xếp")
        if query_metrics and column and column.column_name.casefold() not in grouped_column_names:
            return {
                "error": f"Không thể sắp xếp theo cột '{field_name}' trong truy vấn tổng hợp vì cột này không nằm trong group_by.",
                "next_step": "Đưa cột vào group_by nếu đó là chiều phân nhóm, hoặc sắp xếp theo metric đã yêu cầu.",
            }
        query_orderby.append([resolved_name, descending])

    query_payload = {
        "datasource": {"id": dataset_id, "type": "table"},
        "queries": [{
            "columns": selected_columns,
            "metrics": query_metrics,
            "filters": query_filters,
            "granularity": dataset.main_dttm_col if time_range else None,
            "time_range": resolved_time_range,
            "orderby": query_orderby,
            "row_limit": limit + 1,
        }],
        "result_type": "full",
        "result_format": "json",
    }
    from superset.charts.schemas import ChartDataQueryContextSchema
    from superset.commands.chart.data.get_data_command import ChartDataCommand
    from superset.extensions import db

    # LangGraph executes tools in worker threads while this SSE request keeps its
    # Flask app context open. Release the scoped SQLAlchemy session explicitly so
    # each chart query returns its metadata DB connection to the pool.
    with _chart_query_lock:
        try:
            query_context = ChartDataQueryContextSchema().load(query_payload)
            command = ChartDataCommand(query_context)
            command.validate()
            result = command.run()["queries"][0]
        finally:
            db.session.remove()
    if result.get("error"):
        return {"error": "Superset không thể thực hiện truy vấn dữ liệu này.", "details": str(result["error"])[:500]}
    rows = result.get("data", [])
    output = {
        "columns": result.get("colnames", []),
        "rows": rows[:limit],
        "row_count": min(len(rows), limit),
        "truncated": len(rows) > limit,
        "time_range": resolved_time_range,
        "time_zone": config.query_timezone,
        "superset_form_data": {
            "datasource": f"{dataset_id}__table",
            "viz_type": "echarts_bar",
            "x_axis": next(
                (
                    column.column_name
                    for name in (group_by or requested_columns)
                    if (column := _find_column(dataset, name)) is not None
                ),
                None,
            ),
            "groupby": [
                column.column_name
                for name in (group_by or requested_columns)
                if (column := _find_column(dataset, name)) is not None
            ],
            "metrics": query_metrics,
            "adhoc_filters": [
                {
                    "clause": "WHERE",
                    "expressionType": "SIMPLE",
                    "subject": item["col"],
                    "operator": item["op"],
                    "comparator": item["val"],
                }
                for item in query_filters
            ],
            "time_range": resolved_time_range or "No filter",
            "row_limit": limit,
            "orderby": query_orderby,
        },
    }
    return json.dumps(output, ensure_ascii=False, default=str)
