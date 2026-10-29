# Hành vi chung của API

Mô tả cách backend Semantic Layer trả lỗi, giữ transaction và kiểm tra quyền. Mọi route mới theo đúng các quy tắc này để
client nhận cùng một kiểu phản hồi ở mọi nơi.

## Exception

`common/exceptions/` giữ các lớp lỗi gốc. Chúng là lớp trừu tượng (khởi tạo trực tiếp sẽ ném `TypeError`); mỗi lớp
mang `status` và `message` mặc định:

| Lớp gốc | Status | Dùng khi |
| --- | --- | --- |
| `ValidationError` | 400 | Dữ liệu gửi lên phạm quy tắc; cũng là `ValueError` |
| `NotAuthorizedError` | 403 | Thiếu vai trò hoặc quyền Superset |
| `SelfApprovalError` | 403 | Người soạn tự duyệt khi cần người duyệt thứ hai |
| `NotFoundError` | 404 | Bản ghi được nêu không tồn tại |
| `ConflictError` | 409 | Xung đột trạng thái: revision đã đổi, đã có contract được duyệt |
| `TooManyRequestsError` | 429 | Vượt giới hạn số mục đang chờ duyệt |
| `ServiceUnavailableError` | 503 | Dịch vụ ngoài (OpenRouter) chưa sẵn sàng |

Quy tắc:

- Mỗi module khai báo lỗi của nó trong `modules/<module>/exceptions.py`, kế thừa lớp gốc và đặt `message` mặc định.
  Lỗi của các kiểm tra dùng chung nằm trong `core/exceptions.py`; lỗi không thấy dataset, database nằm trong
  `modules/superset/exceptions.py`.
- Service và route `raise` lỗi của module; không `return self.response(4xx, …)` và không ném `ValueError` /
  `PermissionError` trần.
- Thông điệp lỗi là văn bản an toàn để hiện cho người dùng, không chứa SQL, stack trace hay chi tiết nội bộ. Thông điệp
  mới viết bằng tiếng Việt; thông điệp cũ giữ nguyên chữ vì client và test có thể so khớp.
- Lỗi do thư viện ném ra (ví dụ `IntegrityError` của SQLAlchemy) được bắt ở nơi biết nghĩa nghiệp vụ của nó và chuyển
  thành lỗi của module (`ExpertRuleValidationError("Could not save the expert rule.")`).

## Thứ tự decorator của route

```python
@expose("/glossary/<int:term_id>/approve", methods=("POST",))
@protect()
@safe
@permission_name("write")
@csrf_protected        # chỉ route thay đổi dữ liệu
@rollback_on_error     # chỉ route thay đổi dữ liệu
@handle_errors         # luôn nằm sát hàm
def approve_glossary(self, term_id: int):
    ...
```

- `handle_errors` (`core/database.py`) bắt `SemanticLayerError`, rollback session và trả `status` cùng `message` của
  lỗi. Nó phải nằm trong cùng, sát `def`: `@safe` của Superset và `rollback_on_error` biến mọi exception thành 500.
- `rollback_on_error` bắt lỗi ngoài dự kiến, ghi log, rollback và trả 500 "Could not save the change.", không lộ chi
  tiết lỗi.
- Route chỉ đọc (GET) không cần `csrf_protected` và `rollback_on_error`, nhưng vẫn có `handle_errors`.

## Transaction

- Route sở hữu transaction: nó gọi `db.session.commit()` một lần khi mọi bước đã xong. Service và repository không
  commit. Ngoại lệ duy nhất là `seed_dictionary`, tự commit để không để transaction mở cho phần tiếp theo.
- `BaseRepository.add()` và `update()` flush ngay để có ID và để lỗi ràng buộc lộ sớm. Vì vậy `IntegrityError` có thể
  xuất hiện trong lúc service chạy, không chỉ lúc commit: khối `try` bắt nó phải bao cả lời gọi service lẫn commit.
- Khi một lỗi được trả về, session đã được rollback; không có thay đổi dở dang nào được lưu.

## Quyền và CSRF

- Route quản trị gọi `require_admin()` ở đầu hàm; nó ném `AdminRequiredError` (403 "Admin access required.").
- Route đọc dữ liệu của một dataset gọi `require_dataset(...)` rồi `require_dataset_access(dataset)` để Superset kiểm
  tra quyền đọc; thiếu quyền là 403 "Dataset and database access required.".
- Mọi route thay đổi dữ liệu dùng chung `csrf_protected` của `core/security.py`; token sai trả 403
  "CSRF token không hợp lệ." cho mọi API, kể cả `ExpertRuleAPI`.
- Duyệt thuật ngữ, rule và metric: khi `TEXT_TO_BI_REQUIRE_SECOND_REVIEWER = True` trong `superset_config`, người soạn
  không được tự duyệt (`SelfApprovalError`, 403). Mặc định tắt để một quản trị viên tự duyệt được.

## Bảng và migration

- Route đầu tiên đụng tới bảng của extension gọi `ensure_dictionary_tables()` (`migrations.py`). Hàm tạo và nâng cấp
  bảng một lần cho mỗi process, giữ PostgreSQL advisory lock để các worker không chạy song song, và không thử lại
  trong 30 giây sau một lần lỗi.
- `ExpertRuleAPI` không chạy DDL; bảng của nó được tạo trong cùng migration đó.
