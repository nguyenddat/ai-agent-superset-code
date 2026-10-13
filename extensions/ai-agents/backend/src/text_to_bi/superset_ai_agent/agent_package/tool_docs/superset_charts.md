# Superset Chart — hướng dẫn API-driven cho Text-to-BI Agent

> Phạm vi: Apache Superset 6.1.x. Đây là **tài liệu hướng dẫn**, không phải một tool thực thi. Luôn đối chiếu với `/swagger/v1` của instance Superset đang chạy, vì API và schema có thể khác theo phiên bản, plugin và cấu hình.

## 1. Mục đích và nguyên tắc

Sử dụng các API chính thức của Superset để **khám phá, đọc, tham chiếu và (chỉ khi có quyền và công cụ phù hợp) tạo biểu đồ**. Không hardcode tất cả `viz_type` và `form_data` từ trí nhớ. Ưu tiên cấu hình thực được API trả về, schema của instance và ví dụ chart có sẵn cùng loại.

Phân biệt năm hành động:
1. Liệt kê chart và metadata.
2. Lấy cấu hình chart đã lưu (`form_data`, `params`, `query_context` tùy response).
3. Lấy dữ liệu chart.
4. Sinh cấu hình chart/Explore link để xem trước.
5. Tạo/lưu chart hoặc thêm vào dashboard (thao tác ghi, **không được phép trong agent read-only hiện tại**).

Không tuyên bố đã tạo/lưu chart chỉ vì có `superset_form_data` hoặc URL Explore.

## 2. Các endpoint chính thức (đối chiếu ở runtime)

| Method | Endpoint | Ý nghĩa | Agent hiện tại |
|---|---|---|---|
| GET | `/api/v1/chart/` | Danh sách chart | Chỉ dùng nếu backend tool được cấp quyền |
| GET | `/api/v1/chart/{id_or_uuid}` | Chi tiết chart | Chỉ dùng nếu backend tool được cấp quyền |
| GET | `/api/v1/chart/{pk}/data/` | Dữ liệu từ query context đã lưu | Chỉ dùng nếu backend tool được cấp quyền |
| POST | `/api/v1/chart/data` | Chạy chart query context | Có thể được bao bởi tool truy vấn có kiểm soát |
| GET | `/api/v1/chart/_info` | Metadata API resource | Chỉ dùng nếu backend tool được cấp quyền |
| POST | `/api/v1/chart/` | Tạo chart | **Cấm ở chế độ read-only** |
| PUT | `/api/v1/chart/{pk}` | Sửa chart | **Cấm ở chế độ read-only** |

Tài liệu: https://superset.apache.org/developer-docs/6.1.0/api/charts/

Tài liệu của **instance đang chạy**: `https://<superset-host>/swagger/v1` (nếu được bật). Việc cung cấp URL trong tài liệu không có nghĩa agent hiện tại có browser hoặc HTTP-fetch tool.

## 3. Quy trình đọc chart có sẵn

1. Gọi `get_chart_catalog()` để lấy chart `id`, tên, metrics và dimensions **trong dashboard hiện tại**.
2. Chọn `chart_id` phù hợp; **phải kiểm tra chart thực sự thuộc dashboard hiện tại và dataset liên kết thuộc `allowed_dataset_ids`** trước khi gọi API chi tiết.
3. Nếu có tool đọc Chart API, gọi `GET /api/v1/chart/{id}` rồi kiểm tra response thành công và đọc các trường được trả về. Không giả định mọi response đều chứa `form_data` hoàn chỉnh.
4. `params` hoặc `query_context` có thể là JSON được lưu dưới dạng chuỗi; parse có kiểm tra lỗi. Không coi chuỗi chưa parse là object.
5. Đọc `viz_type`, datasource/dataset ID, metrics, dimensions, thời gian, bộ lọc, sắp xếp và cấu hình trục từ response; **không tự đoán** tham số thiếu.
6. Nếu cần dữ liệu chart, dùng endpoint dữ liệu được backend cho phép và có xác thực, kiểm tra scope/filter, row limit và tính đầy đủ của kết quả.
7. Trả kết quả đúng mức hoàn thành: thông tin/chart đã lưu, dữ liệu, cấu hình xem trước hay chart thực sự đã tạo.

### Quy tắc về `form_data`

- `form_data` là cấu hình visualization/Explore; **không** đồng nghĩa với data response.
- `query_context` định nghĩa truy vấn; có thể khác với `params`/`form_data` và cần đối chiếu theo phiên bản.
- `viz_type` quyết định các trường cấu hình khả dụng. Không sử dụng một payload chung cho mọi loại chart.
- Cấu hình của chart mẫu là **tham khảo**, không chứng minh rằng payload sẽ hợp lệ trong chart/dataset khác.
- `GET /api/v1/chart/{pk}/data/` sử dụng query context được lưu. Một số phiên bản hỗ trợ `filters_dashboard_id` để áp dụng default filter của dashboard; không được giả định điều này tái hiện mọi tương tác filter hiện tại của người dùng.

## 4. Chọn chart theo yêu cầu

- Xu hướng thời gian: line/area (xác minh `viz_type` thực tế được instance hỗ trợ).
- So sánh nhóm: bar/column.
- Một giá trị tổng hợp: big number/KPI.
- Cơ cấu: pie/donut khi có ý nghĩa.
- Bản ghi chi tiết: table.

