# Quy ước code

Áp dụng cho Python và TypeScript trong toàn repository.

## Độ dài dòng và xuống dòng

- Một dòng tối đa 120 ký tự. Ruff kiểm tra Python với giới hạn này (`pyproject.toml` ở gốc và ở mỗi
  `extensions/*/backend/`); frontend không có formatter nên tự giữ giới hạn.
- Chỉ xuống dòng khi vượt 120 ký tự. Lời gọi hàm, import, object, comprehension hay JSX element ngắn thì để trên một dòng.

```python
# Đúng
datasets = {dataset.id: dataset for dataset in get_datasets(dataset_ids)}

# Sai: vừa một dòng mà vẫn tách
datasets = {
    dataset.id: dataset
    for dataset in get_datasets(dataset_ids)
}
```

## Đặt tên

- Đặt tên theo nghĩa nghiệp vụ: `metric_contract`, `selected_dataset`, `approved_at`, `metricContract`.
- Không viết tắt (`ds`, `col`, `m`, `tmp`, `res`, `refs`). Tên một chữ cái chỉ dùng cho chỉ số vòng lặp ngắn.
- Hàm trả về đối tượng hoặc `None` đặt `get_…` / `…_for`; hàm ném lỗi khi không thấy đặt `require_…`
  (`require_dataset`, `require_admin`).
- Exception đặt tên theo điều đã xảy ra và kết thúc bằng `Error`: `MetricContractNotFoundError`,
  `GlossarySelfApprovalError`.

## Docstring và comment

- Không viết module docstring trong Python (Ruff `D100` được tắt có chủ đích). Riêng script trong `scripts/` giữ module
  docstring vì `argparse` dùng `__doc__` làm nội dung `--help`.
- Docstring của class và hàm viết khi tên chưa nói hết: hàm làm gì, khi nào trả `None`, ném lỗi gì. Không lặp lại tên.
- Comment giải thích *vì sao*, không thuật lại code.

## Code dùng chung

- Dùng lại hàm sẵn có thay vì viết lại: định dạng thời gian và JSON dùng `common/utils/type_formatter.py`
  (`iso_datetime`, `iso_date`, `compact_json`, …), không tự gọi `.isoformat()`.
- Không kiểm tra lại điều hàm được gọi đã xử lý; ví dụ `get_datasets([])` đã trả `[]`, nên không bọc thêm
  `if dataset_ids else`.

## Biến môi trường và bí mật

- Mỗi extension đọc biến môi trường dùng chung qua lớp `Settings` trong `core/config.py`; không gọi `os.getenv` trong
  module.
- Không đưa khóa API hay mật khẩu vào commit, bundle hay tài liệu. Giá trị thật chỉ nằm trong `.env` ở gốc repository.

## Test

- Chạy từ gốc repository: `uv run pytest extensions/semantic-layer/backend/tests`, `uv run ruff check`.
- Test backend chạy trên Python 3.12 với `superset` giả lập, nên không bắt được lỗi API Superset hay cú pháp Python
  3.10; chạy thêm `uv run scripts/compat.py` và `uv run scripts/smoke.py` khi stack đang chạy.
- Test route biên dịch method thật của route với các đối tượng giả qua `tests/catalog_source.py`. Khi thêm một file
  service mà route gọi trực tiếp, thêm đường dẫn của nó vào `SHARED_SERVICE_PATHS` để test tìm được hàm.
- Sửa một lỗi hành vi thì thêm test tái hiện lỗi đó.

## Commit message

Dùng [Conventional Commits](https://www.conventionalcommits.org/): `<type>(<scope>): <description>`.

- `type`: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `build`, `perf`, `style`, `ci`.
- `scope`: phần bị sửa, ví dụ `semantic-layer`, `ai-agent`, `simulation`, `scripts`, `docs`.
- `description`: tiếng Anh, thể mệnh lệnh, chữ thường ở đầu, không có dấu chấm cuối.
- Thân commit (nếu có) giải thích vì sao và những gì thay đổi về hành vi; thay đổi phá vỡ tương thích ghi
  `BREAKING CHANGE:` ở chân.

```text
fix(semantic-layer): answer an expert rule name collision with 400
refactor(semantic-layer): move Superset lookups into the superset module
docs(handbook): record the module layout and error handling
```
