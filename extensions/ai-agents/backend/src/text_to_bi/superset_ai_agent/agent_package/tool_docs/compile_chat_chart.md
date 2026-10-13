# compile_chat_chart

## Mục đích

Xác nhận SQL Data Builder vừa chạy thành công, sau đó compile chart bằng compile pipeline native của Superset trên dataset hiện có trong dashboard. Cấu hình Metadata Resolution quyết định tham số chart như trục, metric, bộ lọc và khoảng thời gian; tool không tạo virtual dataset mới. Nếu trục X là thời gian và BI Plan không nêu grain cho yêu cầu hôm nay, công cụ dùng grain theo giờ để tránh gộp toàn bộ ngày thành một điểm. Công cụ báo lỗi nếu chart không có điểm dữ liệu hoặc chart đường chỉ có một điểm. Công cụ không lưu chart, không trả các dòng dữ liệu, và hiện không chụp/đọc ảnh trình duyệt.

## Đầu vào

- `sql`: đúng câu SQL vừa chạy thành công qua `query_sql`.

Dataset, dashboard, quyền truy cập và cấu hình Metadata Resolution được lấy từ runtime context tin cậy; không truyền các giá trị này trong arguments.

## Kết quả

- Khi thành công: `success=true` và `chart_url` để frontend mở chart.
- Khi thất bại: `success=false` và `error` có thông báo compile/query từ Superset hoặc lỗi chuẩn bị chart.

Tool chỉ trả trạng thái, thông báo lỗi và URL. Không trả dữ liệu raw, ảnh hay nội dung truy vấn chart.

## Quy trình Data Builder

1. Gọi `query_sql` với SQL dự kiến.
2. Nếu thành công, gọi `compile_chat_chart` với cùng SQL.
3. Nếu một trong hai tool lỗi, sửa SQL theo thông báo, rồi chạy lại cả `query_sql` và `compile_chat_chart`.
4. Chỉ trả SQL cuối cùng sau khi cả hai tool báo thành công với cùng một câu SQL.

Không đổi BI Plan hoặc Metadata Resolution để né compile error. Nếu lỗi yêu cầu đổi loại biểu đồ, metric hoặc ý nghĩa phân tích, báo lỗi để pipeline phía trên xử lý.

## Giới hạn

Compile check xác nhận chart query chạy được qua Superset và trả tối đa trạng thái/diagnostic. Nó không render giao diện trình duyệt, kiểm tra pixel, nhãn, màu hoặc bố cục bằng mắt. Việc kiểm tra ảnh cần một browser renderer callable từ backend; Playwright MCP của phiên phát triển không thuộc runtime toolset của agent.
