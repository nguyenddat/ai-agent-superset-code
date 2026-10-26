# Đặc tả: Grain và ngữ nghĩa thời gian có cấu trúc

Trạng thái: **đã duyệt** · Bước 1 đã làm (commit `a6f9f93`). Bước 3 và 4 được thay bằng
[schema-link.md](schema-link.md) (26/10/2026): truy vấn sẽ do module schema link của AI Agent sinh SQL trên base table,
không còn đi qua `time_grain` của ChartData. Bước 2 được gộp vào `/schema-graph` của đặc tả đó. · Ngày: 26/10/2026 · Phạm vi: Semantic Layer (mô hình dữ liệu) và AI Agent

## 1. Vấn đề

Semantic Layer chưa biết một dòng dữ liệu đại diện cho khoảng thời gian nào, nên AI Agent phải đoán. Hệ quả đã
gặp ngày 26/10/2026:

- Câu "vẽ linechart so sánh 2 thành phố tại các giờ" lọc `thoi_diem_quan_sat <= '2026-10-25'` trên cột `TIMESTAMP`,
  chỉ giữ được dòng 00:00. Agent trả lời sai rằng "chỉ có số liệu theo ngày".
- Mốc 00:00 của chuỗi theo giờ bị rút thành ngày, làm trục X lẫn định dạng.

Hai lỗi đã được vá ở AI Agent (commit `5dfc9cd`). Cách vá là dò chữ "TIMESTAMP" trong kiểu cột và kiểm tra mọi giá
trị có rơi vào 00:00 không. Đó là đoán, không phải khai báo. Các lỗi cùng loại vẫn còn:

| Câu hỏi | Điều đang xảy ra |
| --- | --- |
| "Nhiệt độ trung bình theo ngày tuần này" | Nhóm theo `thoi_diem_quan_sat` ra 168 dòng theo giờ, vì truy vấn không gom theo ngày. |
| "Tổng lượng mưa theo giờ hôm qua" | Metric chỉ tính dòng `DU_BAO_NGAY`, nên chỉ có giá trị ở mốc 00:00, 23 mốc còn lại trống. Agent không biết là không trả lời được theo giờ. |
| "Nhiệt độ hiện tại" | Dòng `HIEN_TAI` có thời điểm lẻ (09:45, 14:00…), không có gì mô tả điều này. |

### Dữ liệu thực tế của `fact_tong_hop_thoi_tiet` (dataset 12)

| `loai_quan_sat` | Số dòng | Thời điểm | Grain thực tế |
| --- | --- | --- | --- |
| `DU_BAO_GIO` | 5.184 | 15/10–01/11, mỗi giờ | giờ |
| `DU_BAO_NGAY` | 216 | 15/10–01/11, luôn 00:00 | ngày |
| `HIEN_TAI` | 132 | 22/10–26/10, giờ lẻ | thời điểm (không đều) |

Mỗi metric của dataset này gắn với đúng một loại dòng qua `CASE WHEN loai_quan_sat = ...`:
`nhiet_do_trung_binh` và `do_am_trung_binh` dùng `DU_BAO_GIO`. `nhiet_do_cao_nhat`, `nhiet_do_thap_nhat`,
`tong_luong_mua`, `so_ngay_co_mua`, `ty_le_ngay_co_mua` và `toc_do_gio_toi_da` dùng `DU_BAO_NGAY`. Như vậy grain phải
khai báo được tới từng loại dòng, và từ đó suy ra grain của từng metric.

Hiện `text_to_bi_dataset_dictionary.grain` là ô chữ tự do. Dataset 12 đang để trống ô này. Catalog `/semantic-catalog`
không gửi ô này cho agent, và truy vấn metric không có cách gom theo đơn vị thời gian.

## 2. Mục tiêu và ngoài phạm vi

**Mục tiêu**

1. Quản trị viên khai báo được, cho mỗi dataset: cột thời gian chính, cột phân loại dòng (nếu có), và grain của từng
   loại dòng.
2. Mỗi cột thời gian có kiểu ngữ nghĩa rõ ràng: `date` (chỉ ngày) hoặc `timestamp` (có giờ).
3. Mỗi metric có grain gốc, suy ra từ loại dòng nó dùng.
4. Truy vấn metric gom được theo giờ, ngày, tuần, tháng (time grain), và chỉ cho phép gom thô hơn hoặc bằng grain gốc.
5. Bộ lọc theo ngày trên cột `timestamp` luôn phủ trọn ngày. Việc này được xử lý ở Semantic Layer, không phải mỗi
   client tự xử lý.
