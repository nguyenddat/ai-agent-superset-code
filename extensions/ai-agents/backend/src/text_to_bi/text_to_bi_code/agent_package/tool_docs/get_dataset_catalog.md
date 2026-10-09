# get_dataset_catalog

## Mục đích
Liệt kê các dataset thuộc **dashboard hiện tại** để xác định `dataset_id` phù hợp trước khi truy vấn. Chỉ trả metadata, không trả dữ liệu hàng hoặc số liệu đo lường.

## Khi nào dùng
- Chưa biết dataset nào chứa đối tượng hoặc metric người dùng hỏi.
- `query_dataset` trả lỗi dataset không thuộc dashboard hoặc catalog không còn đồng bộ.
- Cần biết tên, schema, mô tả dataset để lựa chọn đúng nguồn.

## Khi nào không dùng
- Dataset ID đã được xác minh trong ngữ cảnh hiện tại và không có lý do làm mới catalog.
- Muốn lấy bản ghi, nhiệt độ, giá trị metric: dùng `query_dataset` sau khi xác minh schema.

## Chữ ký và tham số
```python
get_dataset_catalog(runtime: ToolRuntime) -> list[dict]
```
Không có tham số do LLM nhập. `runtime.context["dashboard_id"]` được hệ thống inject.

## Kết quả
Mỗi phần tử có:

| Trường | Kiểu | Ý nghĩa |
|---|---|---|
| `id` | `int` | Dataset ID cần dùng trong các tool khác |
| `name` | `str \| null` | Tên dataset (`dataset.name` hoặc `datasource_name`) |
| `schema` | `str \| null` | Schema của dataset |
| `description` | `str \| null` | Mô tả, nếu có |

**Ví dụ minh họa, không phải metadata thực tế:**
```json
[{"id": 12, "name": "weather_daily", "schema": "public", "description": "Quan sát thời tiết"}]
```

## Quy trình gọi
1. Gọi tool không có đối số.
2. Xác định ứng viên dựa vào `name`, `description`, `schema`.
3. Nếu còn mơ hồ, gọi `get_column_catalog(dataset_id=...)` hoặc `get_metric_catalog(dataset_id=...)` để kiểm tra.
4. Chỉ dùng ID có trong catalog và `allowed_dataset_ids`.

## Ranh giới và lưu ý triển khai
- Dữ liệu lấy từ `get_dashboard_datasets(runtime.context["dashboard_id"], superset_client)`.
- Code hiện tại **không lọc lại `allowed_dataset_ids` trong hàm này**; không coi việc dataset xuất hiện là quyền truy vấn. `query_dataset` vẫn kiểm tra quyền truy cập.
- Không suy đoán cấu trúc cột từ tên dataset.
- Không dùng metadata làm bằng chứng cho giá trị quan sát.