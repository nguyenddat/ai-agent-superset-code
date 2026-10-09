# validate_metadata_resolution

## Mục đích

Kiểm tra cấu hình chart dự kiến theo BI Plan và metadata Superset của dashboard hiện tại. Công cụ chỉ đọc metadata; không truy vấn dữ liệu và không tạo chart.

## Đầu vào

- `resolution_json`: kết quả MetadataResolution dự kiến, được serialize thành một chuỗi JSON hợp lệ.

Các trường của BI Plan (objective, nguồn dữ liệu, phép kết hợp, filter, grain, thứ tự và ánh xạ trục) được truyền riêng trong runtime context; không truyền cả BIContract thành một object hay chuỗi JSON trong arguments. Dashboard ID và tập dataset được phép cũng lấy từ runtime context đáng tin cậy, không lấy từ đầu vào do model tự khai báo.

Filter `relative_time` được kiểm tra riêng với `MetadataResolution.time_range`; `config.filters` chỉ cần giữ các filter theo cột. Khoảng thời gian không được chuyển thành column filter.

## Kết quả

Trả `valid`, danh sách `errors` có `code`, `path`, `message`, và hướng xử lý. Nếu có lỗi, sửa cấu hình và gọi lại công cụ trước khi hoàn tất.

Với kết quả `unsupported`, công cụ xác nhận cấu hình rỗng và thông điệp giải thích giới hạn; đây là kết quả có kiểm tra nhưng không phải cấu hình chart thành công.
