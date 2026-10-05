import { useEffect, useRef, useState } from 'react';
import { ArrowUpRight, Sparkles } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Bubble, BubbleContent } from '@/components/ui/bubble';
import { Button } from '@/components/ui/button';
import {
  Message,
  MessageAvatar,
  MessageContent,
  MessageHeader,
} from '@/components/ui/message';
import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from '@/components/ui/message-scroller';
import { streamChat, type InlineChartPayload } from '@/shared/api/chat';

type AgentProgress = { id: number; kind: 'status' | 'analysis_summary' | 'tool_start' | 'tool_result' | 'error'; text: string };

type ChatMessage = {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  progress?: AgentProgress[];
  charts?: InlineChartPayload[];
  isComplete?: boolean;
};

const toolLabels: Record<string, string> = {
  get_dataset_catalog: 'catalog dataset',
  get_column_catalog: 'catalog cột',
  get_metric_catalog: 'catalog metrics',
  get_chart_catalog: 'catalog biểu đồ',
  query_dataset: 'dữ liệu',
};

function InlineChart({ chart }: { chart: InlineChartPayload }) {
  return (
    <section className="ai-chat-inline-chart" aria-label={`Biểu đồ: ${chart.title}`}>
      <div className="ai-chat-inline-chart-heading">
        <strong>{chart.title}</strong>
      </div>
      <iframe className="ai-chat-superset-chart" src={chart.src} title={chart.title} loading="lazy" />
    </section>
  );
}

type AIChatSidebarProps = {
  dashboardId: string;
  dashboardTitle?: string;
};