Không tự đặt `viz_type` theo tên ví dụ ở tài liệu này; kiểm tra instance, schema plugin và cấu hình chart có sẵn. Khi chưa có tool tạo chart, chỉ có thể hướng dẫn hoặc trả cấu hình/preview ở mức khả năng thực tế của backend.

## 5. Dùng Chart API làm nguồn tài liệu động

Khi cần biết field hay payload cụ thể:
1. Đọc `/swagger/v1` hoặc OpenAPI spec của **đúng instance** qua một **backend tool HTTP allowlist** (nếu được triển khai).
2. Ưu tiên endpoint resource `GET /api/v1/chart/_info` để tìm metadata được hỗ trợ (nếu response thực tế cung cấp).
3. Đọc một chart mẫu *được phép truy cập* cùng `viz_type` bằng `GET /api/v1/chart/{id}` để tham khảo config thực tế.
4. Xác thực các field trước khi gửi yêu cầu tạo chart hoặc chạy query.
5. Cache schema theo instance + phiên bản với TTL; không tải lại OpenAPI trong mọi lượt chat.

**Không** cho LLM truy cập URL tùy ý. Backend phải cố định host Superset, allowlist path, timeout, giới hạn response, kiểm soát phiên đăng nhập và quyền của người dùng.

## 6. Phạm vi quyền và bảo mật

- Chỉ dùng chart thuộc dashboard hiện tại; kiểm tra quyền chart **và** dataset tương ứng.
- `allowed_dataset_ids` phải đến từ backend đáng tin cậy; không lấy từ prompt do người dùng nhập.
- API/chart có thể áp dụng row-level security và quyền truy cập theo user. Không dùng token admin chung để lách quyền.
- Mặc định read-only: không gọi POST tạo chart, PUT sửa chart, DELETE hoặc API thay đổi dashboard.
- Không lộ raw data ngoài chính sách của hệ thống. Nếu policy chỉ cho metadata, chỉ trả metadata; không gọi các endpoint chart data.
- Không giả định truy vấn thành công đồng nghĩa biểu đồ đã được render ở frontend.

## 7. Kiến trúc của project hiện tại

Các tool đã có:
- `get_chart_catalog`: chỉ liệt kê ID/tên/mô tả/metrics/dimensions, chưa lấy toàn bộ config.
- `get_dataset_catalog`, `get_column_catalog`, `get_metric_catalog`: xác thực metadata.
- `query_dataset`: structured query, trả kết quả cùng `superset_form_data` gợi ý; **không tạo/lưu chart**.
- `get_tool_documentation`: chỉ đọc Markdown đóng gói, **không vào website**.

Các tool cần bổ sung nếu muốn API-driven thực sự:
- `get_chart_details(chart_id)`: xác thực scope rồi đọc chart detail API, trả config đã chuẩn hóa.
- `get_superset_chart_api_schema(...)`: chỉ đọc OpenAPI/_info từ same-origin allowlist và cache, không fetch URL bất kỳ.
- `get_chart_data(chart_id, ...)`: chỉ khi chính sách cho phép truy vấn dữ liệu qua chart API; áp dụng quyền và giới hạn.
- Tool tạo chart riêng **chỉ sau khi** thay đổi rõ ràng read-only guardrail và có xác nhận/ủy quyền phù hợp.

Đọc file Markdown này **không tự đăng ký** các tool trên; phải triển khai backend tool rồi thêm vào `create_agent(tools=[...])`.

## 8. Các tình huống tham khảo

**“Dashboard có những biểu đồ nào?”** → `get_chart_catalog()` là đủ; không cần truy vấn dữ liệu.

**“Biểu đồ số 12 đang dùng trục X gì?”** → kiểm tra chart 12 thuộc dashboard và dataset cho phép; cần `get_chart_details(12)`; nếu chưa có tool này, nói rõ chưa đọc được form_data đầy đủ.

**“Vẽ chart đường nhiệt độ Hà Nội trong 24 giờ gần nhất”** → xác thực dataset/cột, truy vấn dữ liệu, tạo cấu hình line chart theo schema được xác thực. Nếu chỉ có `query_dataset` và URL Explore thì trình bày đó là **preview**, chưa phải saved chart.

**“Lấy số liệu từ chart hiện có”** → không dùng metadata catalog để suy ra số liệu; cần data tool hợp lệ. Nếu chính sách agent không được đọc raw data, không thực hiện bước này.

## 9. Kiểm tra kết quả trước khi trả lời

- Chart/dataset có thuộc phạm vi hiện tại không?
- `viz_type` và các field có được API/schema trả về hoặc xác nhận không?
- Thời gian, timezone, native dashboard filters có được áp dụng đúng không?
- Dữ liệu có lỗi, rỗng, phân trang hay truncated không?
- Kết quả hiện tại là chart đã lưu, preview, form_data hay dữ liệu thuần?
- Công cụ có thực sự xác nhận thành công thao tác cuối không?

## 10. Nguồn tài liệu

- Superset 6.1.0 Chart REST API: https://superset.apache.org/developer-docs/6.1.0/api/charts/
- Chart list: https://superset.apache.org/developer-docs/api/get-a-list-of-charts/
- Chart data for saved chart: https://superset.apache.org/developer-docs/api/return-payload-data-response-for-a-chart/
- Swagger của instance: `/swagger/v1` (nếu được bật).