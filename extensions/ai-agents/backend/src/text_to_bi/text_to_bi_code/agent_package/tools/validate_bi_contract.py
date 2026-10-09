from typing import Any

from langchain.tools import ToolRuntime, tool
from pydantic import BaseModel, Field

from ...core.superset_client import superset_client
from ..context.dashboard import DatasetDTO, get_dashboard_datasets
from ..context.contract import BIContract


def _issue(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


class BIContractValidator:
    def validate(
        self, contract: BIContract, datasets: list[DatasetDTO],
        authorized_ids: set[int], capabilities: dict[str, Any] | None = None,
        verified_relationships: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, str]]:
        issues: list[dict[str, str]] = []
        by_id = {ds.id: ds for ds in datasets}
        resolve = contract.data_resolve
        sources = resolve.sources
        for i, source in enumerate(sources):
            path = f"data_resolve.sources[{i}]"
            if source.dataset_id not in authorized_ids:
                issues.append(_issue("unauthorized_dataset", path + ".dataset_id", f"Dataset {source.dataset_id} nằm ngoài dashboard được phép."))
                continue
            ds = by_id.get(source.dataset_id)
            if ds is None:
                issues.append(_issue("missing_dataset", path + ".dataset_id", f"Dataset {source.dataset_id} không có trong metadata dashboard."))
                continue
            columns = {c.column_name: c for c in ds.columns}
            metrics = {m.metric_name: m for m in ds.metrics}
            def valid_column(name: str, at: str) -> bool:
                col = columns.get(name)
                if col is None:
                    issues.append(_issue("missing_column", at, f"Không tìm thấy column_name chính xác '{name}' trong dataset {ds.id}."))
                    return False
                if col.is_sensitive is True or col.is_queryable is False:
                    issues.append(_issue("restricted_column", at, f"Cột '{name}' không được phép truy vấn."))
                    return False
                return True
            for j, name in enumerate(source.columns):
                valid_column(name, f"{path}.columns[{j}]")
            for j, name in enumerate(source.group_by):
                valid_column(name, f"{path}.group_by[{j}]")
            for j, metric in enumerate(source.metrics):
                at = f"{path}.metrics[{j}]"
                if metric.name in metrics:
                    if metric.aggregation is not None:
                        issues.append(_issue("saved_metric_aggregation", at + ".aggregation", "Metric lưu sẵn phải có aggregation=null."))
                elif metric.name in columns:
                    col = columns[metric.name]
                    if col.is_sensitive is True or col.is_queryable is False:
                        issues.append(_issue("restricted_column", at + ".name", f"Cột '{metric.name}' không được phép truy vấn."))
                    elif metric.aggregation is None:
                        issues.append(_issue("missing_aggregation", at + ".aggregation", "Cột được dùng làm metric cần aggregation."))
                    elif metric.aggregation in {"sum", "avg"} and not _is_numeric(col.type):
                        issues.append(_issue("invalid_aggregation", at + ".aggregation", f"{metric.aggregation} yêu cầu cột số; kiểu hiện tại là {col.type or 'không rõ'}."))
                else:
                    issues.append(_issue("missing_metric", at + ".name", f"'{metric.name}' không phải metric lưu sẵn hoặc column_name trong dataset {ds.id}."))
            for j, filt in enumerate(source.filters):
                at = f"{path}.filters[{j}]"
                valid_column(filt.field, at + ".field")
                if filt.operator == "between" and (not isinstance(filt.value, list) or len(filt.value) != 2):
                    issues.append(_issue("invalid_filter_value", at + ".value", "between yêu cầu đúng hai giá trị."))
            if (source.metrics or source.group_by) and source.columns:
                # `columns` means detail rows in the existing query tool; mixing raw rows
                # and aggregation has no unambiguous output grain.
                issues.append(_issue("mixed_grain", path, "Không trộn columns dạng chi tiết với metrics/group_by tổng hợp."))

        count = len(sources)
        if count == 1 and resolve.combination != "single":
            issues.append(_issue("combination_count", "data_resolve.combination", "Một nguồn dữ liệu phải dùng combination='single'."))
        if count > 1 and resolve.combination == "single":
            issues.append(_issue("combination_count", "data_resolve.combination", "Nhiều nguồn dữ liệu không thể dùng combination='single'."))
        if count == 0:
            issues.append(_issue("missing_source", "data_resolve.sources", "Cần ít nhất một nguồn dữ liệu."))
        if resolve.combination == "join":
            verified = verified_relationships or []
            if not any(r.get("verified") and set(r.get("dataset_ids", [])) == {s.dataset_id for s in sources} for r in verified):
                issues.append(_issue("unverified_join", "data_resolve.combination", "Không có metadata quan hệ đã xác minh cho JOIN; shared column name không đủ để chứng minh quan hệ."))
        if count > 1 and resolve.combination == "independent" and not resolve.combination_key:
            issues.append(_issue("missing_combination_key", "data_resolve.combination_key", "Independent nhiều nguồn cần chiều khóa chuẩn hóa; contract chưa mô tả quy tắc chuẩn hóa đầu ra."))

        chart = contract.chart_resolve
        if chart.mode != "auto":
            issues.append(_issue("chart_selection_delegated", "chart_resolve.mode", "BI Planner phải để mode='auto'; MetadataResolution phụ trách chọn hình thức biểu đồ."))
        if chart.viz_type is not None:
            issues.append(_issue("chart_selection_delegated", "chart_resolve.viz_type", "BI Planner không được chọn viz_type; hãy để null để MetadataResolution chọn từ Superset registry."))
        output_fields = _expected_fields(contract, by_id)
        for path, name in [("chart_resolve.x_axis", chart.x_axis), ("chart_resolve.series", chart.series), *((f"chart_resolve.y_axis[{i}]", n) for i, n in enumerate(chart.y_axis))]:
            if name is not None and name not in output_fields:
                issues.append(_issue("missing_output_field", path, f"'{name}' không có trong output dự kiến ({', '.join(sorted(output_fields)) or 'chưa xác định'})."))
        if chart.data_shape == "scalar" and (chart.x_axis or chart.series or chart.data_grain.casefold() not in {"một giá trị", "single value", "scalar"}):
            issues.append(_issue("inconsistent_shape", "chart_resolve.data_shape", "scalar phải biểu diễn một giá trị đơn, không có trục/series hoặc grain nhiều dòng."))
        if chart.data_shape == "raw" and any(s.metrics or s.group_by for s in sources):
            issues.append(_issue("inconsistent_shape", "chart_resolve.data_shape", "raw không nhất quán với kế hoạch có metric/group_by tổng hợp."))
        if chart.data_shape == "aggregated" and not any(s.metrics for s in sources):
            issues.append(_issue("inconsistent_shape", "chart_resolve.data_shape", "aggregated cần ít nhất một metric."))
        if resolve.time_grain and not any(s.group_by for s in sources):
            issues.append(_issue("inconsistent_time_grain", "data_resolve.time_grain", "time_grain yêu cầu nhóm kết quả theo chiều thời gian."))
        if chart.time_comparison == "previous_day":
            relative_ranges = [
                item.value
                for source in sources
                for item in source.filters
                if item.operator == "relative_time" and isinstance(item.value, str)
            ]
            if resolve.time_range != "today" or relative_ranges != ["today"]:
                issues.append(_issue(
                    "invalid_time_comparison_range", "chart_resolve.time_comparison",
                    "So sánh hôm nay với hôm qua cần time_range và relative_time đều là 'today'; Superset tự truy vấn ngày trước bằng time_compare.",
                ))
        return issues


