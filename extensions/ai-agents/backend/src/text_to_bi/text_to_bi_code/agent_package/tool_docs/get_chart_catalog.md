# get_chart_catalog

## Mục đích
Liệt kê những biểu đồ **đã tồn tại** trên dashboard, bao gồm ID, tên, mô tả, metric và dimension đang cấu hình. Không cung cấp dữ liệu nguồn hoặc khả năng tạo biểu đồ.

## Khi nào dùng
- "Dashboard này có những biểu đồ nào?"
- "Biểu đồ thời tiết đang dùng metric/dimension nào?"
- Cần tham khảo cấu hình chart hiện có trước khi xây dựng kế hoạch phân tích.

## Chữ ký
```python
get_chart_catalog(runtime: ToolRuntime) -> list[dict]
```
Không có tham số do LLM nhập; runtime inject dashboard ID.

## Kết quả
Mỗi chart trả `id`, `name`, `description`, `metrics: list[str]`, `dimensions: list[str]`.

**Ví dụ minh họa:**
```json
[{"id": 4, "name": "Nhiệt độ theo thời gian", "description": null, "metrics": ["AVG(nhiet_do_c)"], "dimensions": ["ten_thanhpho"]}]
```

## Cách diễn giải
- `metrics` và `dimensions` phản ánh cấu hình biểu đồ, không phải giá trị hiện tại.
- Danh sách được tách từ `form_data.metrics`, `form_data.groupby`, `form_data.columns`; các phần tử không trích được tên có thể bị bỏ qua.
- Nếu chart không có `form_data`, hai danh sách để trống.
- Không suy diễn chart đang hiển thị dữ liệu thời gian thực hoặc các filter runtime chỉ từ catalog này.

## Giới hạn quan trọng
- `get_chart_catalog` **không phải** công cụ tạo, sửa hoặc render chart.
- Trong bộ công cụ hiện tại chưa có tool chuyên tạo chart. `query_dataset` chỉ trả dữ liệu và `superset_form_data` gợi ý (mặc định `viz_type=echarts_bar`), không tự lưu hoặc render chart.
- Nếu được yêu cầu tạo chart thực, agent cần tool khác được triển khai và cấp quyền; không được báo đã tạo chart khi chưa có kết quả xác nhận.