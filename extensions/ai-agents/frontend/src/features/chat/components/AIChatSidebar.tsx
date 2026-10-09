import { useEffect, useRef, useState } from 'react';
import { ArrowUpRight, BookOpen, ChartColumn, ChartNoAxesCombined, ChevronDown, Check, ClipboardCheck, Code2, Columns3, Database, FileCheck2, ListChecks, LoaderCircle, Search, Sparkles, Table2, Wrench } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { currentDashboardRef, streamChat, type BIContract, type MetadataResolution, type ValidationError } from '@/shared/api/chat';

type AgentProgress = {
  id: number;
  kind: 'status' | 'context' | 'planning_attempt' | 'validation_errors' | 'tool_start' | 'tool_result' | 'error';
  text: string;
  tool?: string;
};

type ChatMessage = {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  progress?: AgentProgress[];
  contract?: BIContract;
  metadataResolution?: MetadataResolution;
  chartUrl?: string;
  chartError?: string;
  datasetNames?: Record<string, string>;
  planningErrors?: ValidationError[];
  isComplete?: boolean;
};

const toolLabels: Record<string, string> = {
  get_dataset_catalog: 'danh sách bộ dữ liệu',
  get_column_catalog: 'các trường dữ liệu',
  get_metric_catalog: 'các chỉ số có sẵn',
  get_chart_catalog: 'các biểu đồ trong dashboard',
  get_chart_capabilities: 'các loại biểu đồ được hỗ trợ',
  get_superset_chart_types: 'danh sách loại biểu đồ Superset hỗ trợ',
  get_superset_chart_type_schema: 'cấu hình chi tiết của loại biểu đồ',
  validate_bi_contract: 'kiểm tra kế hoạch phân tích',
  validate_metadata_resolution: 'kiểm tra cấu hình biểu đồ',
  query_sql: 'kiểm tra cấu trúc và số dòng của SQL',
  compile_chat_chart: 'compile và kiểm tra truy vấn biểu đồ Superset',
  get_tool_documentation: 'hướng dẫn công cụ',
};

const toolIcons = {
  get_dataset_catalog: Database,
  get_column_catalog: Columns3,
  get_metric_catalog: ChartColumn,
  get_chart_catalog: ChartNoAxesCombined,
  get_chart_capabilities: ChartNoAxesCombined,
  get_superset_chart_types: ChartNoAxesCombined,
  get_superset_chart_type_schema: Table2,
  validate_bi_contract: ClipboardCheck,
  validate_metadata_resolution: FileCheck2,
  query_sql: Search,
  compile_chat_chart: Code2,
  get_tool_documentation: BookOpen,
};

function conciseToolResult(output: unknown): string {
  if (typeof output !== 'string') return 'Đã hoàn tất.';
  const value = output.trim();
  if (!value) return 'Đã hoàn tất.';
  try {
    const parsed = JSON.parse(value);
    if (parsed && typeof parsed === 'object') {
      const record = parsed as Record<string, unknown>;
      if (typeof record.message === 'string') return record.message;
      if (typeof record.summary === 'string') return record.summary;
      if (Array.isArray(record.errors) && record.errors.length) {
        const first = record.errors[0] as { message?: unknown };
        if (typeof first?.message === 'string') return first.message;
      }
      return JSON.stringify(parsed);
    }
  } catch { /* Keep plain text tool output. */ }
  return value;
}

function addToolResult(progress: AgentProgress[], tool: string, output: unknown, nextId: () => number): AgentProgress[] {
  let pendingIndex = -1;
  for (let index = progress.length - 1; index >= 0; index -= 1) {
    if (progress[index].kind === 'tool_start' && progress[index].tool === tool) {
      pendingIndex = index;
      break;
    }
  }
  const text = `${toolLabels[tool] || tool || 'Kết quả công cụ'}: ${conciseToolResult(output)}`;
  if (pendingIndex < 0) return [...progress, { id: nextId(), kind: 'tool_result', tool, text }];
  return progress.map((item, index) => index === pendingIndex ? { ...item, kind: 'tool_result', text } : item);
}

