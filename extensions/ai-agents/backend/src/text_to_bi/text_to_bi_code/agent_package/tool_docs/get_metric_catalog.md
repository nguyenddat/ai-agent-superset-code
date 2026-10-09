# get_metric_catalog

## Mục đích
Liệt kê các metric **đã định nghĩa** trên Superset cùng mô tả và các phép tổng hợp được catalog khai báo. Tool chỉ đọc metadata, không tính số liệu.

## Khi nào dùng
- Người dùng hỏi metric nghiệp vụ, ví dụ doanh thu, số đơn, KPI đã có trong dataset.
- Cần phân biệt metric có sẵn với cột số cần phép tổng hợp (`avg`, `sum`, v.v.).
- Cần xác minh tên metric trước khi truyền vào `query_dataset`.

## Chữ ký
```python
get_metric_catalog(dataset_id: int | None = None, runtime: ToolRuntime = ...) -> list[dict] | dict
```
`runtime` được inject. Nếu có `dataset_id`, chỉ tra cứu một dataset.

## Kết quả
Các trường: `dataset_id: int`, `name: str`, `verbose_name: str|null`, `description: str|null`, `allowed_aggregations: list[str]`.

**Ví dụ minh họa:**
```json
[{"dataset_id": 12, "name": "avg_temperature", "verbose_name": "Nhiệt độ trung bình", "description": "Giá trị trung bình", "allowed_aggregations": []}]
```

## Cách dùng cùng query_dataset
**Metric đã lưu:**
```json
{"metrics": [{"name": "avg_temperature", "aggregation": null}]}
```
**Cột vật lý với phép tổng hợp:**
```json
{"metrics": [{"name": "nhiet_do_c", "aggregation": "avg"}]}
```
Các JSON trên chỉ là **phần** của đầu vào `query_dataset`; cần thêm `dataset_id` và các trường tương ứng.

## Quy tắc quan trọng
- Với **metric đã định nghĩa sẵn**, để `aggregation=null`. Code từ chối tổng hợp thêm lên metric có sẵn.
- Với **cột số**, cung cấp `aggregation` trong `sum`, `avg`, `count`, `min`, `max`.
- Không dùng `avg` khi câu hỏi yêu cầu một quan sát nhiệt độ mới nhất; hãy lấy record và sắp xếp timestamp giảm dần.
- Không coi `allowed_aggregations` là khả năng thực thi được bảo đảm: `query_dataset` hiện chủ yếu dựa vào `MetricRequest.aggregation` và kiểm tra cột. Cần kiểm tra logic thực thi khi thêm chính sách tổng hợp theo catalog.
- Dataset ngoài phạm vi: kết quả là dict lỗi, không phải danh sách.