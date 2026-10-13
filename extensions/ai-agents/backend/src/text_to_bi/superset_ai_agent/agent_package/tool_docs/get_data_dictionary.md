# get_data_dictionary

## Mục đích

Đọc Data Dictionary tùy chọn do Semantic Layer cung cấp để hiểu thuật ngữ nghiệp vụ,
display name, unit, grain, phân loại dataset và reference giữa các cột. Tool chỉ đọc
metadata, không trả dữ liệu từng dòng.

## Khi nào dùng

- Tên vật lý của cột chưa cho biết rõ ý nghĩa nghiệp vụ.
- Cần xác nhận unit, grain hoặc phân loại base/aggregate.
- Cần dùng reference do người dùng cấu hình để xác nhận khóa liên kết.

## Chữ ký

```python
get_data_dictionary(dataset_id: int | None = None, runtime: ToolRuntime = ...) -> dict
```

`runtime` được hệ thống inject. Nếu không truyền `dataset_id`, tool chỉ đọc các dataset
trong dashboard hiện tại. Có thể truyền ID để giới hạn kết quả vào một dataset.

## Kết quả

- `available=true`: Data Dictionary đã sẵn sàng; `datasets` chứa metadata và columns.
- `available=false`: extension chưa cài/khởi tạo hoặc metadata không khả dụng. Dùng
  `get_dataset_catalog`, `get_column_catalog` và `get_metric_catalog` như bình thường.
- Dataset ngoài dashboard trả `error` và danh sách `allowed_dataset_ids`.

Mỗi column có `column_name` vật lý, `display_name`, `data_type`, `unit`, `format`,
`business_term`, trạng thái PK/FK và thông tin reference nếu có.

## Giới hạn

- Data Dictionary là nguồn bổ sung, không thay cho catalog Superset.
- Chỉ dùng column có trong catalog Superset và dataset được dashboard cho phép.
- Chỉ xem reference như khóa liên kết đã xác nhận; không tự suy ra quan hệ từ tên cột.
- Tool đọc trực tiếp các bảng metadata theo schema đã công bố, không import hoặc phụ thuộc
  package của Semantic Layer. Khi bảng không tồn tại, nó trả `available=false`.