export function AIChatSidebar({
  dashboardId,
  dashboardTitle,
}: AIChatSidebarProps) {
  const minSidebarWidth = 340;
  const maxSidebarWidth = 900;
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    if (typeof window === 'undefined') return 520;
    const savedWidth = Number(window.localStorage.getItem('ai-agent-sidebar-width'));
    return Number.isFinite(savedWidth) && savedWidth >= minSidebarWidth
      ? Math.min(savedWidth, maxSidebarWidth)
      : 520;
  });
  const [isResizing, setIsResizing] = useState(false);
  const resizeStart = useRef<{ pointerX: number; width: number } | null>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [draft, setDraft] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const nextMessageId = useRef(1);
  const nextProgressId = useRef(1);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const close = () => { setIsOpen(false); triggerRef.current?.focus(); };
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!isOpen) return undefined;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close();
    };

    window.addEventListener('keydown', handleKeyDown);
    inputRef.current?.focus();
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen]);

  useEffect(() => {
    if (!isResizing) return undefined;
    const handlePointerMove = (event: PointerEvent) => {
      if (!resizeStart.current) return;
      const availableWidth = Math.max(minSidebarWidth, window.innerWidth - 24);
      const nextWidth = Math.max(minSidebarWidth, Math.min(availableWidth, maxSidebarWidth,
        resizeStart.current.width + resizeStart.current.pointerX - event.clientX));
      setSidebarWidth(nextWidth);
    };
    const stopResizing = () => {
      setIsResizing(false);
      resizeStart.current = null;
    };
    window.addEventListener('pointermove', handlePointerMove);
    window.addEventListener('pointerup', stopResizing);
    window.addEventListener('pointercancel', stopResizing);
    return () => {
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerup', stopResizing);
      window.removeEventListener('pointercancel', stopResizing);
    };
  }, [isResizing]);

  useEffect(() => {
    window.localStorage.setItem('ai-agent-sidebar-width', String(Math.round(sidebarWidth)));
  }, [sidebarWidth]);

  const startResizing = (event: React.PointerEvent<HTMLDivElement>) => {
    if (window.innerWidth <= 480) return;
    event.preventDefault();
    resizeStart.current = { pointerX: event.clientX, width: sidebarWidth };
    setIsResizing(true);
  };

  const sendMessage = async () => {
    const content = draft.trim();
    if (!content || isStreaming) return;

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
      await streamChat(dashboardId, content, (event, data) => {
        setMessages(current => current.map(message => {
          if (message.id !== assistantId) return message;
          if (event === 'token') return { ...message, content: message.content + (data.token || '') };
          if (event === 'status') return { ...message, progress: [...(message.progress || []), { id: nextProgressId.current++, kind: 'status', text: data.message || 'Đang xử lý' }] };
          if (event === 'analysis_summary') return { ...message, progress: [...(message.progress || []), { id: nextProgressId.current++, kind: 'analysis_summary', text: data.summary || '' }] };
          if (event === 'tool_start') return { ...message, progress: [...(message.progress || []), { id: nextProgressId.current++, kind: 'tool_start', text: `Đang lấy ${toolLabels[data.tool || ''] || data.tool || 'thông tin'}…` }] };
          if (event === 'tool_result') return { ...message, progress: [...(message.progress || []), { id: nextProgressId.current++, kind: 'tool_result', text: data.output || 'Đã lấy metadata' }] };
          if (event === 'chart' && data.chart) return { ...message, charts: [...(message.charts || []), data.chart] };
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
    'Dashboard này có những dataset nào?',
    'Các cột và metrics chính là gì?',
    'Dashboard có những biểu đồ nào?',
  ];

  return (
    <>
      <button
        type="button"
        ref={triggerRef}
        className="ai-dashboard-trigger"
        aria-label="AI Agent"
        aria-controls="ai-agent-sidebar"
        aria-expanded={isOpen}
        onClick={() => setIsOpen(open => !open)}
      >
        <svg viewBox="0 0 20 20" aria-hidden="true">
          <path d="M10 1.8 11.8 8.2 18.2 10l-6.4 1.8L10 18.2l-1.8-6.4L1.8 10l6.4-1.8L10 1.8Z" />
          <path d="m16.2 1 .7 2.1L19 3.8l-2.1.7-.7 2.1-.7-2.1-2.1-.7 2.1-.7.7-2.1Z" />
        </svg>
        <span>AI Agent</span>
      </button>

      {isOpen && <aside
        id="ai-agent-sidebar"
        className={`ai-chat-sidebar${isOpen ? ' is-open' : ''}`}
        aria-label="AI assistant"
        aria-hidden={!isOpen}
        style={{ '--ai-sidebar-width': `${sidebarWidth}px` } as React.CSSProperties}
      >
        <div
          className="ai-chat-resize-handle"
          role="separator"
          aria-label="Thay đổi độ rộng sidebar AI Agent"
          aria-orientation="vertical"
          aria-valuemin={minSidebarWidth}
          aria-valuemax={maxSidebarWidth}
          aria-valuenow={Math.round(sidebarWidth)}
          tabIndex={0}
          onPointerDown={startResizing}
          onKeyDown={event => {
            if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
            event.preventDefault();
            const delta = event.key === 'ArrowLeft' ? -24 : 24;
            setSidebarWidth(width => Math.max(minSidebarWidth, Math.min(maxSidebarWidth, width + delta)));
          }}
        />
        <header className="ai-chat-header">
          <div className="ai-chat-heading">
            <span className="ai-chat-mark" aria-hidden="true">✦</span>
            <div>
              <h2>AI Agent</h2>
              <p title={dashboardTitle}>
                {dashboardTitle || 'Đang xem dashboard'}
              </p>
            </div>
          </div>
          <button
            type="button"
            className="ai-chat-close"
            aria-label="Đóng AI assistant"
            onClick={close}
          >
            ×
          </button>
        </header>

        <MessageScrollerProvider autoScroll={messages.length > 0}>
          <MessageScroller className="ai-chat-transcript">
            <MessageScrollerViewport className="ai-chat-viewport">
              <MessageScrollerContent className="ai-chat-message-list">
                {messages.length === 0 ? (
                  <MessageScrollerItem messageId="welcome" className="ai-chat-welcome-item">
                    <div className="ai-chat-empty-state">
                      <span className="ai-chat-empty-icon" aria-hidden="true"><Sparkles /></span>
                      <p className="ai-chat-eyebrow">TRỢ LÝ DASHBOARD</p>
                      <h3>Bạn muốn tìm hiểu điều gì?</h3>
                      <p className="ai-chat-empty-description">
                        Hỏi về xu hướng, so sánh chỉ số hoặc khám phá các biểu đồ trong dashboard này.
                      </p>
                      <div className="ai-chat-suggestions" aria-label="Câu hỏi gợi ý">
                        {suggestedQuestions.map(question => (
                          <button
                            type="button"
                            key={question}
                            onClick={() => {
                              setDraft(question);
                              inputRef.current?.focus();
                            }}
                          >
                            <ArrowUpRight aria-hidden="true" />{question}
                          </button>
                        ))}
                      </div>
                    </div>
                  </MessageScrollerItem>
                ) : (
                  messages.map(message => (
                    <MessageScrollerItem
                      key={message.id}
                      messageId={String(message.id)}
                      scrollAnchor={message.role === 'user'}
                    >
                      <Message align={message.role === 'user' ? 'end' : 'start'} className="ai-chat-turn">
                        <MessageAvatar className={`ai-chat-avatar is-${message.role}`}>
                          {message.role === 'user' ? 'B' : <Sparkles aria-hidden="true" />}
                        </MessageAvatar>
                        <MessageContent className="ai-chat-turn-content">
                          <MessageHeader className="ai-chat-sender">
                            {message.role === 'user' ? 'Bạn' : 'AI Agent'}
                          </MessageHeader>
                          <Bubble
                            align={message.role === 'user' ? 'end' : 'start'}
                            variant={message.role === 'user' ? 'tinted' : 'muted'}
                            className="ai-chat-bubble"
                          >
                            <BubbleContent className="ai-chat-bubble-content">
                              {message.progress?.some(item => item.kind === 'analysis_summary') ? <div className="ai-chat-analysis-summary">
                                {message.progress.find(item => item.kind === 'analysis_summary')?.text}
                              </div> : null}
                              {message.progress?.some(item => item.kind !== 'analysis_summary') ? <details className="ai-chat-progress-details" open={!message.isComplete}>
                                <summary>
                                  Chi tiết xử lý · {message.progress.filter(item => item.kind === 'tool_start').length} công cụ
                                </summary>
                                <ol className="ai-chat-progress" aria-label="Tiến trình Agent">
                                  {message.progress.filter(item => item.kind !== 'analysis_summary').map(item => <li key={item.id} className={`is-${item.kind}`}>{item.text}</li>)}
                                </ol>
                              </details> : null}
                              {message.role === 'assistant' ? <div className="ai-chat-markdown">
                                <ReactMarkdown
                                  remarkPlugins={[remarkGfm]}
                                  components={{ table: ({ children }) => <div className="ai-chat-table-wrap"><table>{children}</table></div> }}
                                >
                                  {message.content}
                                </ReactMarkdown>
                              </div> : message.content}
                              {message.charts?.map((chart, index) => <InlineChart key={`${message.id}-chart-${index}`} chart={chart} />)}
                            </BubbleContent>
                          </Bubble>
                        </MessageContent>
                      </Message>
                    </MessageScrollerItem>
                  ))
                )}
              </MessageScrollerContent>
            </MessageScrollerViewport>
            <MessageScrollerButton
              className="ai-chat-scroll-latest"
              variant="secondary"
              size="icon-sm"
            />
          </MessageScroller>
        </MessageScrollerProvider>

        <form
          className="ai-chat-composer"
          onSubmit={event => {
            event.preventDefault();
            sendMessage();
          }}
        >
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
              placeholder="Hỏi bất cứ điều gì về dữ liệu..."
              rows={2}
              aria-label="Tin nhắn cho AI"
            />
            <div className="ai-chat-composer-footer">
              <span><kbd>↵</kbd> gửi <span className="ai-chat-shortcut-dot">·</span> <kbd>⇧ ↵</kbd> xuống dòng</span>
              <Button type="submit" disabled={!draft.trim() || isStreaming} aria-label="Gửi tin nhắn" size="icon-lg">
                <svg viewBox="0 0 20 20" aria-hidden="true">
                  <path d="M2.2 9.1 17.5 2.5l-4.8 15-2.5-6.1-8-2.3Z" />
                  <path d="m10.2 11.4 4.1-4.1" />
                </svg>
              </Button>
            </div>
          </div>
        </form>
      </aside>}
    </>
  );
}