6. AI Agent dùng các khai báo này thay cho việc đoán, và nói rõ khi câu hỏi mịn hơn grain của dữ liệu.

**Ngoài phạm vi** (để đặc tả sau)

- Quan hệ, khoá và join giữa các dataset.
- Duyệt và lịch sử phiên bản cho mọi thay đổi mô hình. Ở đây chỉ nêu tác động lên metric contract (mục 4.4).
- Chuyển múi giờ. Dữ liệu được nạp theo `Asia/Bangkok` (UTC+7, trùng giờ Việt Nam) và lưu dạng không múi giờ. Hệ
  thống đọc giờ đúng như được ghi, kể cả khi Superset gắn nhãn `GMT`.

## 3. Khái niệm

- **Grain**: khoảng thời gian một dòng đại diện. Thang đo, từ mịn đến thô: `instant` (thời điểm không đều) < `hour` <
  `day` < `week` < `month` < `quarter` < `year`.
- **Cột phân loại dòng**: cột mà giá trị của nó tách các dòng có grain khác nhau trong cùng một bảng. Ví dụ
  `loai_quan_sat`.
- **Grain gốc của metric**: grain của loại dòng mà metric tính trên đó.
- **Time grain của truy vấn**: đơn vị gom nhóm khi metric được chia theo cột thời gian.

## 4. Thiết kế

### 4.1 Lưu trữ (metadata database của Superset)

Thêm vào `text_to_bi_dataset_dictionary`. Các cột mới đều cho phép rỗng và được thêm bằng `ALTER TABLE` theo cách
`catalog/route.py` đang làm cho `grain`, `layer_id`:

| Cột | Kiểu | Ý nghĩa |
| --- | --- | --- |
| `time_column` | `VARCHAR(255)` | Cột thời gian chính, ví dụ `thoi_diem_quan_sat`. |
| `row_kind_column` | `VARCHAR(255)` | Cột phân loại dòng, ví dụ `loai_quan_sat`. Rỗng khi cả bảng chung một grain. |

Bảng mới `text_to_bi_dataset_grain`, mỗi dòng là một loại dòng:

| Cột | Kiểu | Ý nghĩa |
| --- | --- | --- |
| `id` | `INTEGER` PK | |
| `dataset_id` | `INTEGER` FK → `text_to_bi_dataset_dictionary.id`, `ON DELETE CASCADE` | |
| `row_kind_value` | `VARCHAR(255)` rỗng được | Giá trị của cột phân loại, ví dụ `DU_BAO_GIO`. Rỗng khi dataset không có cột phân loại. |
| `label` | `VARCHAR(255)` | Tên nghiệp vụ, ví dụ "Dự báo theo giờ". |
| `grain` | `VARCHAR(16)` | Một giá trị trong thang ở mục 3. |

Ràng buộc: `UNIQUE (dataset_id, row_kind_value)`.

Thêm vào `text_to_bi_column_dictionary`: cột `temporal_kind VARCHAR(16)` (`date` | `timestamp` | rỗng). Khi khởi
tạo, giá trị được điền từ kiểu cột: `DATE` → `date`, kiểu chứa `TIMESTAMP`/`DATETIME` → `timestamp`. Quản trị viên
sửa được.

Ô `grain` chữ tự do vẫn giữ, đổi nhãn thành "Mô tả grain", dùng cho người đọc và cho AI AutoFill.

Ví dụ khai báo cho dataset 12:

```text
time_column     = thoi_diem_quan_sat
row_kind_column = loai_quan_sat
text_to_bi_dataset_grain:
  DU_BAO_GIO   "Dự báo theo giờ"   hour
  DU_BAO_NGAY  "Dự báo theo ngày"  day
  HIEN_TAI     "Quan sát hiện tại" instant
```

### 4.2 Gợi ý tự động (chỉ đọc, quản trị viên bấm mới chạy)

Nút "Phát hiện grain" trong từ điển dataset chạy một truy vấn tổng hợp qua ChartData, có `row_limit` và timeout.
Với mỗi giá trị của cột phân loại (tối đa 20 giá trị, theo `MAX_CODED_VALUES` đã có), truy vấn lấy:

- số dòng, mốc nhỏ nhất và lớn nhất;
- tất cả mốc có rơi vào 00:00 không;
- tất cả mốc có tròn giờ không;
- số mốc khác nhau trên mỗi đơn vị khoá (ví dụ mỗi thành phố mỗi ngày).

Từ đó gợi ý `hour`, `day` hoặc `instant`. Gợi ý chỉ điền vào form, chỉ có hiệu lực khi quản trị viên lưu.

