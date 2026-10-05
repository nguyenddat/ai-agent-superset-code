# AI Agents Extension

Tài liệu này mô tả cấu trúc hiện tại của extension AI Agents và trách nhiệm của
các file đã có. Backend được phát triển độc lập với backend lõi của Superset;
các ID user và dashboard trong model là ID tham chiếu sang Superset.

## Cấu trúc thư mục

```text
extensions/ai-agents/
├── AGENTS.md
├── backend/
│   ├── common/
│   │   └── type_formatter.py
│   ├── core/
│   │   ├── chat_models.py
│   │   └── settings.py
│   ├── ai_agent_backend/
│   │   ├── __init__.py
│   │   └── chat_api.py             # Flask SSE endpoint, persistence and dashboard tools
│   ├── models/
│   │   ├── model_base.py
│   │   ├── model_message.py
│   │   ├── model_thread.py
│   │   └── model_toolcall.py
│   ├── repositories/
│   │   ├── repo_base.py
│   │   ├── repo_message.py
│   │   ├── repo_thread.py
│   │   └── repo_toolcall.py
│   └── modules/                 # Chưa có file triển khai
└── frontend/
    └── src/
        ├── index.tsx
        ├── features/
        │   ├── chat/components/.gitkeep
        │   │   ├── AIChatSidebar.tsx
        │   │   └── AIChatSidebar.css
        │   └── threads/components/.gitkeep
        ├── integration/
        │   ├── .gitkeep
        │   └── installDashboardAI.tsx
        ├── shared/
        │   ├── api/.gitkeep
        │   └── types/.gitkeep
        └── styles/.gitkeep
```

## Backend

### `backend/common/type_formatter.py`

Hàm định dạng thời gian dùng chung. Timestamp được chuẩn hóa về UTC và trả về
chuỗi ISO 8601 để lưu dưới dạng text.

- `to_iso_text(value: datetime | None = None) -> str`: chuyển datetime sang ISO
  8601 UTC. Nếu `value` không có timezone thì xem là UTC; nếu bỏ qua `value`,
  dùng thời gian hiện tại.

### `backend/core/settings.py`

Cấu hình backend qua `pydantic-settings`.

- `BASE_DIR`: đường dẫn tuyệt đối đến `backend/`.
- `ENV_FILE`: đường dẫn `.env` ở thư mục gốc repository.
- `Config`: khai báo cấu hình, encoding của env file, và các trường `base_dir`,
  `openrouter_api_key`, `model_temperature`.
- `config`: instance cấu hình dùng chung. `OPENROUTER_API_KEY` được đọc từ
  environment hoặc `.env`; mặc định là chuỗi rỗng. `MODEL_TEMPERATURE` mặc định
  là `0.0`.

### `backend/core/chat_models.py`

Khởi tạo và cache LangChain `ChatOpenAI` client cấu hình trỏ tới OpenRouter.

- `model_names`: danh sách model cho phép, hiện có
  `openai/gpt-4o-mini-2024-07-18`.
- `model_cache`: cache client theo tên model để tái sử dụng.
- `get_chat_model(model_name: str) -> ChatOpenAI`: kiểm tra tên model, tạo
  client nếu chưa có trong cache và trả client. Tên không nằm trong
  `model_names` sẽ gây `ValueError`.

### `backend/models/model_base.py`

Khai báo SQLAlchemy declarative base cho các model của extension.

- `BaseModel`: base abstract cung cấp `id` số tự tăng, `created_at` và
  `updated_at`. Hai timestamp là cột `TEXT`, giá trị mặc định được tạo bằng
  `to_iso_text`; `updated_at` cũng được tạo lại khi SQLAlchemy ORM cập nhật row.

### `backend/models/model_thread.py`

Khai báo bảng `ai_threads`.

- `Thread`: một cuộc hội thoại AI thuộc về một Superset user và một dashboard.
- `superset_user_id`, `superset_dashboard_id`: ID integer tham chiếu Superset,
  không có foreign key vì Superset metadata nằm ngoài DB extension.
- `title`, `status`, `archived_at`: tiêu đề, trạng thái hội thoại và thời điểm
  archive dạng ISO text.
- `messages`: quan hệ một-nhiều tới `Message`, sắp theo `sequence_no`; xóa
  thread qua ORM sẽ cascade tới messages và tool calls.
- Index `ix_ai_threads_user_dashboard_updated`: hỗ trợ lấy thread theo user,
  dashboard và thời điểm cập nhật.

### `backend/models/model_message.py`

Khai báo bảng `ai_messages`.

- `Message`: một message với role dự kiến `user`, `assistant`, `system` hoặc
  `tool`.
- `thread_id`: foreign key nội bộ tới `ai_threads.id`, xóa cascade.
- `sequence_no`: thứ tự message trong thread; duy nhất cùng `thread_id`.
- `role`, `content`, `status`: vai trò, nội dung text và trạng thái xử lý.
- `extra_data`: metadata tùy chọn kiểu JSON.
- `thread`: quan hệ ngược tới `Thread`.
- `tool_calls`: quan hệ một-nhiều tới `ToolCall`, sắp theo `call_index`; xóa
  message qua ORM sẽ cascade tới tool calls.
- `ix_ai_messages_thread_created`: hỗ trợ đọc lịch sử theo thread và thời gian.

### `backend/models/model_toolcall.py`

Khai báo bảng `ai_tool_calls` để lưu lời gọi tool do assistant phát sinh.

- `ToolCall`: một lần gọi tool gắn với message.
- `message_id`: foreign key nội bộ tới `ai_messages.id`, xóa cascade.
- `call_index`, `tool_name`: thứ tự gọi trong message và tên tool.
- `arguments`, `result`: đầu vào và kết quả JSON; kết quả có thể chưa có khi tool
  đang chạy hoặc thất bại.
