# get_column_catalog

## Mục đích
Đọc catalog cột của một hoặc tất cả dataset thuộc dashboard; dùng để ánh xạ ngôn ngữ nghiệp vụ sang **tên cột vật lý chính xác** trước khi truy vấn.

## Khi nào dùng
- Cần tìm tên cột nhiệt độ, thành phố, timestamp, dimension hoặc field để filter/sort.
- Cần biết kiểu cột, mô tả, tên hiển thị, trạng thái nhạy cảm/queryable.
- `query_dataset` trả `available_columns` hoặc lỗi cột không tồn tại.

## Chữ ký
```python
get_column_catalog(dataset_id: int | None = None, runtime: ToolRuntime = ...) -> list[dict] | dict
```
`runtime` được hệ thống inject, không phải đầu vào do LLM cung cấp.

| Tham số | Bắt buộc | Ý nghĩa |
|---|---|---|
| `dataset_id` | Không | Nếu có, chỉ lấy cột của dataset đó; nếu không, lấy các dataset trong dashboard |

## Kết quả
Mỗi cột có: `dataset_id`, `name` (tên vật lý), `verbose_name`, `type`, `description`, `is_sensitive`, `is_queryable`.

**Ví dụ minh họa:**
```json
[
  {"dataset_id": 12, "name": "ten_thanhpho", "verbose_name": "Thành phố", "type": "VARCHAR", "description": null, "is_sensitive": false, "is_queryable": true},
  {"dataset_id": 12, "name": "thoi_gian_ghi_nhan", "verbose_name": "Thời điểm", "type": "TIMESTAMP", "description": null, "is_sensitive": false, "is_queryable": true}
]
```

## Ví dụ quy trình
Yêu cầu: "Nhiệt độ gần nhất ở Hà Nội".
1. Xác minh `dataset_id` bằng `get_dataset_catalog` (nếu chưa biết).
2. Gọi `get_column_catalog(dataset_id=12)`.
3. Xác nhận cột thành phố, nhiệt độ và thời gian từ kết quả **thực tế**.
4. Dùng các tên vật lý đó trong `query_dataset`.

## Lỗi và cách xử lý
- Dataset ngoài `allowed_dataset_ids`: tool trả `error`, `allowed_dataset_ids`, `next_step`. Chọn lại ID hợp lệ.
- Cột không tồn tại: không phỏng đoán; kiểm tra catalog và tên vật lý.
- `is_sensitive=true` hoặc `is_queryable=false`: **không sử dụng cột** trong `query_dataset`.
- Giá trị `null` ở `is_sensitive` / `is_queryable` nghĩa là **chưa cấu hình**, không phải khẳng định an toàn.

## Lưu ý
- Tool chỉ trả metadata, không trả distinct values; không thể khẳng định trong cột có bản ghi "Hà Nội" nếu chưa query.
- Khi truyền `dataset_id=None`, code hiện tại lấy dữ liệu từ tất cả dataset thuộc dashboard mà helper trả về.
- `query_dataset` có fallback tìm cột theo verbose name/token, nhưng nên ưu tiên `name` vật lý từ catalog để tránh nhập nhằng.