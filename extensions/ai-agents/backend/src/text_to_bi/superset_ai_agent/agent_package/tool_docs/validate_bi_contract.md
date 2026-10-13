# validate_bi_contract

## Mục đích

Kiểm tra một `BIContract` theo siêu dữ liệu của dashboard hiện tại và danh sách
`allowed_dataset_ids` trong ngữ cảnh chạy. Công cụ chỉ đọc metadata, không truy
vấn dữ liệu hàng, không tạo SQL và không thay đổi biểu đồ.

## Thời điểm sử dụng

Tác tử lập kế hoạch phải gọi công cụ với toàn bộ contract trước khi kết thúc.
Nếu kết quả có lỗi, hãy sửa contract theo lỗi và gọi lại công cụ.

## Tham số

- `contract`: BIContract cần kiểm tra. Không gửi thêm mã dashboard hoặc danh sách
  dataset được phép; công cụ lấy các giá trị này từ ngữ cảnh đáng tin cậy của ứng
  dụng.

## Kết quả

- `valid`: `true` khi mọi kiểm tra đều đạt.
- `errors`: danh sách lỗi, mỗi lỗi gồm `code`, `path` và `message` để định vị
  trường cần sửa.
- `message`: trạng thái tổng quát và hướng dẫn bước tiếp theo.

## Các kiểm tra chính

- Dataset tồn tại trong metadata dashboard và được phép dùng trong ngữ cảnh.
- Cột, metric, bộ lọc và phép tổng hợp phù hợp metadata.
- Số nguồn dữ liệu khớp với phương thức kết hợp; JOIN chỉ hợp lệ khi có quan hệ
  được xác minh.
- Loại biểu đồ phải được xác minh khi có khai báo; trường ánh xạ biểu đồ phải
  thuộc kết quả dự kiến.
- Hình dạng kết quả và mức dữ liệu phải nhất quán với kế hoạch truy vấn.

## Giới hạn

Instance hiện chưa cung cấp danh mục loại biểu đồ đáng tin cậy hoặc metadata quan
hệ giữa các dataset cho công cụ này. Vì vậy, không chọn `viz_type` chưa được xác
minh và không lập JOIN chỉ dựa trên tên cột trùng nhau.
