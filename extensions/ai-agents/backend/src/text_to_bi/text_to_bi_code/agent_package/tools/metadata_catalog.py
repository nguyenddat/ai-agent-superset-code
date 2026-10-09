import json
import sys
from importlib.resources import files

from langchain.tools import ToolRuntime, tool
from pydantic import BaseModel, ConfigDict, Field

from ...core.superset_client import superset_client
from ..context.dashboard import get_dashboard_charts, get_dashboard_datasets


# ============================================================
# DTO
# ============================================================

class DatasetCatalogDTO(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: int = Field(description="ID dataset trong Superset.")
    name: str | None = Field(default=None, description="Tên dataset.")
    schema_: str | None = Field(default=None, alias="schema", description="Schema chứa dataset.")
    description: str | None = Field(default=None, description="Mô tả dataset.")


class ColumnCatalogDTO(BaseModel):
    dataset_id: int = Field(description="ID dataset chứa cột.")
    name: str = Field(description="Tên vật lý chính xác của cột; dùng tên này khi gọi query_dataset.")
    verbose_name: str | None = Field(default=None, description="Tên hiển thị thân thiện của cột, nếu có.")
    type: str | None = Field(default=None, description="Kiểu dữ liệu.")
    description: str | None = Field(default=None, description="Mô tả cột.")
    is_sensitive: bool | None = Field(default=None, description="Cột nhạy cảm; null nghĩa là chưa phân loại.")
    is_queryable: bool | None = Field(default=None, description="Cột được phép truy vấn; null nghĩa là chưa cấu hình.")


class MetricCatalogDTO(BaseModel):
    dataset_id: int = Field(description="ID dataset chứa metric.")
    name: str = Field(description="Tên metric chính xác trong Superset.")
    verbose_name: str | None = Field(default=None, description="Tên hiển thị thân thiện của metric, nếu có.")
    description: str | None = Field(default=None, description="Mô tả metric.")
    allowed_aggregations: list[str] = Field(default_factory=list, description="Phép tổng hợp được cho phép.")


class ChartCatalogDTO(BaseModel):
    id: int = Field(description="ID chart trong Superset.")
    name: str | None = Field(default=None, description="Tên chart.")
    description: str | None = Field(default=None, description="Mô tả chart.")
    metrics: list[str] = Field(default_factory=list, description="Metric đang dùng trong chart.")
    dimensions: list[str] = Field(default_factory=list, description="Dimension đang dùng trong chart.")


class ToolDocumentationInput(BaseModel):
    tool_name: str = Field(description="Tên chính xác của công cụ cần đọc tài liệu Markdown.")


# ============================================================
# DOCUMENTATION
# ============================================================

TOOL_DOCS = {
    "superset_charts",
    "get_dataset_catalog",
    "get_column_catalog",
    "get_metric_catalog",
    "get_chart_catalog",
    "validate_bi_contract",
    "get_chart_capabilities",
    "get_superset_chart_types",
    "get_superset_chart_type_schema",
    "validate_metadata_resolution",
    "query_dataset",
    "compile_chat_chart",
}


def _load_tool_documentation(tool_name: str) -> str:
    if tool_name not in TOOL_DOCS:
        raise ValueError(f"Không tìm thấy tài liệu cho tool: {tool_name}")

    docs_package = __package__.rsplit(".", 1)[0]
    artifact = files(docs_package).joinpath("tool_docs").joinpath(f"{tool_name}.md")

    try:
        return artifact.read_text(encoding="utf-8")
    except (OSError, ValueError, TypeError, ModuleNotFoundError):
        pass

    # Fallback cho Superset .supx khi tài liệu được đóng gói trong memory.
    resource_module = f"{docs_package}.tool_docs.{tool_name}"

    for finder in sys.meta_path:
        modules = getattr(finder, "modules", None)
        entry = modules.get(resource_module) if isinstance(modules, dict) else None

        if entry is None:
            continue

        resource = entry[0]

        if isinstance(resource, bytes):
            return resource.decode("utf-8")

        if isinstance(resource, str):
            return resource

    raise RuntimeError(
        f"Không thể đọc tài liệu '{tool_name}.md'. "
        "Kiểm tra cấu hình đóng gói resource trong Superset extension."
    )


@tool(args_schema=ToolDocumentationInput)
def get_tool_documentation(tool_name: str) -> str:
    """Đọc tài liệu Markdown hướng dẫn sử dụng chi tiết của một công cụ.

    Sử dụng khi cần tìm hiểu tham số đầu vào, cấu trúc đầu ra, quy tắc sử dụng,
    ví dụ gọi công cụ, giới hạn hoặc cách xử lý lỗi.

    Chỉ đọc tài liệu của những công cụ đã được đăng ký.
    Không thực thi công cụ và không truy vấn dữ liệu.
    """
    if tool_name not in TOOL_DOCS:
        return json.dumps({
            "error": f"Không tìm thấy tài liệu cho tool '{tool_name}'.",
            "available_tools": sorted(TOOL_DOCS),
        }, ensure_ascii=False)

    try:
        return _load_tool_documentation(tool_name)
    except (OSError, RuntimeError, UnicodeError) as exc:
        return json.dumps({
            "error": "Không thể tải tài liệu công cụ.",
            "tool_name": tool_name,
            "details": str(exc),
        }, ensure_ascii=False)


# ============================================================
# HELPERS
# ============================================================

def _get_dashboard_datasets(runtime: ToolRuntime):
    datasets = get_dashboard_datasets(
        runtime.context["dashboard_id"],
        superset_client,
    )

    allowed_ids = set(runtime.context["allowed_dataset_ids"])

    return [
        dataset
        for dataset in datasets
        if dataset.id in allowed_ids
    ]


def _get_dashboard_charts(runtime: ToolRuntime):
    return get_dashboard_charts(
        runtime.context["dashboard_id"],
        superset_client,
    )


def _select_dashboard_datasets(
    runtime: ToolRuntime,
    dataset_id: int | None = None,
) -> list | dict:
    allowed_ids = runtime.context["allowed_dataset_ids"]

    if dataset_id is not None and dataset_id not in allowed_ids:
        return {
            "error": f"Dataset ID {dataset_id} không thuộc dashboard hiện tại.",
            "allowed_dataset_ids": allowed_ids,
            "next_step": "Gọi get_dataset_catalog và dùng đúng ID trong kết quả.",
        }

    datasets = _get_dashboard_datasets(runtime)

    if dataset_id is None:
        return datasets

    selected = [
        dataset
        for dataset in datasets
        if dataset.id == dataset_id
    ]

    if not selected:
        return {
            "error": f"Dataset ID {dataset_id} không tồn tại trong catalog dashboard hiện tại.",
            "allowed_dataset_ids": [dataset.id for dataset in datasets],
            "next_step": "Gọi get_dataset_catalog để lấy danh sách dataset hiện có.",
        }

    return selected


def _names(values: list) -> list[str]:
    names = []

    for value in values:
        if isinstance(value, str):
            names.append(value)

        elif isinstance(value, dict):
            name = next(
                (
                    value[key]
                    for key in ("label", "metric_name", "column_name")
                    if isinstance(value.get(key), str)
                ),
                None,
            )

            if name:
                names.append(name)

    return list(dict.fromkeys(names))


# ============================================================
# DATASET CATALOG
# ============================================================

@tool
def get_dataset_catalog(runtime: ToolRuntime) -> list[dict]:
    """Dùng để tìm dataset thuộc dashboard và lấy ID/tên/schema/mô tả trước khi truy vấn.

    Gọi khi chưa biết dataset phù hợp. Tool này chỉ trả metadata, không trả dữ liệu hàng.
    """
    datasets = _get_dashboard_datasets(runtime)

    return [
        DatasetCatalogDTO(
            id=dataset.id,
            name=dataset.name or dataset.datasource_name,
            schema_=dataset.schema_,
            description=getattr(dataset, "description", None),
        ).model_dump(by_alias=True)
        for dataset in datasets
    ]


# ============================================================
# COLUMN CATALOG
# ============================================================

@tool
def get_column_catalog(
    runtime: ToolRuntime,
    dataset_id: int | None = None,
) -> list[dict] | dict:
    """Tra cứu cột có trong dataset để ánh xạ field, dimension hoặc cột thời gian.

    Chỉ gọi khi cần biết tên/kiểu/trạng thái queryable của cột. Nếu đã chọn dataset,
    truyền dataset_id để chỉ lấy cột của dataset đó. Đây là metadata, không phải giá trị dữ liệu.
    """
    datasets = _select_dashboard_datasets(runtime, dataset_id)

    if isinstance(datasets, dict):
        return datasets

    return [
        ColumnCatalogDTO(
            dataset_id=dataset.id,
            name=column.column_name,
            verbose_name=column.verbose_name,
            type=column.type,
            description=column.description,
            is_sensitive=column.is_sensitive,
            is_queryable=column.is_queryable,
        ).model_dump()
        for dataset in datasets
        for column in dataset.columns
    ]


# ============================================================
# METRIC CATALOG
# ============================================================

@tool
def get_metric_catalog(
    runtime: ToolRuntime,
    dataset_id: int | None = None,
) -> list[dict] | dict:
    """Tra cứu metric đã định nghĩa và các phép tổng hợp được phép trong dataset.

    Dùng khi câu hỏi nhắc đến metric có sẵn hoặc cần xác nhận metric trước khi query_dataset.
    Nếu đã chọn dataset, truyền dataset_id. Tool này chỉ trả metadata, không tính metric.
    """
    datasets = _select_dashboard_datasets(runtime, dataset_id)

    if isinstance(datasets, dict):
        return datasets

    return [
        MetricCatalogDTO(
            dataset_id=dataset.id,
            name=metric.metric_name,
            verbose_name=metric.verbose_name,
            description=metric.description,
            allowed_aggregations=metric.allowed_aggregations,
        ).model_dump()
        for dataset in datasets
        for metric in dataset.metrics
    ]


# ============================================================
# CHART CATALOG
# ============================================================

@tool
def get_chart_catalog(runtime: ToolRuntime) -> list[dict]:
    """Liệt kê chart có trên dashboard cùng các metric/dimension cấu hình trong chart.

    Dùng khi người dùng hỏi về chart hiện có hoặc khi cần tham khảo chart để hiểu cách
    dashboard đang biểu diễn dữ liệu. Không dùng kết quả này thay cho truy vấn dữ liệu.
    """
    charts = _get_dashboard_charts(runtime)

    return [
        ChartCatalogDTO(
            id=chart.id,
            name=chart.slice_name,
            description=chart.description,
            metrics=_names(chart.form_data.metrics) if chart.form_data else [],
            dimensions=_names(
                [
                    *chart.form_data.groupby,
                    *chart.form_data.columns,
                ]
            ) if chart.form_data else [],
        ).model_dump()
        for chart in charts
    ]