- `status`, `error_text`: trạng thái thực thi và thông tin lỗi nếu có.
- `started_at`, `finished_at`: thời điểm bắt đầu/kết thúc dạng ISO text;
  `started_at` mặc định là thời điểm hiện tại UTC.
- `message`: quan hệ ngược tới `Message`.
- `ix_ai_tool_calls_status_created`: hỗ trợ tra cứu theo trạng thái và thời gian.

### `backend/repositories/`

Các repository đóng gói truy vấn SQLAlchemy, nhận `Session` từ bên gọi và không
tự commit transaction.

- `repo_base.py` — `RepositoryBase`: CRUD cơ bản dùng chung: `get`, `list`,
  `add`, `delete`, `delete_by_id`. `add` gọi `flush` để lấy ID/kiểm tra lỗi DB;
  commit hoặc rollback thuộc trách nhiệm service.
- `repo_thread.py` — `ThreadRepository`: `list_for_dashboard` lấy thread theo
  user và dashboard, mới cập nhật trước; `get_for_dashboard_user` chỉ trả thread
  khi khớp cả thread ID, user ID và dashboard ID.
- `repo_message.py` — `MessageRepository`: `list_for_thread` trả lịch sử theo
  `sequence_no`; `get_next_sequence_no` tính số thứ tự kế tiếp trong thread.
- `repo_toolcall.py` — `ToolCallRepository`: `list_for_message` lấy tool calls
  của một message theo `call_index`.

### `backend/modules/`

Thư mục dành cho các module nghiệp vụ như NLU, sinh SQL, kiểm tra SQL và bàn
giao kết quả cho Superset. Hiện chưa có file triển khai.

### `backend/ai_agent_backend/chat_api.py`

`POST /api/v1/ai/chat/stream` нь Superset-ийн нэвтэрсэн cookie session болон
CSRF хамгаалалтаар ажиллаж, SSE `status`, `tool_start`, `tool_progress`,
`tool_result`, `token`, `done`, `error` event буцаана. Dashboard эрхийг
Superset-ийн `security_manager.raise_for_access` шалгана; thread-ийг хэрэглэгч,
dashboard, thread-ийн ID-аар хамтад нь шалгана. User/assistant message болон
tool call/run төлөв extension-ийн `ai_*` хүснэгтүүдэд хадгалагдана.

Read-only tool-ууд dashboard-ийн chart metadata-г үзэх эсвэл тухайн dashboard-д
байгаа chart-ийн хадгалсан query-г ажиллуулна. `ChartDataCommand.validate()` ба
`run()` нь datasource болон Superset query security-г хадгална. Tool үр дүнг
хязгаарлаж, хэрэглэгчийн UI руу зөвхөн товч summary stream хийнэ. Ярианы
түүхийг SQL хүснэгтээс сэргээдэг тул InMemorySaver ашиглахгүй; ингэснээр олон
Gunicorn worker болон restart хооронд thread state алдагдахгүй.

Extension хүснэгтүүд байхгүй үед `BaseModel.metadata.create_all()` эхний
хүсэлтээр үүсгэнэ. Production schema өөрчлөлтөд Alembic migration нэмэх
шаардлагатай. Model context-д chart-аас дээд тал нь 100 мөр орно.
`OPENROUTER_API_KEY`-г Superset container-д тохируулна. LangChain dependency
өөрчлөгдсөн тул шинэ backend-г ашиглахын өмнө Superset image-ийг rebuild хийнэ.

## Frontend

Frontend đang có prototype sidebar chat và điểm gắn nút vào dashboard; phần gọi
API backend chưa được nối. Bundle được build bằng esbuild và nạp qua custom
template hook cùng Flask blueprint trong `superset/superset_config.py`.

- `src/index.tsx`: entry point gọi `installDashboardAI()` khi frontend bundle
  được nạp.
- `src/integration/installDashboardAI.tsx`: quan sát DOM của Superset, tìm menu
  `actions-trigger` trên dashboard, gắn React root ngay trước menu cho cả viewer
  và editor và trả về hàm cleanup. Đây là adapter
  prototype dựa trên DOM; khi tích hợp production nên thay bằng điểm tích hợp
  frontend Superset được kiểm soát.
- `src/features/threads/components/`: component danh sách và quản lý threads.
- `src/features/chat/components/AIChatSidebar.tsx`: nút AI Agent ngay trước menu ba chấm và sidebar chat trượt từ phải vào; quản lý đóng bằng nút/Escape,
  input và message phía user tại local state. `onSendMessage` là callback để
  nối API sau này.
- `src/features/chat/components/AIChatSidebar.css`: style cho trigger, drawer,
  message, empty state và composer.
- `src/shared/api/`: client gọi API backend extension.
- `src/shared/types/`: kiểu dữ liệu dùng chung giữa các feature.
- `src/styles/`: style dùng chung.
- `.gitkeep`: giữ thư mục rỗng trong git; không chứa logic ứng dụng.

## Quy ước hiện tại

- Các bảng chat nằm trong DB của extension; không tạo foreign key sang DB
  metadata Superset.
- ID nội bộ dùng integer tự tăng; ID user/dashboard là integer tham chiếu từ
  Superset.
- Quyền dashboard và chart được kiểm tra qua security manager và
  `ChartDataCommand` của Superset.
- Các cột thời gian được lưu dưới dạng ISO 8601 text UTC.
- Import hiện giả định `backend/` nằm trên Python import path (ví dụ
  `PYTHONPATH=extensions/ai-agents/backend`), do các model dùng import dạng
  `models...` và `common...`.