const chartTypeLabels: Record<string, string> = {
  echarts_timeseries_bar: 'Biểu đồ cột (bar chart)',
  echarts_timeseries_line: 'Biểu đồ đường',
  echarts_area: 'Biểu đồ vùng',
  echarts_timeseries_scatter: 'Biểu đồ phân tán',
  table: 'Bảng dữ liệu',
  'ag-grid-table': 'Bảng dữ liệu tương tác',
  pie: 'Biểu đồ tròn',
  pivot_table_v2: 'Bảng tổng hợp',
  mixed_timeseries: 'Biểu đồ kết hợp theo thời gian',
  big_number_total: 'Chỉ số tổng hợp',
  big_number: 'Chỉ số tổng hợp',
};

function getChartTypeLabel(vizType: string | null) {
  if (!vizType) return 'Chưa xác định loại biểu đồ';
  const normalized = vizType.trim().toLowerCase();
  if (chartTypeLabels[normalized]) return chartTypeLabels[normalized];
  if (normalized.includes('bar')) return 'Biểu đồ cột (bar chart)';
  return vizType;
}

function timeRangeLabel(value: string): string {
  const labels: Record<string, string> = { today: 'Hôm nay', yesterday: 'Hôm qua' };
  const simpleLabel = labels[value.toLowerCase()];
  if (simpleLabel) return simpleLabel;

  const [start, end] = value.split(' : ');
  const formatDateTime = (timestamp: string) => {
    const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2})(?::\d{2}(?:\.\d+)?)?([+-]\d{2}:\d{2}|Z)?$/.exec(timestamp);
    if (!match) return null;
    return {
      text: `${match[3]}/${match[2]}/${match[1]} ${match[4]}`,
      zone: match[5] === 'Z' ? 'UTC' : match[5] ? `UTC${match[5]}` : '',
    };
  };
  if (!end) return value;
  const startLabel = formatDateTime(start);
  const endLabel = formatDateTime(end);
  if (!startLabel || !endLabel) return value;
  const zone = startLabel.zone === endLabel.zone ? startLabel.zone : '';
  return `${startLabel.text} – ${endLabel.text}${zone ? ` (${zone})` : ''}`;
}

function ContractResult({ contract }: { contract: BIContract }) {
  return (
    <section className="ai-chat-contract" aria-label="Kế hoạch phân tích">
      <h3>Kế hoạch phân tích</h3>
      <p><strong>Mục tiêu:</strong> {contract.user_intent.objective}</p>
    </section>
  );
}

function fieldName(value: unknown): string | null {
  if (typeof value === 'string') return value;
  if (!value || typeof value !== 'object' || !('name' in value)) return null;
  const name = (value as { name?: unknown }).name;
  return typeof name === 'string' ? name : null;
}

function fieldLabel(name: string): string {
  const labels: Record<string, string> = {
    thoi_gian_ghi_nhan: 'Thời gian ghi nhận',
    nhiet_do_c: 'Nhiệt độ (°C)',
    ten_thanhpho: 'Thành phố',
  };
  return labels[name] || name.replace(/_/g, ' ');
}

function aggregationLabel(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const labels: Record<string, string> = { AVG: 'Trung bình', SUM: 'Tổng', COUNT: 'Số lượng', MIN: 'Nhỏ nhất', MAX: 'Lớn nhất' };
  return labels[value.toUpperCase()] || value;
}

