# Đặc tả: Schema link trên base table

Trạng thái: **đã duyệt** · Ngày: 26/10/2026 · Phạm vi: Semantic Layer (cung cấp metadata) và AI Agent (module schema
link)

Đặc tả này thay cho bước 3 và 4 của [grain-va-ngu-nghia-thoi-gian.md](grain-va-ngu-nghia-thoi-gian.md). Phần grain đã
làm ở bước 1 vẫn giữ nguyên và là đầu vào của schema link.

## 1. Bối cảnh

Hiện nay AI Agent trả lời theo thứ tự sau:

1. Dùng metric đã duyệt trên aggregate dataset.
2. Nếu thiếu metric, tự dựng metric tạm tính trên một cột của aggregate dataset.
3. Nếu không có aggregate dataset nào đo được, soạn một virtual dataset để quản trị viên duyệt. Câu hỏi chưa được trả
   lời.

Bước 3 không mở rộng được: câu hỏi thì vô vàn, còn quản trị viên không thể duyệt hết. Schema link thay bước 3 bằng
việc tự trả lời trên base table:

1. **Xác định dữ liệu cần cho câu trả lời:** câu hỏi cần đo gì, chia theo gì, lọc theo gì.
2. **Xác định vị trí dữ liệu:** bảng và cột chứa từng thứ, và công thức tính.
3. **Tìm đường nối bảng bằng thuật toán đồ thị:** các phép join.
4. **Sinh SQL hoàn chỉnh**, kiểm tra, chạy và trả lời.

## 2. Quyết định đã chốt (26/10/2026)

1. Thuật toán tìm đường join nằm trong module schema link của **AI Agent**, chạy tự động cho mọi câu hỏi. Quản trị
   viên không duyệt từng câu. Quá trình linking được **hiển thị trên trang AI Agent**.
2. Chỉ **quan hệ đã duyệt** mới là cạnh của đồ thị. Quan hệ chỉ được gợi ý hoặc chỉ đánh dấu FK trong từ điển thì không
   được dùng.
3. Schema link chỉ chạy trên **base table**: dataset có `dataset_type = 'base'` và là bảng vật lý trong Superset
   (không có SQL). Virtual dataset không được dùng. Aggregate dataset (`dim_*`, `fact_*`) vẫn đi theo đường metric như
   hiện nay.

## 3. Hiện trạng metadata cho schema link

Base table của kho mẫu: `dm_thanh_pho`, `dm_ngay`, `dm_nguon_du_lieu`, `dm_dieu_kien_thoi_tiet`,
`dm_chi_so_thoi_tiet`, `tb_lan_nap_du_lieu`, `tb_quan_sat_thoi_tiet`, `tb_gia_tri_quan_sat`.

| Cần cho schema link | Hiện có | Thiếu |
| --- | --- | --- |
| Tên và nghĩa của bảng, cột | `display_name`, `description` (bảng), `business_term`, `unit`, giá trị mã của cột chữ ngắn | Mô tả cột, từ đồng nghĩa |
| Vai trò của cột | Cờ PK/FK/UQ, `temporal_kind` | Vai trò đo lường, chiều, nhãn; phép gộp hợp lệ |
| Chỉ số dạng key-value | Không có | `tb_gia_tri_quan_sat.gia_tri_so` chỉ có nghĩa khi biết `chi_so_id`; tên, đơn vị và cách tổng hợp nằm ở `dm_chi_so_thoi_tiet` |
| Grain | Bước 1: `time_column`, `row_kind_column`, grain từng loại dòng | Chưa khai báo cho base table |
| Cạnh của đồ thị | 6 FK đánh dấu trong từ điển, khớp FK thật của warehouse | **0 quan hệ đã duyệt.** `RelationshipContract` mới có backend, chưa có màn hình, chưa kiểm chứng bằng dữ liệu |

## 4. Thiết kế phía Semantic Layer: cung cấp metadata

### 4.1 Quan hệ có kiểm chứng (cạnh của đồ thị)