Gợi ý cột phân loại: cột chữ có ít giá trị khác nhau và xuất hiện trong `CASE WHEN` của các metric của dataset
(lấy từ `metric_columns.py`, phần vai trò cột lọc).

### 4.3 Grain gốc của metric

Grain gốc được suy ra khi xây catalog, không lưu riêng:

1. Đọc điều kiện trong `CASE WHEN` của metric. Văn phạm contract hiện có (`contracts.py`) đã giới hạn ở một
   `CASE WHEN col op const`, và `metric_columns.py` đã tách được vai trò cột lọc.
2. Nếu điều kiện là `row_kind_column = 'X'` thì grain gốc là grain của loại dòng `X`.
3. Nếu dataset không có cột phân loại thì dùng grain của dòng có `row_kind_value` rỗng.
4. Nếu metric không lọc theo loại dòng mà dataset lại có nhiều loại dòng, grain gốc là `mixed`. Catalog cảnh báo ở
   màn hình metric: metric đang cộng lẫn nhiều grain, ví dụ `count` = `COUNT(*)` của dataset 12.

Với `ty_le_ngay_co_mua` (biểu thức có `100.0 * COUNT(...) / NULLIF(COUNT(...))`, ngoài văn phạm contract), grain gốc
lấy theo loại dòng chung của mọi `CASE WHEN` trong biểu thức. Nếu không xác định được thì là `mixed`.

### 4.4 Tác động lên metric contract

Dấu vân tay của metric contract (`metric_contract_hash`) thêm grain gốc. Khi quản trị viên đổi grain của một loại
dòng, các contract đã duyệt của metric dùng loại dòng đó chuyển sang `outdated` và cần duyệt lại. Lý do: con số "theo
giờ" hay "theo ngày" là một phần nghĩa của metric.

### 4.5 Catalog gửi cho AI Agent (`/semantic-catalog`)

Mỗi dataset thêm khối `time`:

```json
"time": {
  "column": "thoi_diem_quan_sat",
  "row_kind_column": "loai_quan_sat",
  "row_kinds": [
    {"value": "DU_BAO_GIO", "label": "Dự báo theo giờ", "grain": "hour"},
    {"value": "DU_BAO_NGAY", "label": "Dự báo theo ngày", "grain": "day"},
    {"value": "HIEN_TAI", "label": "Quan sát hiện tại", "grain": "instant"}
  ]
}
```

Mỗi cột thêm `temporal_kind`. Mỗi metric thêm `native_grain` và `row_kind`. `time_ranges` của
`/dimension-members` tính riêng cho từng loại dòng, vì `HIEN_TAI` chỉ có từ 22/10 trong khi dự báo có từ 15/10.

### 4.6 Thực thi truy vấn metric

Body của endpoint thực thi nhận thêm một khoá, là khoá duy nhất được thêm vào danh sách cho phép:

```json
{"dimensions": ["thoi_diem_quan_sat", "thanh_pho_key"], "filters": [...], "time_grain": "day"}
```

`build_metric_chart_payload` kiểm tra:

- `time_grain` thuộc `hour|day|week|month|quarter|year`;
- có đúng một dimension là cột `temporal_kind` khác rỗng;
- `time_grain` thô hơn hoặc bằng `native_grain` của metric. Nếu không, trả lỗi 400 kèm grain mịn nhất cho phép.

Dimension thời gian được chuyển thành cột `BASE_AXIS` có `timeGrain` (`PT1H`, `P1D`, `P1W`, `P1M`, `P3M`, `P1Y`)
theo payload ChartData của Superset 6.1. Cách viết này cần xác nhận bằng `scripts/compat.py` trên container trước khi
chốt. Tuần bắt đầu từ thứ Hai, theo cách Superset gom `P1W` trên PostgreSQL.

Bộ lọc theo ngày trên cột `temporal_kind = timestamp` được mở thành trọn ngày ngay tại đây, theo cùng quy tắc AI Agent
đang dùng: `<= d` thành `< d+1`, `== d` thành `>= d` và `< d+1`, `> d` thành `>= d+1`. Sau đó gỡ phần xử lý này
khỏi `ai-agents/.../chat/query.py`.

Kết quả trả về gắn kèm `time_grain` đã dùng, để giao diện định dạng trục X: `hour` → `HH:mm`, `day` → `dd/mm`,
`week` → "Tuần dd/mm", `month` → `mm/yyyy`.

### 4.7 AI Agent

- Prompt `understand_question` nhận khối `time` và `native_grain`. Kế hoạch truy vấn thêm trường `time_grain` khi câu
  hỏi chia theo thời gian ("theo giờ", "từng ngày", "theo tuần").