function MetadataResolutionResult({ resolution, datasetNames = {} }: { resolution: MetadataResolution; datasetNames?: Record<string, string> }) {
  const config = resolution.config;
  const xField = fieldName(config.x);
  const yValues = Array.isArray(config.y) ? config.y : config.y ? [config.y] : [];
  const yFields = yValues.map(value => {
    const name = fieldName(value);
    if (!name) return null;
    const aggregate = value && typeof value === 'object' && 'aggregate' in value
      ? aggregationLabel((value as { aggregate?: unknown }).aggregate)
      : null;
    return `${aggregate ? `${aggregate} ` : ''}${fieldLabel(name)}`;
  }).filter((value): value is string => Boolean(value));
  const filters = Array.isArray(config.filters) ? config.filters.map(value => {
    if (!value || typeof value !== 'object') return null;
    const filter = value as { column?: unknown; op?: unknown; value?: unknown };
    if (typeof filter.column !== 'string') return null;
    const operators: Record<string, string> = { IN: 'thuộc', 'NOT IN': 'không thuộc', ILIKE: 'có chứa' };
    const operator = typeof filter.op === 'string' ? operators[filter.op.toUpperCase()] || filter.op : '=';
    const rawValue = Array.isArray(filter.value) ? filter.value.join(', ') : String(filter.value ?? '');
    const filterValue = filter.op === 'ILIKE' ? rawValue.replace(/^%|%$/g, '') : rawValue;
    return `${fieldLabel(filter.column)} ${operator} ${filterValue}`;
  }).filter((value): value is string => Boolean(value)) : [];
  const datasetName = resolution.dataset_id == null
    ? 'Chưa xác định'
    : datasetNames[String(resolution.dataset_id)] || `#${resolution.dataset_id}`;
  const timeCompare = Array.isArray(config.time_compare) ? config.time_compare : [];

  return (
    <section className="ai-chat-contract" aria-label="Metadata biểu đồ">
      <h3>{resolution.status === 'ready' ? 'Cấu hình biểu đồ đã kiểm tra' : 'Chưa thể cấu hình biểu đồ'}</h3>
      {resolution.message ? <p>{resolution.message}</p> : null}
      {resolution.status === 'ready' ? (
        <>
          <p><strong>Bộ dữ liệu:</strong> {datasetName}</p>
          <p><strong>Loại biểu đồ:</strong> {getChartTypeLabel(resolution.viz_type)}</p>
          {resolution.time_range ? <p><strong>Khoảng thời gian:</strong> {timeRangeLabel(resolution.time_range)}</p> : null}
          {timeCompare.includes('1 day ago') ? <p><strong>So sánh:</strong> Hôm nay và hôm qua, căn theo cùng thời điểm trong ngày</p> : null}
          {xField ? <p><strong>Trục X:</strong> {fieldLabel(xField)}</p> : null}
          {yFields.length ? <p><strong>Chỉ số:</strong> {yFields.join(', ')}</p> : null}
          {filters.length ? <p><strong>Bộ lọc:</strong> {filters.join('; ')}</p> : null}
        </>
      ) : null}
    </section>
  );
}