**Gợi ý từ nhiều nguồn.** Mỗi gợi ý ghi rõ nguồn của nó:

| Nguồn | Cách lấy | Ghi chú |
| --- | --- | --- |
| `database` | `get_foreign_keys` của SQLAlchemy inspector trên kết nối warehouse | Không phải lúc nào cũng có: view, bảng nạp bằng ETL, engine không ép FK, tài khoản không có quyền đọc catalog |
| `dictionary` | Cờ FK và cột tham chiếu đã khai báo trong từ điển | Như hiện nay |
| `naming` | Cột `*_id` hoặc `*_key` trùng tên và kiểu với PK hoặc cột duy nhất của một base table khác | Độ tin cậy thấp nhất |

**Kiểm chứng bằng dữ liệu**, do quản trị viên bấm "Kiểm tra". Hệ thống chạy hai truy vấn chỉ đọc trên warehouse, có
timeout và giới hạn mẫu:

- **Cột đích có duy nhất không:** `COUNT(*)` so với `COUNT(DISTINCT đích)`.
- **Tỉ lệ mồ côi:** phần trăm giá trị khác NULL của cột nguồn không có ở cột đích, kèm vài giá trị mẫu.
- **Kiểu dữ liệu hai đầu có khớp không.**
- **Bản số thực tế:** `many_to_one` hoặc `one_to_one`.

Kết quả lưu cùng contract. Kiểm chứng phải nối hai bảng, nên không chạy được qua ChartData của một dataset. Nó chạy
bằng engine của database trong Superset, chỉ cho quản trị viên.

**Duyệt** dùng `RelationshipContract` có sẵn (`candidate`, `approved`, `revoked`), thêm các trường:

- `source`;
- `verified_at`, `orphan_ratio`, `target_unique`;
- cặp cột nhiều phần cho khoá ghép. Ví dụ `tb_gia_tri_quan_sat` có PK `(quan_sat_id, chi_so_id)`.

> Đã làm ở bước 1 (26/10/2026): quan hệ **một cột**. Cả 6 FK của kho mẫu là một cột; khoá ghép của
> `tb_gia_tri_quan_sat` chỉ nằm ở phía nguồn, nên không cần cặp cột nhiều phần. Phần khoá ghép để lại tới khi có FK
> ghép thật. Kết quả kiểm chứng lưu thành JSON trong `verification`, chỉ có hiệu lực khi `verified_hash` bằng
> `contract_hash`; duyệt cần kiểm chứng đạt (đích duy nhất, kiểu khớp).

Contract chuyển `outdated` khi cấu trúc cột đổi, theo cơ chế dấu vân tay hiện có. Có thể bật `TEXT_TO_BI_REQUIRE_SECOND_REVIEWER` cho quan hệ như với metric.

**Giao diện:** tab "Quan hệ" trong Data Dictionary của base table. Tab liệt kê quan hệ ra và vào bảng, có nguồn, kết
quả kiểm chứng, trạng thái và các nút Kiểm tra, Duyệt, Thu hồi. Nút "Tìm quan hệ" gom gợi ý từ cả ba nguồn.

### 4.2 Vai trò cột

Thêm vào `text_to_bi_column_dictionary`:

| Trường | Giá trị | Dùng để |
| --- | --- | --- |
| `semantic_role` | `key`, `measure`, `dimension`, `label`, `time`, `row_kind`, `attribute` | Biết cột nào để đo, chia nhóm, hiển thị tên hay nối bảng |
| `aggregations` | Tập con của `SUM`, `AVG`, `MIN`, `MAX`, `COUNT`, `COUNT_DISTINCT` | Chặn phép gộp vô nghĩa, ví dụ `SUM` nhiệt độ |
| `synonyms` | Danh sách chuỗi | Định vị cột theo cách người hỏi nói |
| `description` | Chữ | Nghĩa của cột |

