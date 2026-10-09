from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class MetadataResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "unsupported"]
    chart_type: str | None = None
    viz_type: str | None = None
    dataset_id: int | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    time_range: str | None = Field(default=None, description="Khoảng thời gian dạng Superset, tách khỏi config.filters và áp dụng cho truy vấn dữ liệu.")
    message: str = Field(description="Kết quả chọn loại biểu đồ hoặc hạn chế chưa thể xử lý.")