export function AIChatSidebar({ onClose }: { onClose: () => void }) {
  const [draft, setDraft] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [dashboardRef, setDashboardRef] = useState<string | null>(currentDashboardRef);
  const nextMessageId = useRef(messages.reduce((next, message) => Math.max(next, message.id + 1), 1));
  const nextProgressId = useRef(1);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const transcriptRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const syncDashboard = () => setDashboardRef(currentDashboardRef());
    window.addEventListener('popstate', syncDashboard);
    return () => window.removeEventListener('popstate', syncDashboard);
  }, []);

  useEffect(() => {
    transcriptRef.current?.scrollTo({ top: transcriptRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages]);

  const sendMessage = async () => {
    const content = draft.trim();
    if (!content || isStreaming) return;
    const activeDashboard = currentDashboardRef();
    setDashboardRef(activeDashboard);
    if (!activeDashboard) {
      setMessages(current => [...current, {
        id: nextMessageId.current++,
        role: 'assistant',
        content: 'Hãy mở một dashboard để bắt đầu trò chuyện với AI Agent.',
        isComplete: true,
      }]);
      setDraft('');
      return;
    }

    const userMessage: ChatMessage = {
      id: nextMessageId.current++,
      role: 'user',
      content,
    };
    const assistantId = nextMessageId.current++;
    setMessages(current => [...current, userMessage, { id: assistantId, role: 'assistant', content: '', progress: [] }]);
    setDraft('');
    setIsStreaming(true);
    try {
      await streamChat(activeDashboard, content, (event, data) => {
        setMessages(current => current.map(message => {
          if (message.id !== assistantId) return message;
          if (event === 'token') return { ...message, content: message.content + (data.token || '') };
          if (event === 'status') return { ...message, progress: [...(message.progress || []), { id: nextProgressId.current++, kind: 'status', text: data.message === 'Đang lấy ngữ cảnh dashboard' ? 'Đang kiểm tra dashboard và dữ liệu được phép sử dụng…' : data.message === 'Đang lập kế hoạch BI' ? 'Đang chuẩn bị kế hoạch phân tích…' : data.message || 'Đang xử lý…' }] };
          if (event === 'context') return { ...message, datasetNames: data.datasets || {}, progress: [...(message.progress || []), { id: nextProgressId.current++, kind: 'context', text: `Đã xác định dashboard “${data.dashboard_title || 'hiện tại'}” và ${data.authorized_dataset_count ?? 0} bộ dữ liệu có thể sử dụng.` }] };
          if (event === 'planning_attempt') return { ...message, progress: [...(message.progress || []), { id: nextProgressId.current++, kind: 'planning_attempt', text: (data.attempt || 1) > 1 ? `Đang điều chỉnh kế hoạch theo kết quả kiểm tra (lần ${data.attempt}).` : 'Đang lập kế hoạch phân tích…' }] };
          if (event === 'metadata_attempt') return { ...message, progress: [...(message.progress || []), { id: nextProgressId.current++, kind: 'planning_attempt', text: (data.attempt || 1) > 1 ? `Đang điều chỉnh cấu hình biểu đồ (lần ${data.attempt}).` : 'Đang chọn biểu đồ và ánh xạ tham số theo BI Plan…' }] };
          if (event === 'validation_errors') {
            const errors = data.errors || [];
            return { ...message, planningErrors: errors, progress: [...(message.progress || []), { id: nextProgressId.current++, kind: 'validation_errors', text: `Kế hoạch cần chỉnh ${errors.length} mục để khớp với dữ liệu và cấu hình dashboard.` }] };
          }
          if (event === 'metadata_validation_errors') {
            const errors = data.errors || [];
            return { ...message, progress: [...(message.progress || []), { id: nextProgressId.current++, kind: 'validation_errors', text: `Cấu hình biểu đồ cần điều chỉnh ${errors.length} mục để khớp BI Plan và schema Superset.` }] };
          }
          if (event === 'data_builder_attempt') return { ...message, progress: [...(message.progress || []), { id: nextProgressId.current++, kind: 'planning_attempt', text: (data.attempt || 1) > 1 ? `Đang sửa SQL theo lỗi truy vấn (lần ${data.attempt}).` : 'Đang tạo SQL và kiểm tra cấu trúc kết quả…' }] };
          if (event === 'data_builder_validation_errors') {
            const errors = data.errors || [];
            return { ...message, progress: [...(message.progress || []), { id: nextProgressId.current++, kind: 'validation_errors', text: `SQL hoặc biểu đồ cần điều chỉnh ${errors.length} mục trước khi xác nhận.` }] };
          }
          if (event === 'tool_start') {
            const tool = data.tool || '';
            return { ...message, progress: [...(message.progress || []), { id: nextProgressId.current++, kind: 'tool_start', tool, text: `Đang lấy ${toolLabels[tool] || tool || 'thông tin'}…` }] };
          }
          if (event === 'tool_result') return { ...message, progress: addToolResult(message.progress || [], data.tool || '', data.output, () => nextProgressId.current++) };
          if (event === 'bi_contract' && data.contract) return { ...message, contract: data.contract, planningErrors: [], content: 'Mình đã chuẩn bị kế hoạch phân tích và kiểm tra kế hoạch này với dữ liệu cùng cấu hình của dashboard.' };
          if (event === 'metadata_resolution' && data.resolution) return { ...message, metadataResolution: data.resolution };
          if (event === 'data_builder_result') {
            if (data.success && data.sql) return {
              ...message,
              chartUrl: data.chart_url || undefined,
              chartError: data.chart_error || undefined,
              content: data.chart_url
                ? 'Biểu đồ Superset đã được dựng từ SQL cuối cùng.'
                : 'SQL cuối cùng đã chạy thành công; chưa thể dựng biểu đồ Superset.',
            };
            const errors = Array.isArray(data.errors) ? data.errors.map(error => error.message).filter(Boolean).join(' ') : '';
            return { ...message, content: `Chưa thể xác nhận SQL và biểu đồ.${errors ? ` ${errors}` : ''}` };
          }
          if (event === 'planning_failure') {
            const errors = data.errors || [];
            return { ...message, planningErrors: errors, content: 'Mình chưa thể lập kế hoạch phân tích phù hợp. Chi tiết cần làm rõ được liệt kê bên dưới.' };
          }
          if (event === 'done') return { ...message, isComplete: true, progress: (message.progress || []).map(item => item.kind === 'status' ? { ...item, text: 'Đã hoàn tất' } : item) };
          if (event === 'error') return { ...message, isComplete: true, progress: [...(message.progress || []), { id: nextProgressId.current++, kind: 'error', text: data.message || 'Agent gặp lỗi' }] };
          return message;
        }));
      });
    } catch (error) {
      setMessages(current => current.map(message => message.id === assistantId
        ? { ...message, isComplete: true, progress: [...(message.progress || []).map(item => item.kind === 'status' ? { ...item, text: 'Đã xảy ra lỗi' } : item), { id: nextProgressId.current++, kind: 'error', text: error instanceof Error ? error.message : 'Không thể kết nối Agent' }] }
        : message));
    } finally {
      setIsStreaming(false);
    }
  };

  const suggestedQuestions = [
    'Phân tích xu hướng theo thời gian',
    'So sánh các nhóm theo chỉ số chính',
    'Tóm tắt chỉ số chính thành một giá trị',
  ];

  return (
    <section className="ai-chat-sidebar" aria-label="Text to BI AI Agent">
      <header className="ai-chat-header">
        <div className="ai-chat-heading">
          <span className="ai-chat-mark" aria-hidden="true">✦</span>
          <div>
            <h2>AI Agent</h2>
            <p>{dashboardRef ? 'Theo ngữ cảnh dashboard hiện tại' : 'Mở dashboard để bắt đầu'}</p>
          </div>
        </div>
        <button type="button" className="ai-chat-close" aria-label="Đóng AI Agent" onClick={onClose}>×</button>
      </header>

      <div className="ai-chat-transcript" ref={transcriptRef}>
        <div className="ai-chat-message-list">
          {messages.length === 0 ? (
            <div className="ai-chat-empty-state">
              <span className="ai-chat-empty-icon" aria-hidden="true"><Sparkles /></span>
              <p className="ai-chat-eyebrow">TRỢ LÝ DASHBOARD</p>
              <h3>Bạn muốn tìm hiểu điều gì?</h3>
              <p className="ai-chat-empty-description">
                Hỏi về xu hướng, so sánh chỉ số hoặc khám phá các biểu đồ trong dashboard này.
              </p>
              <div className="ai-chat-suggestions" aria-label="Câu hỏi gợi ý">
                {suggestedQuestions.map(question => (
                  <button type="button" key={question} onClick={() => {
                    setDraft(question);
                    inputRef.current?.focus();
                  }}>
                    <ArrowUpRight aria-hidden="true" />{question}
                  </button>
                ))}
              </div>
            </div>
          ) : messages.map(message => (
            <div key={message.id} className={`ai-chat-turn is-${message.role}`}>
              <div className={`ai-chat-avatar is-${message.role}`}>
                {message.role === 'user' ? 'B' : <Sparkles aria-hidden="true" />}
              </div>
              <div className="ai-chat-turn-content">
                <div className="ai-chat-sender">{message.role === 'user' ? 'Bạn' : 'AI Agent'}</div>
                <div className={`ai-chat-bubble is-${message.role}`}>
                  {message.progress?.length ? (
                    <details className="ai-chat-progress-details" open={!message.isComplete}>
                      <summary aria-label={`${message.progress.filter(item => Boolean(item.tool)).length} bước tra cứu · ${message.isComplete ? 'Xem' : 'Ẩn'} tiến trình`}>
                        <span>Các bước chuẩn bị · {message.progress.filter(item => Boolean(item.tool)).length} lượt tra cứu</span>
                        <span className="ai-chat-progress-toggle" aria-hidden="true"><ChevronDown /></span>
                      </summary>
                      <ol className="ai-chat-progress" aria-label="Tiến trình Agent">
                        {message.progress.map(item => {
                          const ToolIcon = item.tool ? toolIcons[item.tool as keyof typeof toolIcons] || Wrench : null;
                          return (
                            <li key={item.id} className={`is-${item.kind}`} title={item.text}>
                              {ToolIcon ? <span className="ai-chat-progress-tool-icon" aria-hidden="true"><ToolIcon /></span> : null}
                              <span className="ai-chat-progress-text">{item.text}</span>
                              {item.kind === 'tool_start' ? <LoaderCircle className="ai-chat-progress-spinner" aria-label="Đang chạy" /> : null}
                              {item.kind === 'tool_result' ? <Check className="ai-chat-progress-check" aria-label="Hoàn tất" /> : null}
                            </li>
                          );
                        })}
                      </ol>
                    </details>
                  ) : null}
                  {message.planningErrors?.length ? (
                    <ul className="ai-chat-planning-errors" aria-label="Lỗi xác thực kế hoạch">
                      {message.planningErrors.map((error, index) => <li key={`${error.code}-${index}`}><strong>{error.path}</strong>: {error.message}</li>)}
                    </ul>
                  ) : null}
                  {message.role === 'assistant' ? (
                    <div className="ai-chat-markdown">
                      <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ table: ({ children }) => <div className="ai-chat-table-wrap"><table>{children}</table></div> }}>
                        {message.content}
                      </ReactMarkdown>
                    </div>
                  ) : message.content}
                      {message.contract ? <ContractResult contract={message.contract} /> : null}
                      {message.metadataResolution ? <MetadataResolutionResult resolution={message.metadataResolution} datasetNames={message.datasetNames} /> : null}
                      {message.chartUrl ? <section className="ai-chat-contract ai-chat-chart-result" aria-label="Biểu đồ Superset">
                        <h3>Biểu đồ Superset</h3>
                        <iframe src={message.chartUrl} title="Biểu đồ được tạo từ SQL Data Builder" loading="lazy" />
                      </section> : null}
                      {message.chartError ? <section className="ai-chat-contract" role="status"><p>Không thể hiển thị biểu đồ Superset: {message.chartError}</p></section> : null}
                </div>
              </div>
            </div>
          ))}
          <div aria-hidden="true" />
        </div>
      </div>

      <form className="ai-chat-composer" onSubmit={event => { event.preventDefault(); sendMessage(); }}>
        <div className="ai-chat-composer-box">
          <textarea
            ref={inputRef}
            value={draft}
            onChange={event => setDraft(event.target.value)}
            onKeyDown={event => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                sendMessage();
              }
            }}
            placeholder={dashboardRef ? 'Hỏi về dashboard...' : 'Mở dashboard để bắt đầu...'}
            rows={2}
            aria-label="Tin nhắn cho AI"
          />
          <div className="ai-chat-composer-footer">
            <span><kbd>↵</kbd> gửi <span className="ai-chat-shortcut-dot">·</span> <kbd>⇧ ↵</kbd> xuống dòng</span>
            <button type="submit" disabled={!draft.trim() || isStreaming} aria-label="Gửi tin nhắn">
              <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M2.2 9.1 17.5 2.5l-4.8 15-2.5-6.1-8-2.3Z" /><path d="m10.2 11.4 4.1-4.1" /></svg>
            </button>
          </div>
        </div>
      </form>
    </section>
  );
}