Khi khởi tạo, vai trò được điền theo cờ khoá, `temporal_kind`, cột phân loại dòng và kiểu số. AI AutoFill gợi ý mô
tả, từ đồng nghĩa và vai trò, đều chỉ có hiệu lực khi quản trị viên lưu.

### 4.3 Chỉ số dạng key-value

Khai báo ở cấp bảng, cho bảng lưu giá trị theo từng chỉ số:

```text
tb_gia_tri_quan_sat
  indicator_column  = chi_so_id            → dm_chi_so_thoi_tiet.chi_so_id (theo quan hệ đã duyệt)
  value_columns     = gia_tri_so (SO), gia_tri_dung_sai (DUNG_SAI), gia_tri_chu (CHU)
dm_chi_so_thoi_tiet
  indicator_code    = ma_chi_so
  indicator_name    = ten_chi_so
  indicator_unit    = ten_don_vi
  value_kind        = kieu_du_lieu
  aggregation       = cach_tong_hop        (TRUNG_BINH → AVG, TONG → SUM, NHO_NHAT → MIN, LON_NHAT → MAX)
```

Danh sách chỉ số (mã, tên, đơn vị, cách tổng hợp) được đọc từ bảng chỉ số qua ChartData như `dimension-members`. Nhờ
vậy "nhiệt độ" được định vị thành `gia_tri_so` với điều kiện `ma_chi_so = '…'` và phép gộp `AVG`, đúng như dữ liệu
tự mô tả.

### 4.4 Grain trên base table

Dùng lại bước 1, khai báo cho `tb_quan_sat_thoi_tiet`: cột thời gian `thoi_diem_quan_sat`, cột phân loại dòng
`loai_quan_sat`. Cho `dm_ngay`: grain ngày. Đồ thị dùng grain để cảnh báo nhân dòng và để buộc lọc một loại dòng khi
đo.

### 4.5 Endpoint `/schema-graph` cho AI Agent

Endpoint trả về đồ thị của một database, chỉ gồm:

- base table vật lý mà **người hỏi** được quyền xem (theo quyền datasource của Superset);
- quan hệ **đã duyệt và còn hiệu lực** giữa các bảng đó.

```json
{
  "database": {"id": 1, "dialect": "postgresql"},
  "tables": [{
    "dataset_id": 15, "schema": "public", "table": "tb_quan_sat_thoi_tiet", "label": "Quan sát thời tiết",
    "description": "…", "time": {"column": "thoi_diem_quan_sat", "row_kind_column": "loai_quan_sat",
    "row_kinds": [{"value": "DU_BAO_GIO", "grain": "hour"}]},
    "columns": [{"name": "loai_quan_sat", "label": "Loại quan sát", "type": "VARCHAR(30)",
      "role": "row_kind", "values": ["DU_BAO_GIO", "DU_BAO_NGAY", "HIEN_TAI"], "synonyms": []}],
    "indicators": null
  }],
  "edges": [{
    "id": 7, "from": {"dataset_id": 13, "columns": ["quan_sat_id"]},
    "to": {"dataset_id": 15, "columns": ["quan_sat_id"]}, "cardinality": "many_to_one"
  }]
}
```

Endpoint này chỉ mô tả dữ liệu, không chạy truy vấn nào. Nó được cache theo người dùng như catalog hiện nay.

## 5. Thiết kế phía AI Agent: module schema link

Module mới `modules/schema_link/`. Nó chạy khi không có metric hay aggregate dataset nào trả lời được câu hỏi, thay
cho việc soạn đề xuất dataset.

### 5.1 Linking: xác định dữ liệu và vị trí

1. **Lọc ứng viên không dùng model:** so khớp từ khoá của câu hỏi (đã bỏ dấu) với nhãn, từ đồng nghĩa, mô tả, giá trị
   mã và tên chỉ số. Kết quả là một tập bảng và cột ứng viên có điểm.