class ValidateBIContractInput(BaseModel):
    contract: BIContract = Field(description="BIContract cần kiểm tra theo siêu dữ liệu dashboard hiện tại.")


@tool(args_schema=ValidateBIContractInput)
def validate_bi_contract(contract: BIContract, runtime: ToolRuntime) -> dict[str, Any]:
    """Kiểm tra BIContract theo siêu dữ liệu và quyền truy cập của dashboard hiện tại."""
    authorized_ids = set(runtime.context.get("allowed_dataset_ids", []))
    try:
        dashboard_datasets = get_dashboard_datasets(runtime.context["dashboard_id"], superset_client)
    except Exception as exc:
        return {"valid": False, "errors": [_issue("metadata_unavailable", "metadata", f"Không tải được siêu dữ liệu dashboard: {exc}")]}
    datasets = [dataset for dataset in dashboard_datasets if dataset.id in authorized_ids]
    errors = BIContractValidator().validate(
        contract,
        datasets,
        authorized_ids,
    )
    return {"valid": not errors, "errors": errors, "message": "Contract hợp lệ." if not errors else "Hãy sửa contract theo lỗi rồi gọi lại công cụ xác thực."}


def _is_numeric(type_name: str | None) -> bool:
    value = (type_name or "").casefold()
    return any(token in value for token in ("int", "numeric", "decimal", "float", "double", "real", "number"))


def _expected_fields(contract: BIContract, datasets: dict[int, DatasetDTO]) -> set[str]:
    result: set[str] = set()
    for source in contract.data_resolve.sources:
        ds = datasets.get(source.dataset_id)
        if not ds:
            continue
        if source.metrics or source.group_by:
            result.update(source.group_by)
            result.update(metric.name for metric in source.metrics)
        else:
            result.update(source.columns)
    return result
