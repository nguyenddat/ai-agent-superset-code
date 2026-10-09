# query_dataset

## Mục đích
Thực thi truy vấn **có cấu trúc** qua Superset ChartData API nội bộ đối với dataset thuộc dashboard hiện tại. Tool không nhận raw SQL và chỉ đọc dữ liệu. Dùng để retrieve/filter/aggregate/compare theo những khả năng đã triển khai.

## Khi nào dùng
- Người dùng hỏi giá trị thực tế: nhiệt độ, thời điểm ghi nhận, doanh thu, số lượng.
- Cần lọc bản ghi, lấy bản ghi mới nhất, tính tổng/trung bình, nhóm theo dimension.
- Không dùng catalog metadata để thay thế tool này khi câu hỏi đòi dữ liệu thực tế.

## Điều kiện tiên quyết
1. Xác định `dataset_id` thuộc dashboard qua `get_dataset_catalog` hoặc metadata đã xác minh.
2. Xác định tên **cột vật lý** qua `get_column_catalog` và tên metric có sẵn qua `get_metric_catalog` khi cần.
3. Không yêu cầu cột có `is_queryable=false` hoặc `is_sensitive=true`.
4. Nếu context có `analysis_time_expression` (không rỗng), code **bắt buộc** `time_range` không rỗng. Đây là ràng buộc implementation, không có nghĩa mọi biểu thức như "hiện tại" được Superset nhận trực tiếp.

## Tham số
```python
query_dataset(
    dataset_id: int,
    columns: list[str] = [],
    metrics: list[MetricRequest] = [],
    filters: list[FilterRequest] = [],
    group_by: list[str] = [],
    time_range: str | None = None,
    order_by: list[str] = [],
    limit: int = 100,
    runtime: ToolRuntime = ...,  # inject; LLM không cung cấp
)
```

| Trường | Ý nghĩa / yêu cầu |
|---|---|
| `dataset_id` | ID dataset được phép trong `allowed_dataset_ids` |
| `columns` | Các cột cần lấy ở dạng record; `['*']` lấy tất cả cột được phép; **không dùng `*`** trong các trường khác |
| `metrics` | Danh sách `{"name": string, "aggregation": "sum"\|"avg"\|"count"\|"min"\|"max"\|null}` |
| `filters` | Danh sách `{"field": string, "operator": ..., "value": string\|list[string]}` |
| `group_by` | Các cột dùng để phân nhóm; code đưa cùng vào `columns` gửi tới Superset |
| `time_range` | Biểu thức thời gian theo Superset; `Today` và `Yesterday` được resolve theo `config.query_timezone` |
| `order_by` | Danh sách cột/metric; prefix `-` là giảm dần, ví dụ `-thoi_gian_ghi_nhan` |
| `limit` | 1–100, mặc định 100 |

**Filter operators:** `=`, `!=`, `>`, `>=`, `<`, `<=`, `in`, `not_in`, `contains`, `between`, `relative_time`.
- `in`, `not_in`: `value` có thể là chuỗi phân cách dấu phẩy hoặc danh sách.
- `between`: `value` **phải là danh sách đúng 2 phần tử**; được đổi thành `>=` và `<=` (bao gồm hai đầu).
- `contains`: được đổi thành ILIKE `%value%`.
- `relative_time`: được map thành `TEMPORAL_RANGE`.

## Ví dụ gọi: Quan sát mới nhất tại Hà Nội
Giả sử **catalog thực tế đã xác minh** dataset `12` và các cột `ten_thanhpho`, `nhiet_do_c`, `thoi_gian_ghi_nhan`.

```json
{
  "dataset_id": 12,
  "columns": ["ten_thanhpho", "nhiet_do_c", "thoi_gian_ghi_nhan"],
  "metrics": [],
  "filters": [{"field": "ten_thanhpho", "operator": "=", "value": "Hà Nội"}],
  "group_by": [],
  "time_range": null,
  "order_by": ["-thoi_gian_ghi_nhan"],
  "limit": 1
}
```

**Lưu ý quan trọng:** Ví dụ trên chỉ chạy khi runtime **không có** `analysis_time_expression`. Nếu trường đó chứa "hiện tại, lúc 11:22", implementation hiện tại sẽ trả lỗi bắt buộc `time_range`. Cần dịch intent thành khoảng Superset hợp lệ và thống nhất chính sách có/không lọc thời gian để tìm bản ghi mới nhất. **Không đưa thẳng chuỗi ngôn ngữ tự nhiên tùy ý vào `time_range` nếu không được Superset hỗ trợ.**

## Ví dụ gọi: Nhiệt độ trung bình theo thành phố hôm nay
```json
{
  "dataset_id": 12,
  "columns": [],
  "metrics": [{"name": "nhiet_do_c", "aggregation": "avg"}],
  "filters": [],
  "group_by": ["ten_thanhpho"],
  "time_range": "Today",
  "order_by": ["-nhiet_do_c"],
  "limit": 20
}
```

Trong truy vấn tổng hợp, chỉ sắp xếp theo metric được yêu cầu hoặc cột có trong `group_by`; không sắp xếp theo cột không được group.