2. **Một lần gọi model:** model chọn từ danh sách ứng viên, không được tự đặt tên.
   - **Đo gì:** cột đo lường, hoặc chỉ số dạng key-value, cùng phép gộp nằm trong `aggregations` hay `cach_tong_hop`.
   - **Chia theo gì:** cột chiều hoặc thời gian, kèm đơn vị thời gian nếu có.
   - **Lọc theo gì:** cột, toán tử, giá trị. Giá trị lấy từ giá trị mã hoặc nhãn có thật.
   - **Loại dòng:** loại nào của bảng có nhiều grain.

   Mọi lựa chọn đều được đối chiếu lại với đồ thị. Tên không có trong đồ thị bị loại.

### 5.2 Tìm đường join bằng đồ thị

Đồ thị gồm đỉnh là bảng và cạnh là quan hệ đã duyệt. Mỗi cạnh đi được hai chiều, với chi phí khác nhau:

- Đi theo chiều nhiều → một (FK → PK): chi phí 1, không nhân dòng.
- Đi ngược chiều một → nhiều: chi phí cao, và đánh dấu **nhân dòng**.

Tập đỉnh cần nối (terminal) là các bảng chứa cột đã link. Thuật toán:

1. Chọn **bảng gốc**: bảng chứa cột đo lường, hoặc bảng giá trị của chỉ số key-value. Đây là bảng có grain mịn nhất
   trong các bảng cần đo.
2. Tìm cây Steiner nhỏ nhất nối bảng gốc với các terminal. Kho dữ liệu thường có dưới vài chục bảng, nên dùng
   Dreyfus–Wagner chính xác khi số terminal ≤ 6. Nhiều hơn thì dùng xấp xỉ theo đường ngắn nhất (Kou–Markowsky–Berman).
3. **Kiểm tra nhân dòng:** đường đi từ bảng gốc chỉ được đi theo chiều nhiều → một. Nếu buộc phải đi ngược, phép đo được
   gộp trước trong một subquery ở grain của bảng gốc, rồi mới nối. Không làm được thì dừng và giải thích.
4. **Nhiều đường cùng chi phí** (ví dụ hai FK cùng trỏ về `dm_ngay`): chọn theo cột đã link. Nếu vẫn còn mơ hồ thì hỏi
   lại người dùng bằng thẻ lựa chọn như hiện nay.

Thuật toán là Python thuần, không gọi model, có unit test đầy đủ.

### 5.3 Sinh và kiểm tra SQL

- SQL được **dựng bằng AST của sqlglot** từ kết quả linking và cây join, không để model viết SQL tự do. Thành phần gồm
  SELECT, JOIN theo cạnh, WHERE (gồm điều kiện chỉ số và loại dòng), GROUP BY, ORDER BY và LIMIT.
- Bộ lọc ngày trên cột `timestamp` phủ trọn ngày, theo quy tắc đã dùng ở AI Agent.
- Kiểm tra trước khi chạy:
  - chỉ một câu `SELECT`;
  - chỉ các bảng và cột có trong đồ thị;
  - không có hàm hệ thống;
  - có `LIMIT`.

  Bộ kiểm tra hiện có ở `agent_ladder/service.py` được dùng lại.

### 5.4 Chạy và trả lời

- SQL chạy qua Superset với **danh nghĩa người hỏi**, trên database và với quyền của họ.
- Kết quả được đánh dấu **"Tạm tính · từ dữ liệu gốc"**, giống metric tạm tính. Câu trả lời nêu cách tính bằng lời, và
  bên dưới có "Xem truy vấn".
- Câu hỏi được ghi log kèm SQL và đường join, để quản trị viên thấy câu nào hay được hỏi.

### 5.5 Hiển thị quá trình linking trên trang AI Agent

Bước "Liên kết dữ liệu" trong danh sách công cụ của câu trả lời, mở ra được, gồm:

- **Đồ thị nhỏ:**
  - Bảng ứng viên là đỉnh mờ. Bảng được chọn là đỉnh đậm, bảng gốc được đánh dấu.
  - Cạnh trong cây join được tô màu, kèm cặp cột và bản số.
  - Cạnh nhân dòng có cảnh báo.
