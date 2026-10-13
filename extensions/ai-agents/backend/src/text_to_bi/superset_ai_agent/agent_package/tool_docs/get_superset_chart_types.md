# get_superset_chart_types

Liệt kê các `chart_type` mà chart tools của phiên bản Superset đang chạy đăng ký.
Danh sách này là metadata từ Superset, không phải danh sách chart đã lưu trên dashboard.

Dùng tiếp `get_superset_chart_type_schema(chart_type)` để lấy JSON Schema và ví dụ
cấu hình của loại biểu đồ đã chọn. Không tự tạo loại biểu đồ hoặc tham số ngoài schema.

Công cụ chỉ đọc metadata. Công cụ này không chạy truy vấn, tạo chart hay sửa dashboard.