- `plan_query` kiểm tra `time_grain` so với `native_grain` trước khi gọi Semantic Layer. Khi câu hỏi mịn hơn dữ liệu,
  câu trả lời nói rõ, ví dụ: "Lượng mưa chỉ có theo ngày, nên tôi trả lời theo ngày." Agent không trả về chuỗi theo
  giờ toàn ô trống.
- Gỡ phần dò `TIMESTAMP_TYPES` và `_days_when_daily`. Việc định dạng mốc thời gian dựa trên `time_grain` của kết quả.
- Bỏ `CASE WHEN loai_quan_sat` khỏi phần giải thích tiêu chí trong câu trả lời: nói "theo dữ liệu dự báo theo giờ"
  bằng `label` của loại dòng.

### 4.8 Giao diện quản trị (Semantic Layer → Từ điển dữ liệu)

Trong form dataset, thêm mục "Thời gian và grain":

- chọn cột thời gian chính (chỉ các cột có `temporal_kind`);
- chọn cột phân loại dòng (không bắt buộc);
- bảng các loại dòng, mỗi dòng có giá trị, nhãn và grain. Giá trị lấy từ `dimension-members` của cột phân loại;
- nút "Phát hiện grain" (mục 4.2), hiện số liệu đã dùng để gợi ý.

Trong bảng cột, thêm cột "Kiểu thời gian" (`Ngày` / `Ngày giờ` / trống) cho các cột thời gian. Trong màn hình metric,
hiện grain gốc và cảnh báo `mixed`.

## 5. Kiểm thử và tiêu chí nghiệm thu

**Unit test (pytest, chạy local)**

- Suy ra grain gốc cho cả 9 metric của dataset 12. `count` phải là `mixed`.
- `build_metric_chart_payload`:
  - nhận `time_grain` hợp lệ;
  - từ chối khi mịn hơn grain gốc;
  - từ chối khi không có dimension thời gian;
  - mở bộ lọc ngày trên cột `timestamp`, giữ nguyên bộ lọc trên cột `date`.
- Đổi grain một loại dòng thì contract đã duyệt của metric liên quan thành `outdated`.

**Trên container (`compat.py`, `smoke.py`, hỏi thử trên `/ai-agent/`)**

| Câu hỏi | Kết quả mong đợi |
| --- | --- |
| "Nhiệt độ Hà Nội theo giờ hôm qua" | 24 điểm, 00:00–23:00. Trung bình khớp 28,76 °C. |
| "So sánh nhiệt độ Hà Nội và Huế theo giờ hôm qua" | 2 × 24 điểm. |
| "Nhiệt độ trung bình theo ngày tuần này" | Một điểm mỗi ngày, mỗi điểm là trung bình các giờ của ngày đó. |
| "Tổng lượng mưa theo giờ hôm qua" | Trả lời theo ngày, nói rõ dữ liệu mưa chỉ có theo ngày. |
| "Nhiệt độ cao nhất hôm qua" | Lọc trọn ngày 25/10 trên cột `timestamp`. |
| "Lượng mưa theo tháng" | Gom theo tháng. Ghi chú phần tháng chỉ có dữ liệu một phần (`coverage.partial`). |

## 6. Các bước triển khai

1. **Lưu trữ và giao diện quản trị:** mục 4.1, 4.2, 4.8. Agent chưa đổi gì. Khai báo dataset 12 như ví dụ ở 4.1.
2. **Catalog và grain gốc của metric:** mục 4.3, 4.4, 4.5.
3. **Thực thi `time_grain` và bộ lọc trọn ngày ở Semantic Layer:** mục 4.6. Xác nhận payload `BASE_AXIS` bằng
   `compat.py`.
4. **AI Agent dùng khai báo, gỡ phần đoán:** mục 4.7.
5. **Kiểm thử nghiệm thu:** mục 5. Cập nhật `AGENTS.md` của hai extension.

Mỗi bước build và ship được riêng. Bước 1 và 2 không làm đổi câu trả lời của agent.

## 7. Quyết định (duyệt 26/10/2026)

1. Đổi grain buộc duyệt lại metric contract của các metric liên quan (mục 4.4).
2. Tuần bắt đầu từ thứ Hai, theo mặc định của Superset trên PostgreSQL. Không thêm cấu hình.
3. Dòng `instant` (như `HIEN_TAI`) được gom theo giờ hoặc thô hơn. Không vẽ từng thời điểm lẻ.
4. Các dataset `dim_*` đang được gắn `dataset_type = aggregate` không sửa trong đợt này, vì không thuộc phạm vi grain.
