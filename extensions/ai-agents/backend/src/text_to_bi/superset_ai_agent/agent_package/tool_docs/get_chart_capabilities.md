# get_chart_capabilities

## Mục đích

Đọc schema XY chart và ánh xạ loại biểu đồ từ phiên bản Superset đang chạy. Kết
quả trả về các `viz_type` đã xác minh, kiểu biểu đồ tương ứng, vai trò trường và
schema cấu hình.

## Khi sử dụng

Gọi công cụ khi người dùng nêu rõ loại biểu đồ hoặc khi cần chọn biểu đồ cho
BIContract. Không dùng `get_chart_catalog` thay cho công cụ này vì danh mục chart
chỉ chứa các chart đã lưu trên dashboard.

## Kết quả

- `viz_types`: các ID Superset được ánh xạ từ schema chart XY của instance.
- `kinds_by_viz_type`: ánh xạ ID Superset sang kiểu biểu đồ trong schema.
- `field_roles`, `required_fields`, `schema`: vai trò và cấu hình trường.
- `available=false`: Superset không cung cấp được metadata; khi đó để
  `chart_resolve.viz_type` là null và giải thích hạn chế.

Ví dụ: nếu người dùng yêu cầu biểu đồ cột, chọn kiểu `bar` và dùng đúng
`viz_type` được trả về trong `kinds_by_viz_type`.

## Giới hạn

Công cụ khám phá các kiểu XY khai báo trong schema Superset; kết quả không phải
danh mục đầy đủ mọi loại biểu đồ.
