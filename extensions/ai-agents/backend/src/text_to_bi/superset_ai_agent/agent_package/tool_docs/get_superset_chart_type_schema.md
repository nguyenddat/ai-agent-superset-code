# get_superset_chart_type_schema

Đọc JSON Schema và ví dụ cấu hình cho một `chart_type` do
`get_superset_chart_types` trả về. Dùng schema này để ánh xạ dimension, metric,
filter, trục và tùy chọn biểu đồ theo BI Plan.

Nếu Superset trả lỗi hoặc trường cần thiết không được schema hỗ trợ, báo rõ hạn chế;
không tự đoán cấu hình. Công cụ chỉ đọc metadata, không chạy truy vấn, tạo chart hay
sửa dashboard.