## Ví dụ gọi: Lấy các record của ngày hôm qua
```json
{
  "dataset_id": 12,
  "columns": ["thoi_gian_ghi_nhan", "nhiet_do_c"],
  "metrics": [],
  "filters": [{"field": "ten_thanhpho", "operator": "=", "value": "Hà Nội"}],
  "group_by": [],
  "time_range": "Yesterday",
  "order_by": ["-thoi_gian_ghi_nhan"],
  "limit": 100
}
```

## Kết quả
Tool hiện trả về **JSON được serialize thành string**, nội dung mẫu:
```json
{
  "columns": ["ten_thanhpho", "nhiet_do_c", "thoi_gian_ghi_nhan"],
  "rows": [{"ten_thanhpho": "Hà Nội", "nhiet_do_c": 25, "thoi_gian_ghi_nhan": "2026-10-08T08:30:00"}],
  "row_count": 1,
  "truncated": false,
  "time_range": null,
  "time_zone": "Asia/Ho_Chi_Minh",
  "superset_form_data": {"datasource": "12__table", "viz_type": "echarts_bar"}
}
```
Đây là **ví dụ cấu trúc được rút gọn**, không phải kết quả thực tế. `superset_form_data` trong kết quả thật còn có `x_axis`, `groupby`, `metrics`, `adhoc_filters`, `time_range`, `row_limit`, `orderby`.

- `rows`: dữ liệu truy vấn thực tế; cần đọc timestamp thực tế trước khi trả lời.
- `row_count`: số dòng trả ra trong giới hạn, **không phải tổng số dòng của dataset**.
- `truncated=true`: còn nhiều hơn `limit` dòng trong kết quả đã lấy để phát hiện giới hạn; không kết luận toàn bộ dataset đã được kiểm tra.
- `time_zone`: giá trị `config.query_timezone` của hệ thống; **không chứng minh** rằng mỗi timestamp trong `rows` đã được chuyển sang múi giờ này.
- `superset_form_data`: cấu hình gợi ý cho chart; không phải kết quả tạo hoặc lưu chart.

## Lỗi và xử lý
| Trạng thái | Cách xử lý |
|---|---|
| Dataset ID ngoài dashboard | Kiểm tra `allowed_dataset_ids`, gọi `get_dataset_catalog` |
| `analysis_time_expression` có nhưng `time_range` rỗng | Chọn biểu thức Superset hợp lệ hoặc điều chỉnh pipeline ở code; không truyền lại nguyên văn intent nếu không được hỗ trợ |
| Field sai | Dùng `available_columns` và `get_column_catalog`; không tự bịa tên |
| Cột nhạy cảm/không queryable | Không truy vấn cột này |
| Metric là cột nhưng `aggregation=null` | Bổ sung phép tổng hợp, hoặc chuyển sang `columns` để lấy record |
| Metric lưu sẵn nhưng thêm aggregation | Đặt `aggregation=null` |
| `between` không có đúng 2 giá trị | Sửa danh sách 2 phần tử |
| Không có columns/metrics | Bổ sung ít nhất một cột hoặc metric |
| Sắp xếp bằng cột không thuộc group_by trong truy vấn tổng hợp | Sắp xếp theo metric hoặc đưa dimension vào group_by |
| Superset báo lỗi | Dựa vào `error` và `details`, không tuyên bố truy vấn thành công |
| `rows=[]` | Chỉ nói không có dữ liệu trong **đúng phạm vi đã truy vấn**, không đoán nguyên nhân |

## Thời gian và độ mới dữ liệu
- `Today` / `Yesterday` được chuyển thành khoảng ngày local (`config.query_timezone`) bằng `datetime.now(ZoneInfo(...))`.
- `time_range` khác được gửi xuống Superset **không qua chuyển đổi bổ sung** trong `_resolve_relative_day`.
- Không tự giả định UTC, UTC+7 hay double-conversion từ giá trị trả về; phải biết định nghĩa cột dataset và cấu hình truy vấn.
- Đối với "hiện tại", phân biệt **thời điểm bây giờ** và **lần ghi nhận mới nhất**; nếu có đủ mốc thời gian, nêu độ trễ, không mô tả bản ghi cũ là real-time.

## Cảnh báo về implementation hiện tại
1. Tool **không nhận SQL thô**.
2. Tool chưa có logic kết hợp `OR` tùy ý; các filter được gửi như danh sách thông thường.
3. Tool chưa cung cấp pagination đầy đủ, chỉ `limit` tối đa 100.
4. Với truy vấn có `metrics`, code gửi `selected_columns` vào `queries[0].columns`, đồng thời `group_by` không phải trường riêng trong payload Superset. Cần kiểm thử logic nhóm với phiên bản Superset đang chạy.
5. Code hiện tại build `superset_form_data` với `viz_type='echarts_bar'` cố định; không tự chọn line/pie theo intent.
6. Tool trả JSON string khi thành công nhưng dict khi có một số lỗi: downstream cần xử lý cả hai dạng.
7. Chỉ coi dữ liệu ở `rows` là bằng chứng quan sát; **không** tự tuyên bố đã tạo chart hoặc cập nhật dashboard.