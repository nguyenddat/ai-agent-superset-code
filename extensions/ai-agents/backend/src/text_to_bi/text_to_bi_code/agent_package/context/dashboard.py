from typing import Any

import requests
from pydantic import BaseModel, ConfigDict, Field

from ...core.settings import config

class ColumnDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")

    column_name: str = Field(description="Tên vật lý của cột trong dataset.")
    verbose_name: str | None = Field(default=None, description="Tên hiển thị thân thiện của cột.")
    type: str | None = Field(default=None, description="Kiểu dữ liệu của cột.")
    description: str | None = Field(default=None, description="Mô tả ý nghĩa nghiệp vụ của cột.")
    is_dttm: bool | None = Field(default=None, description="Cho biết cột có phải là cột thời gian hay không.")
    is_sensitive: bool | None = Field(default=None, description="Cột có chứa dữ liệu nhạy cảm hay không; None nghĩa là chưa phân loại.")
    is_queryable: bool | None = Field(default=None, description="Cột có được phép truy vấn hay không; None nghĩa là chưa cấu hình.")


class MetricDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")

    metric_name: str = Field(description="Tên định danh của metric trong dataset.")
    verbose_name: str | None = Field(default=None, description="Tên hiển thị thân thiện của metric.")
    expression: str | None = Field(default=None, description="Biểu thức SQL hoặc biểu thức tính toán định nghĩa metric.")
    description: str | None = Field(default=None, description="Mô tả ý nghĩa nghiệp vụ của metric.")
    allowed_aggregations: list[str] = Field(default_factory=list, description="Các phép tổng hợp đã được cho phép.")


class DatasetDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int = Field(description="ID của dataset trong Superset.")
    name: str | None = Field(default=None, description="Tên của dataset.")
    description: str | None = Field(default=None, description="Mô tả dataset.")
    datasource_name: str | None = Field(default=None, description="Tên datasource được Superset sử dụng.")
    schema_: str | None = Field(default=None, alias="schema", description="Tên schema chứa bảng hoặc dataset.")
    table_name: str | None = Field(default=None, description="Tên bảng vật lý hoặc bảng logic của dataset.")
    type: str | None = Field(default=None, description="Loại datasource của dataset, ví dụ table hoặc query.")
    main_dttm_col: str | None = Field(default=None, description="Cột thời gian chính được cấu hình cho dataset.")
    column_names: list[str] = Field(default_factory=list, description="Danh sách tên các cột có trong dataset.")
    columns: list[ColumnDTO] = Field(default_factory=list, description="Metadata chi tiết của các cột trong dataset.")
    metrics: list[MetricDTO] = Field(default_factory=list, description="Danh sách metric được định nghĩa sẵn trong dataset.")


class ChartFormDataDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")

    datasource: str | None = Field(default=None, description="Datasource mà chart đang sử dụng.")
    viz_type: str | None = Field(default=None, description="Loại visualization của chart.")
    metrics: list[Any] = Field(default_factory=list, description="Các metric được sử dụng trong chart.")
    groupby: list[str] = Field(default_factory=list, description="Các cột được dùng để nhóm dữ liệu trong chart.")
    columns: list[Any] = Field(default_factory=list, description="Các cột được sử dụng trong cấu hình chart.")
    time_range: str | None = Field(default=None, description="Khoảng thời gian được áp dụng cho chart.")
    granularity: str | None = Field(default=None, description="Cột hoặc mức granularity thời gian của chart.")
    time_grain_sqla: str | None = Field(default=None, description="Mức gom nhóm thời gian, ví dụ ngày, tuần hoặc tháng.")
    row_limit: int | None = Field(default=None, description="Giới hạn số dòng được cấu hình cho truy vấn của chart.")
    x_axis: Any | None = Field(default=None, description="Cấu hình hoặc trường dữ liệu được sử dụng cho trục X.")
    y_axis: Any | None = Field(default=None, description="Cấu hình hoặc trường dữ liệu được sử dụng cho trục Y.")


class ChartDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int = Field(description="ID của chart trong Superset.")
    slice_name: str | None = Field(default=None, description="Tên hiển thị của chart.")
    description: str | None = Field(default=None, description="Mô tả nội dung hoặc mục đích của chart.")
    form_data: ChartFormDataDTO | None = Field(default=None, description="Cấu hình visualization của chart.")


def _get_dashboard_resource(dashboard_id: int, resource: str, session: Any):
    url = f"{config.superset_base_url}/api/v1/dashboard/{dashboard_id}/{resource}"

    try:
        response = session.get(url, timeout=30)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise RuntimeError(
            f"Unable to fetch dashboard {resource} for dashboard {dashboard_id}"
        ) from exc

    result = payload.get("result")
    if not isinstance(result, list):
        raise RuntimeError(
            f"Invalid Superset {resource} response: expected a result list"
        )

    return result


def get_dashboard_datasets(dashboard_id: int, session: requests.Session) -> list[DatasetDTO]:
    return [
        DatasetDTO.model_validate(item)
        for item in _get_dashboard_resource(dashboard_id, "datasets", session)
    ]


def get_dashboard_charts(dashboard_id: int, session: requests.Session) -> list[ChartDTO]:
    return [
        ChartDTO.model_validate(item)
        for item in _get_dashboard_resource(dashboard_id, "charts", session)
    ]


def get_dashboard_title(dashboard_id: int, session: Any) -> str:
    url = f"{config.superset_base_url}/api/v1/dashboard/{dashboard_id}"
    try:
        response = session.get(url, timeout=30)
        response.raise_for_status()
        result = response.json().get("result", {})
    except (requests.RequestException, ValueError) as exc:
        raise RuntimeError(f"Unable to fetch dashboard {dashboard_id}") from exc
    if not isinstance(result, dict) or not isinstance(result.get("dashboard_title"), str):
        raise RuntimeError(f"Invalid Superset dashboard response for {dashboard_id}")
    return result["dashboard_title"]
