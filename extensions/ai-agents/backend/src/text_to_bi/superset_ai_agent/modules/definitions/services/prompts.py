from ...chat.services.prompts import DATA_NOTICE

STRUCTURE_DEFINITION = f"""Người dùng vừa xác nhận cách hiểu của họ về một khái niệm định tính (ví dụ "ngày gió mạnh").
Chuyển cách hiểu đó thành điều kiện lọc trên đúng một dataset để mọi câu hỏi sau dùng cùng một ngưỡng.

`dataset_id`: dataset có cột để biểu diễn điều kiện. `filters`: mỗi điều kiện có `column` (đúng tên cột có
`filterable`), `operator` (==, !=, <, <=, >, >=, IN, NOT IN) và `value` (số cho cột số, nhãn đổi thành giá trị khoá
theo `labelled_values`). Chỉ dùng ngưỡng có trong cách hiểu, không tự thêm mốc thời gian hay địa điểm. "Từ 45 km/h"
là >= 45; "trên 45" là > 45; "từ 50 đến dưới 100 mm" là >= 50 và < 100.
Nếu cách hiểu không thể viết thành điều kiện trên các cột này (cần phép tính, tỷ lệ, hay so với ngày khác) thì
`dataset_id` là null và `filters` rỗng. `reason`: một câu tiếng Việt.
{DATA_NOTICE}"""
