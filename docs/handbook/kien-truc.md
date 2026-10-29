# Kiến trúc backend

Mô tả backend Semantic Layer: `extensions/semantic-layer/backend/src/text_to_bi/superset_semantic_layer/`.

## Các lớp

```text
entrypoint.py, migrations.py, modules/catalog   ← ghép ứng dụng: đăng ký API, tạo bảng
modules/<nghiệp vụ>                             ← models, repositories, services, routes của từng nghiệp vụ
core                                            ← hạ tầng dùng chung: cấu hình, bảo mật, xử lý lỗi của route
common                                          ← nền tảng thuần: BaseModel, BaseRepository, exception gốc, formatter
```

Mũi tên phụ thuộc chỉ đi xuống:

| Lớp | Được import | Không được import |
| --- | --- | --- |
| `common` | thư viện ngoài | `core`, `modules`, `migrations` |
| `core` | `common` | `modules`, `migrations` |
| `modules/<x>` | `common`, `core`, service / repository / model / exception của module khác | routes của module khác |
| `migrations.py`, `modules/catalog`, `entrypoint.py` | mọi thứ ở trên | — |

- `core/config.py`: lớp `Settings` đọc biến môi trường.
- `core/security.py`: quyền admin, quyền đọc dataset, CSRF, quy tắc người duyệt thứ hai.
- `core/database.py`: `handle_errors` và `rollback_on_error` (xem [hanh-vi.md](hanh-vi.md)).
- `core/exceptions.py`: lỗi của các kiểm tra dùng chung (admin, quyền dataset, CSRF, thân request).
- `migrations.py`: tạo và nâng cấp bảng của mọi module, một lần cho mỗi process (`ensure_dictionary_tables`). Nó nằm
  trên các module vì cần model của tất cả.

## Module chia theo nghiệp vụ

Một module là một nghiệp vụ, không phải một model hay một bảng. Một nghiệp vụ có thể có nhiều model; một model chỉ
thuộc một nghiệp vụ.

| Module | Nghiệp vụ |
| --- | --- |
| `data_dictionary` | Từ điển dataset và cột, grain, chỉ số, AI AutoFill (`autofill/`) |
| `business_model` | Tầng dữ liệu, nghiệp vụ, canvas và lineage |
| `glossary` | Thuật ngữ nghiệp vụ, vòng đời duyệt, khám phá thuật ngữ |
| `expert_rules` | Expert rule, vòng đời duyệt, khám phá rule (API riêng `ExpertRuleAPI`) |
| `semantic_query` | Metric contract, relationship contract, semantic catalog, biên dịch và chạy truy vấn |
| `agent_ladder` | Metric tạm tính và đề xuất dataset do AI Agent tạo |
| `superset` | Dataset, database và người dùng của Superset: chỉ đọc, không có bảng riêng |
| `catalog` | Ghép `SemanticLayerAPI` từ route mixin của các module và trang Semantic Layer |

Thêm tính năng: đặt vào module của nghiệp vụ đó. Chỉ tạo module mới khi có một nghiệp vụ mới, có ngôn ngữ và vòng đời
riêng. Không tạo module chỉ để chứa một model, một bảng hay một kiểu tiện ích.

Mọi truy vấn vào bảng của Superset (`SqlaTable`, `Database`, người dùng) đi qua module `superset`:
`modules/superset/services/datasets.py` (`get_dataset`, `require_dataset`, `datasets_on_database`, …) và
`services/users.py` (`active_users`, `user_names`). Không gọi `db.session.query(SqlaTable)` ở module khác. Truy vấn
join bảng của một module với bảng Superset (ví dụ dataset dictionary với `SqlaTable`) nằm trong repository của module đó.

## Cấu trúc một module

```text
modules/<module>/
├── models/          # bảng của module trong metadata database; __init__.py liệt kê __all__
├── repositories/    # một repository cho mỗi model, kế thừa BaseRepository: mọi truy vấn của module
├── dependencies.py  # hàm tạo repository gắn với db.session của request
├── exceptions.py    # lỗi của module, kế thừa common/exceptions
├── services/        # quy tắc nghiệp vụ và các hàm module khác gọi; không đọc request
└── routes/          # route mixin: đọc request, gọi service, trả response
```

- **Repository** là nơi duy nhất viết truy vấn. Service và route gọi repository qua `dependencies.py`.
- **Service** không đọc `request`. Cần dữ liệu từ request thì route đọc rồi truyền vào
  (`review_reason(request.get_json(silent=True))`).
- **Route mixin** chỉ gọi method của chính mixin đó qua `self`. Một helper mà mixin hay module khác cũng cần thì để thành
  hàm trong `services/` của module sở hữu nghiệp vụ, và nơi dùng import nó, ví dụ `metric_contract_for` trong
  `semantic_query/services/metric_review.py` hay `discoverable_glossary_terms` trong `glossary/services/discovery.py`.
  `SemanticLayerAPI` ghép các mixin, nhưng không mixin nào được dựa vào method của mixin khác.
- **Gọi giữa các module** đi qua service, repository factory, model hoặc exception của module kia, không đi qua route.

## Superset 6.1 và Python 3.10

- Code chạy trong image Superset 6.1, Python 3.10, SQLAlchemy 1.4. Không dùng cú pháp mới hơn Python 3.10.
- Import nặng của Superset chỉ cần khi chạy (ví dụ `ChartDataCommand`) thì import trong hàm, để test cục bộ vẫn import
  được module.
- Sau khi sửa backend, chạy `uv run scripts/compat.py` để biên dịch và import mọi module trong container.
