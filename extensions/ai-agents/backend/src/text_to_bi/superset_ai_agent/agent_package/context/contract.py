from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class UserIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: str = Field(description="Người dùng thực sự muốn tìm hiểu, so sánh, đo lường hoặc khám phá điều gì thông qua phân tích dữ liệu?")


class DataMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="metric_name lưu sẵn hoặc column_name chính xác trong dataset.")
    aggregation: Literal["sum", "avg", "count", "min", "max"] | None = Field(default=None, description="Để null khi dùng metric lưu sẵn; bắt buộc khi tổng hợp một cột.")


class DataFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = Field(description="column_name chính xác trong dataset.")
    operator: Literal["=", "!=", ">", ">=", "<", "<=", "in", "not_in", "contains", "between", "relative_time"]
    value: str | list[str] = Field(description="Giá trị lọc; between nhận đúng hai giá trị.")


class DataSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: int = Field(description="ID dataset Superset đã được xác thực từ metadata và nằm trong phạm vi được phép.")
    columns: list[str] = Field(default_factory=list, description="Các column_name cần truy xuất ở dạng bản ghi chi tiết.")
    metrics: list[DataMetric] = Field(default_factory=list, description="Các metric đã định nghĩa hoặc phép tổng hợp cần tính.")
    filters: list[DataFilter] = Field(default_factory=list, description="Các điều kiện lọc áp dụng trên dataset.")
    group_by: list[str] = Field(default_factory=list, description="Các column_name dùng làm chiều phân nhóm.")


class DataResolve(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Nguồn dữ liệu nào có thể đáp ứng yêu cầu?
    # Cần những đại lượng và chiều dữ liệu nào?
    # Dữ liệu phải được lọc và tính toán như thế nào?

    sources: list[DataSource] = Field(min_length=1, description="Các dataset cần thiết để đáp ứng yêu cầu phân tích.")
    combination: Literal["single", "independent", "join"] = Field(description="Phương thức sử dụng nhiều dataset: single dùng một dataset; independent truy vấn riêng và kết hợp kết quả; join kết hợp các nguồn theo quan hệ dữ liệu đã xác thực.")
    combination_key: list[str] = Field(default_factory=list, description="Các khóa hoặc chiều dùng để kết hợp kết quả giữa các dataset, nếu cần.")
    time_range: str | None = Field(default=None, description="Khoảng thời gian phân tích chung theo ngữ nghĩa yêu cầu.")
    time_grain: str | None = Field(default=None, description="Độ chi tiết thời gian cần cho kết quả truy vấn, ví dụ 15 phút, 1 giờ hoặc 1 ngày.")
    order_by: list[str] = Field(default_factory=list, description="Các trường cần sắp xếp; tiền tố '-' biểu thị giảm dần.")


class ChartResolve(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Cấu trúc kết quả và vai trò trường để MetadataResolution chọn biểu đồ.
    mode: Literal["auto", "chart", "table", "single_value"] = Field(default="auto", description="Luôn để auto; MetadataResolution chọn hình thức và loại biểu đồ.")
    viz_type: str | None = Field(default=None, description="Luôn để null; MetadataResolution chọn viz_type từ Superset registry.")

    # Biểu đồ yêu cầu dữ liệu có cấu trúc như thế nào?
    data_shape: Literal["raw", "aggregated", "scalar"] = Field(description="Dữ liệu chi tiết, dữ liệu tổng hợp hoặc một giá trị đơn.")

    # Mỗi dòng và mỗi điểm dữ liệu đại diện cho điều gì?
    data_grain: str = Field(description="Ý nghĩa của mỗi dòng kết quả hoặc mỗi điểm dữ liệu trên biểu đồ.")

    # Dữ liệu đầu ra ánh xạ vào các thành phần biểu đồ ra sao?
    x_axis: str | None = Field(default=None, description="Tên trường trong kết quả truy vấn dùng cho trục X.")
    y_axis: list[str] = Field(default_factory=list, description="Các tên trường hoặc metric trong kết quả truy vấn dùng cho trục Y.")
    series: str | None = Field(default=None, description="Tên trường trong kết quả truy vấn dùng để phân chia series.")
    time_comparison: Literal["previous_day"] | None = Field(
        default=None,
        description="So sánh chuỗi thời gian với ngày liền trước bằng tính năng time_compare của Superset.",
    )
    title: str | None = Field(default=None, description="Tiêu đề biểu đồ phản ánh mục tiêu phân tích.")


class BIContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_intent: UserIntent = Field(description="Mục tiêu phân tích thực sự của người dùng.")
    data_resolve: DataResolve = Field(description="Nguồn dữ liệu, các đại lượng và yêu cầu xử lý dữ liệu.")
    chart_resolve: ChartResolve = Field(description="Cấu trúc kết quả và vai trò trường; MetadataResolution quyết định loại biểu đồ.")
