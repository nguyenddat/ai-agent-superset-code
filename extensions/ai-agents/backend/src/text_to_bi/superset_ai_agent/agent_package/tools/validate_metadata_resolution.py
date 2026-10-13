import json
import logging
from typing import Any

from langchain.tools import ToolRuntime, tool
from pydantic import BaseModel, ConfigDict

from ..context.contract import BIContract
from ..context.agent import MetadataResolutionContext
from ..context.dashboard import DatasetDTO, get_dashboard_datasets
from ..context.metadata_resolution import MetadataResolution
from .query_dataset import _resolve_relative_day
from ...core.superset_client import superset_client

logger = logging.getLogger(__name__)


def validate_metadata_resolution_contract(
    contract: BIContract,
    resolution: MetadataResolution,
    dataset: DatasetDTO,
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if resolution.status != "ready":
        if resolution.config or not resolution.message.strip():
            return [_issue("invalid_unsupported_result", "status", "Kết quả unsupported phải có config rỗng và giải thích giới hạn.")]
        return []
    if resolution.dataset_id != dataset.id:
        issues.append(_issue("dataset_mismatch", "dataset_id", "Cấu hình chart phải dùng đúng dataset trong BI Plan."))

    try:
        from superset.mcp_service.chart.chart_utils import _resolve_viz_type
        from superset.mcp_service.chart.schemas import parse_chart_config

        parsed = parse_chart_config(resolution.config)
        resolved_viz_type = _resolve_viz_type(parsed)
        if resolution.chart_type != getattr(parsed, "chart_type", None):
            issues.append(_issue("chart_type_mismatch", "chart_type", "chart_type không khớp cấu hình đã được Superset parse."))
        if resolution.viz_type != resolved_viz_type:
            issues.append(_issue("viz_type_mismatch", "viz_type", f"Superset ánh xạ cấu hình này thành '{resolved_viz_type}'."))
        planned_comparison = contract.chart_resolve.time_comparison
        configured_comparison = resolution.config.get("time_compare", [])
        expected_offsets = ["1 day ago"] if planned_comparison == "previous_day" else []
        if configured_comparison != expected_offsets:
            issues.append(_issue(
                "time_comparison_mismatch", "config.time_compare",
                "time_compare phải khớp yêu cầu so sánh khoảng thời gian trong BI Plan; so sánh hôm nay với hôm qua cần ['1 day ago'].",
            ))
        if planned_comparison and resolved_viz_type not in {
            "echarts_timeseries_line", "echarts_timeseries_bar", "echarts_area", "echarts_timeseries_scatter",
        }:
            issues.append(_issue(
                "time_comparison_unsupported", "viz_type",
                "Superset chỉ hỗ trợ time_compare trên biểu đồ chuỗi thời gian trong cấu hình này.",
            ))
        if contract.chart_resolve.viz_type and resolution.viz_type != contract.chart_resolve.viz_type:
            issues.append(_issue("plan_viz_type_mismatch", "viz_type", "Loại chart không khớp viz_type đã chốt trong BI Plan."))
        if contract.data_resolve.time_grain and not getattr(parsed, "time_grain", None):
            issues.append(_issue("time_grain_missing", "config.time_grain", "Schema chart đã chọn không nhận time_grain nhưng BI Plan yêu cầu mức thời gian cụ thể."))

        expected_time_range = _planned_time_range(contract, issues)
        if resolution.time_range != expected_time_range:
            issues.append(_issue(
                "time_range_mismatch", "time_range",
                f"Khoảng thời gian phải được đặt ở MetadataResolution.time_range={expected_time_range!r}, không đưa vào config.filters.",
            ))

        planned_filters = _planned_chart_filters(contract)
        configured_filters = _configured_filters(parsed)
        if planned_filters is None:
            issues.append(_issue("invalid_column_filter", "config.filters", "Column filter trong BI Plan có giá trị hoặc cấu trúc không hợp lệ."))
        elif planned_filters != configured_filters:
            issues.append(_issue("filter_mismatch", "config.filters", "Các filter trong chart config phải giữ đầy đủ operator và giá trị của BI Plan."))

        allowed_fields = _planned_fields(contract)
        configured_fields = _referenced_fields(resolution.config)
        for name in sorted(configured_fields - allowed_fields):
            issues.append(_issue("unknown_chart_field", "config", f"Trường '{name}' không có trong BI Plan."))
        planned_metrics = {metric.name: metric.aggregation.upper() if metric.aggregation else None for source in contract.data_resolve.sources for metric in source.metrics}
        configured_metrics = _configured_metrics(resolution.config)
        if configured_metrics != planned_metrics:
            issues.append(_issue("metric_mismatch", "config", "Metric và aggregation trong chart config phải khớp BI Plan."))

        x_ref = getattr(parsed, "x", None) or getattr(parsed, "dimension", None)
        if x_ref is not None:
            if contract.chart_resolve.x_axis and x_ref.name != contract.chart_resolve.x_axis:
                issues.append(_issue("x_axis_mismatch", "config", "Trường trục X không khớp x_axis đã chốt trong BI Plan."))
            if x_ref.aggregate or x_ref.saved_metric:
                issues.append(_issue("x_axis_role_mismatch", "config", "Trục X phải là dimension, không phải metric."))
        elif contract.chart_resolve.x_axis:
            chart_dimensions = getattr(parsed, "columns", None) or getattr(parsed, "rows", None) or []
            if not any(item.name == contract.chart_resolve.x_axis for item in chart_dimensions):
                issues.append(_issue("x_axis_mismatch", "config", "Cấu hình chưa dùng trường x_axis đã chốt trong BI Plan."))
        if set(contract.chart_resolve.y_axis) != set(configured_metrics):
            issues.append(_issue("y_axis_mismatch", "config", "Các metric trên Y axis phải khớp y_axis trong BI Plan."))
        if contract.chart_resolve.series:
            series_refs = [
                *(getattr(parsed, "group_by", None) or []),
                *(getattr(parsed, "group_by_secondary", None) or []),
            ]
            if not any(item.name == contract.chart_resolve.series for item in series_refs):
                issues.append(_issue("series_mismatch", "config", "Cấu hình chưa dùng trường series đã chốt trong BI Plan."))
    except Exception as exc:
        issues.append(_issue("invalid_superset_config", "config", f"Superset từ chối cấu hình: {exc}"))
    return issues


def _planned_fields(contract: BIContract) -> set[str]:
    source = contract.data_resolve.sources[0]
    return set(source.columns + source.group_by + [metric.name for metric in source.metrics] + [item.field for item in source.filters])


def _referenced_fields(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"name", "column"} and isinstance(item, str):
                found.add(item)
            else:
                found.update(_referenced_fields(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_referenced_fields(item))
    return found


def _configured_metrics(config: dict[str, Any]) -> dict[str, str | None]:
    metrics: dict[str, str | None] = {}
    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if isinstance(value.get("name"), str) and (value.get("aggregate") or value.get("saved_metric")):
                metrics[value["name"]] = value.get("aggregate")
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(config)
    return metrics


def _planned_chart_filters(contract: BIContract) -> set[tuple[str, str, str]] | None:
    result: set[tuple[str, str, str]] = set()
    for item in contract.data_resolve.sources[0].filters:
        if item.operator == "relative_time":
            continue
        if item.operator == "between":
            if not isinstance(item.value, list) or len(item.value) != 2:
                return None
            result.add((item.field, ">=", json.dumps(item.value[0], ensure_ascii=False)))
            result.add((item.field, "<=", json.dumps(item.value[1], ensure_ascii=False)))
            continue
        if item.operator in {"in", "not_in"} and not isinstance(item.value, list):
            return None
        if item.operator == "contains" and not isinstance(item.value, str):
            return None
        operator = {"=": "=", "in": "IN", "not_in": "NOT IN", "contains": "ILIKE"}.get(item.operator, item.operator)
        value = f"%{item.value}%" if item.operator == "contains" and isinstance(item.value, str) else item.value
        result.add((item.field, operator, json.dumps(value, ensure_ascii=False, sort_keys=True)))
    return result


def _planned_time_range(contract: BIContract, issues: list[dict[str, str]]) -> str | None:
    temporal_values: list[str] = []
    for source_index, source in enumerate(contract.data_resolve.sources):
        for filter_index, item in enumerate(source.filters):
            if item.operator != "relative_time":
                continue
            if not isinstance(item.value, str) or not item.value.strip():
                issues.append(_issue(
                    "invalid_time_range", f"data_resolve.sources[{source_index}].filters[{filter_index}].value",
                    "relative_time cần một giá trị khoảng thời gian dạng chuỗi.",
                ))
                continue
            temporal_values.append(item.value)

    distinct_values = set(temporal_values)
    if len(distinct_values) > 1:
        issues.append(_issue(
            "conflicting_time_ranges", "data_resolve.sources.filters",
            "BI Plan có nhiều relative_time khác nhau; cần một khoảng thời gian thống nhất.",
        ))
    filter_time_range = _resolve_relative_day(temporal_values[0]) if temporal_values else None
    planned_time_range = _resolve_relative_day(contract.data_resolve.time_range)
    if planned_time_range and filter_time_range and planned_time_range != filter_time_range:
        issues.append(_issue(
            "conflicting_time_ranges", "data_resolve.time_range",
            "data_resolve.time_range phải trùng với giá trị relative_time trong filter.",
        ))
    return planned_time_range or filter_time_range


def _configured_filters(config: Any) -> set[tuple[str, str, str]]:
    result: set[tuple[str, str, str]] = set()
    for item in getattr(config, "filters", None) or []:
        result.add((item.column, item.op, json.dumps(item.value, ensure_ascii=False, sort_keys=True)))
    return result


def _issue(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}

class ValidateMetadataResolutionInput(BaseModel):
    # ToolNode injects the hidden `runtime` parameter into the tool call before
    # LangChain validates it against this public argument schema. Ignore extra
    # keys here; ToolNode strips model-supplied runtime values and injects its
    # trusted ToolRuntime instance.
    model_config = ConfigDict(extra="ignore")

    resolution_json: str


@tool(args_schema=ValidateMetadataResolutionInput)
def validate_metadata_resolution(
    resolution_json: str, runtime: ToolRuntime[MetadataResolutionContext]
) -> dict[str, Any]:
    """Kiểm tra cấu hình chart theo các trường BI Plan trong runtime context và metadata được cấp quyền."""
    try:
        context = runtime.context or {}
        dashboard_id = context.get("dashboard_id")
        bi_plan = BIContract.model_validate({
            "user_intent": {"objective": context["user_intent_objective"]},
            "data_resolve": {
                "sources": context["data_sources"],
                "combination": context["combination"],
                "combination_key": context["combination_key"],
                "time_range": context["time_range"],
                "time_grain": context["time_grain"],
                "order_by": context["order_by"],
            },
            "chart_resolve": {
                "mode": "auto",
                "viz_type": None,
                "data_shape": context["data_shape"],
                "data_grain": context["data_grain"],
                "x_axis": context["x_axis"],
                "y_axis": context["y_axis"],
                "series": context["series"],
                "time_comparison": context.get("time_comparison"),
                "title": context["chart_title"],
            },
        })
        resolution = MetadataResolution.model_validate_json(resolution_json)
    except Exception as exc:
        logger.exception("MetadataResolution tool input parsing failed (dashboard_id=%s)", locals().get("dashboard_id"))
        path = "metadata_resolution_context" if "bi_plan" not in locals() else "resolution_json"
        return _tool_error("invalid_tool_input", path, exc)

    try:
        allowed_ids = set(context.get("allowed_dataset_ids", []))
        source_ids = [source.dataset_id for source in bi_plan.data_resolve.sources]
        if len(source_ids) != 1:
            return _tool_invalid([_issue("unsupported_sources", "data_resolve.sources", "Tool hiện chỉ xác thực cấu hình chart cho một dataset.")])
        dataset_id = source_ids[0]
        if dataset_id not in allowed_ids or resolution.dataset_id != dataset_id:
            return _tool_invalid([_issue("unauthorized_dataset", "dataset_id", "Dataset trong cấu hình phải thuộc dashboard được cấp quyền và khớp BI Plan.")])
        if dashboard_id is None:
            return _tool_invalid([_issue("missing_dashboard_context", "dashboard_id", "Runtime context không có dashboard_id để xác minh quyền dataset.")])

        datasets = get_dashboard_datasets(dashboard_id, superset_client)
        dataset = next((item for item in datasets if item.id == dataset_id and item.id in allowed_ids), None)
        if dataset is None:
            return _tool_invalid([_issue("missing_dataset", "dataset_id", "Dataset không tồn tại trong metadata dashboard được phép.")])

        errors = validate_metadata_resolution_contract(bi_plan, resolution, dataset)
        if errors:
            return _tool_invalid(errors)
        return {"valid": True, "errors": [], "message": "Cấu hình hợp lệ."}
    except Exception as exc:
        logger.exception("MetadataResolution validator tool failed (dashboard_id=%s)", dashboard_id)
        return _tool_error("validator_exception", "validate_metadata_resolution", exc)


def _tool_invalid(errors: list[dict[str, str]]) -> dict[str, Any]:
    logger.warning("MetadataResolution validator returned errors: %s", json.dumps(errors, ensure_ascii=False))
    return {"valid": False, "errors": errors, "message": "Hãy sửa cấu hình theo lỗi rồi gọi lại tool."}


def _tool_error(code: str, path: str, exc: Exception) -> dict[str, Any]:
    detail = f"{type(exc).__name__}: {exc}"
    return _tool_invalid([_issue(code, path, detail)])
