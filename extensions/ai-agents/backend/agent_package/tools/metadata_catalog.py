from pydantic import BaseModel, ConfigDict, Field
from langchain.tools import ToolRuntime, tool

from core.superset_client import superset_client

from ..context.dashboard import get_dashboard_charts, get_dashboard_datasets

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

def _get_dashboard_datasets(runtime: ToolRuntime):
    return get_dashboard_datasets(runtime.context["dashboard_id"], superset_client)

def _get_dashboard_charts(runtime: ToolRuntime):
    return get_dashboard_charts(runtime.context["dashboard_id"], superset_client)

def _select_dashboard_datasets(runtime: ToolRuntime, dataset_id: int | None = None) -> list | dict:
    datasets = _get_dashboard_datasets(runtime)
    allowed_ids = runtime.context["allowed_dataset_ids"]
    if dataset_id is not None:
        if dataset_id not in allowed_ids:
            return {
                "error": f"Dataset ID {dataset_id} không thuộc dashboard hiện tại.",
                "allowed_dataset_ids": allowed_ids,
                "next_step": "Gọi get_dataset_catalog và dùng đúng ID trong kết quả.",
            }
        datasets = [dataset for dataset in datasets if dataset.id == dataset_id]
    return datasets

def _names(values: list) -> list[str]:
    names = []
    for value in values:
        if isinstance(value, str):
            names.append(value)
        elif isinstance(value, dict):
            name = next((value[key] for key in ("label", "metric_name", "column_name") if isinstance(value.get(key), str)), None)
            if name:
                names.append(name)
    return list(dict.fromkeys(names))

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

@tool
def get_column_catalog(runtime: ToolRuntime, dataset_id: int | None = None) -> list[dict] | dict:
    """Tra cứu cột có trong dataset để ánh xạ field, dimension hoặc cột thời gian.

    Chỉ gọi khi cần biết tên/kiểu/trạng thái queryable của cột. Nếu đã chọn dataset,
    truyền dataset_id để chỉ lấy cột của dataset đó. Đây là metadata, không phải giá trị dữ liệu.
    """
    datasets = _select_dashboard_datasets(runtime, dataset_id)
    if isinstance(datasets, dict):
        return datasets
    return [ColumnCatalogDTO(dataset_id=dataset.id, name=column.column_name, verbose_name=column.verbose_name, type=column.type, description=column.description, is_sensitive=column.is_sensitive, is_queryable=column.is_queryable).model_dump() for dataset in datasets for column in dataset.columns]

@tool
def get_metric_catalog(runtime: ToolRuntime, dataset_id: int | None = None) -> list[dict] | dict:
    """Tra cứu metric đã định nghĩa và các phép tổng hợp được phép trong dataset.

    Dùng khi câu hỏi nhắc đến metric có sẵn hoặc cần xác nhận metric trước khi query_dataset.
    Nếu đã chọn dataset, truyền dataset_id. Tool này chỉ trả metadata, không tính metric.
    """
    datasets = _select_dashboard_datasets(runtime, dataset_id)
    if isinstance(datasets, dict):
        return datasets
    return [MetricCatalogDTO(dataset_id=dataset.id, name=metric.metric_name, verbose_name=metric.verbose_name, description=metric.description, allowed_aggregations=metric.allowed_aggregations).model_dump() for dataset in datasets for metric in dataset.metrics]

@tool
def get_chart_catalog(runtime: ToolRuntime) -> list[dict]:
    """Liệt kê chart có trên dashboard cùng các metric/dimension cấu hình trong chart.

    Dùng khi người dùng hỏi về chart hiện có hoặc khi cần tham khảo chart để hiểu cách
    dashboard đang biểu diễn dữ liệu. Không dùng kết quả này thay cho truy vấn dữ liệu.
    """
    charts = _get_dashboard_charts(runtime)
    return [ChartCatalogDTO(id=chart.id, name=chart.slice_name, description=chart.description, metrics=_names(chart.form_data.metrics) if chart.form_data else [], dimensions=_names([*chart.form_data.groupby, *chart.form_data.columns]) if chart.form_data else []).model_dump() for chart in charts]
