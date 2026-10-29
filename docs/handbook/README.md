# Handbook

Handbook ghi những gì cả nhóm đã thống nhất khi viết code trong repository này: quy ước code, kiến trúc backend và hành
vi chung của API. Người và agent viết code đều đọc nó trước khi sửa code; khi một quy ước đổi, sửa handbook trong cùng
commit với code.

| Tài liệu | Nội dung |
| --- | --- |
| [quy-uoc-code.md](quy-uoc-code.md) | Độ dài dòng, đặt tên, docstring và comment, test, commit message |
| [kien-truc.md](kien-truc.md) | Các lớp `common`, `core`, `modules`; module chia theo nghiệp vụ; cấu trúc một module |
| [hanh-vi.md](hanh-vi.md) | Exception và mã lỗi, thứ tự decorator của route, transaction, quyền và CSRF |

Đặc tả từng tính năng nằm ở [docs/specs/](../specs/); handbook chỉ ghi quy tắc dùng chung cho mọi tính năng.

## Phạm vi

- Quy ước code áp dụng cho toàn repository: Python và TypeScript của cả hai extension, script, DAG Airflow.
- Kiến trúc và hành vi mô tả backend Semantic Layer (`extensions/semantic-layer/backend`), là cấu trúc chuẩn. Backend
  AI Agent hiện có cấu trúc riêng (xem `extensions/ai-agents/AGENTS.md`); code mới ở đó theo quy ước code của
  handbook, và khi tái cấu trúc thì đi về cùng các lớp như Semantic Layer.