- **Danh sách cột đã link**, theo nhóm Đo, Chia theo, Lọc, Loại dòng, mỗi cột kèm lý do (khớp nhãn, từ đồng nghĩa, giá
  trị mã).
- **Các bước:** ứng viên → model chọn → cây join → SQL. Mỗi bước có thời gian chạy, theo kiểu tool call hiện có.

Bố cục đồ thị dùng thư viện xếp lớp (elkjs, đã dùng ở lineage của Semantic Layer) hoặc xếp lớp đơn giản từ bảng gốc.

## 6. Các bước triển khai

1. **Semantic Layer: quan hệ có kiểm chứng (4.1).** Tab "Quan hệ", gợi ý từ nhiều nguồn, kiểm chứng, duyệt. Sau bước
   này: duyệt 6 quan hệ của kho mẫu.
2. **Semantic Layer: vai trò cột, chỉ số key-value, grain base table (4.2–4.4).** Sau bước này: khai báo cho 8 base
   table.
3. **Semantic Layer: `/schema-graph` (4.5)**, có test quyền: người không được xem bảng thì không thấy đỉnh và cạnh của
   bảng đó.
4. **AI Agent: thuật toán đồ thị và sinh SQL (5.2–5.3).** Python thuần, test trên đồ thị của kho mẫu và các đồ thị tự
   dựng: nhiều đường, nhân dòng, không có đường.
5. **AI Agent: linking, chạy và trả lời (5.1, 5.4)**, gắn vào ladder thay cho đề xuất dataset.
6. **AI Agent: hiển thị quá trình linking (5.5).**
7. **Nghiệm thu** bằng các câu hỏi chỉ base table trả lời được (mục 7).

Bước 1–3 dùng được ngay cho quản trị và không đổi câu trả lời của agent.

## 7. Tiêu chí nghiệm thu

| Câu hỏi | Đường join mong đợi | Kết quả |
| --- | --- | --- |
| "Có bao nhiêu lần nạp dữ liệu thất bại tuần này?" | Chỉ `tb_lan_nap_du_lieu` | `COUNT` với `trang_thai = 'THAT_BAI'`, không join |
| "Nhiệt độ trung bình theo giờ ở Hà Nội hôm qua theo dữ liệu gốc" | `tb_gia_tri_quan_sat` → `tb_quan_sat_thoi_tiet` → `dm_thanh_pho`, và → `dm_chi_so_thoi_tiet` | 24 dòng, `AVG(gia_tri_so)`, lọc chỉ số nhiệt độ, `loai_quan_sat = 'DU_BAO_GIO'`. Khớp với fact (28,76 °C trung bình ngày) |
| "Thành phố nào có nhiều quan sát hiện tại nhất?" | `tb_quan_sat_thoi_tiet` → `dm_thanh_pho` | `COUNT`, xếp hạng, nhãn thành phố |
| Câu hỏi về bảng không có quan hệ đã duyệt | Không có đường | Nói rõ chưa nối được dữ liệu, ghi log cho quản trị viên |
| Câu hỏi cần đi ngược chiều một → nhiều | Gộp trước trong subquery | Số không bị nhân dòng |

## 8. Quyết định thêm (duyệt 26/10/2026)

1. **Quyền khi chạy SQL.** Row-level security của Superset gắn với dataset, nên không tự áp vào SQL tự sinh. Bảng nào có
   luật RLS áp cho người hỏi thì không đưa vào đồ thị của người đó.
2. **Đề xuất dataset.** Giữ, nhưng chạy nền. Đường join và SQL hay dùng được gợi ý cho quản trị viên dựng aggregate
   dataset và metric chính thức, không chặn câu trả lời.
3. **Định vị cột.** Lọc ứng viên bằng so khớp từ khoá, bỏ dấu cả hai phía (tên chỉ số trong kho mẫu viết không dấu).
   Thêm embedding khi số bảng hoặc cột tăng lớn.
