import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowUp, BookMarked, FlaskConical, LayoutDashboard, LoaderCircle, MessageSquare, Pencil, Plus, Search, Sparkles,
  Square, Trash2,
} from 'lucide-react';
import {
  ChatSession, ChatStreamEvent, DashboardOption, UserDefinition, answerClarification,
  deleteDefinition, deleteSession, getSession, listDashboards, listDefinitions, listSessions, renameSession, streamChat,
  updateDefinition,
} from '../../shared/api/chat';
import {
  ClarificationHandlers, Turn, TurnView, applyStreamEvent, newTurn, turnFromStored,
} from './components/ChatTurn';
import { DefinitionsPanel } from './components/DefinitionsPanel';
import { canUseSchemaLinkLab } from '../../shared/api/schemaLink';
import { SchemaLinkLab } from '../schema-link/SchemaLinkLab';

export const AGENT_PAGE = '/ai-agent/';

export type ThemeMode = 'light' | 'dark' | 'system';

export function activeSupersetTheme(): ThemeMode {
  const luminance = (color: string) => {
    const match = color.match(/rgba?\(([^)]+)\)/i);
    if (!match) return null;
    const channels = match[1].split(/[ ,/]+/).filter(Boolean).map(Number);
    if (channels.length < 3 || channels.some(channel => !Number.isFinite(channel))) return null;
    if (channels.length > 3 && channels[3] === 0) return null;
    return (0.2126 * channels[0]) + (0.7152 * channels[1]) + (0.0722 * channels[2]);
  };

  const body = getComputedStyle(document.body);
  const backgroundLuminance = luminance(body.backgroundColor);
  if (backgroundLuminance !== null) return backgroundLuminance < 128 ? 'dark' : 'light';

  const textLuminance = luminance(body.color);
  if (textLuminance !== null) return textLuminance > 128 ? 'dark' : 'light';
  return 'system';
}

const sessionFromLocation = (): number | null => {
  const sessionId = Number(new URLSearchParams(window.location.search).get('session'));
  return Number.isInteger(sessionId) && sessionId > 0 ? sessionId : null;
};

const LAB_PAGE = '?lab=schema-link';
const labFromLocation = () => new URLSearchParams(window.location.search).get('lab') === 'schema-link';
const dashboardRefFromLocation = () => new URLSearchParams(window.location.search).get('dashboard');

const sessionHref = (sessionId: number | null) => (
  sessionId === null ? AGENT_PAGE : `${AGENT_PAGE}?session=${sessionId}`
);

const errorMessage = (error: unknown) => error instanceof Error ? error.message : String(error);

const DAY_MS = 24 * 60 * 60 * 1000;

/** Sidebar sections by how long ago a conversation was last active, newest first. */
function groupSessionsByRecency(sessions: ChatSession[]): Array<{ label: string; sessions: ChatSession[] }> {
  const startOfToday = new Date();
  startOfToday.setHours(0, 0, 0, 0);
  const sections = [
    { label: 'Hôm nay', since: startOfToday.getTime() },
    { label: 'Hôm qua', since: startOfToday.getTime() - DAY_MS },
    { label: '7 ngày qua', since: startOfToday.getTime() - 7 * DAY_MS },
    { label: '30 ngày qua', since: startOfToday.getTime() - 30 * DAY_MS },
    { label: 'Cũ hơn', since: Number.NEGATIVE_INFINITY },
  ];
  const groups = sections.map(section => ({ label: section.label, sessions: [] as ChatSession[] }));
  sessions.forEach(chatSession => {
    const updatedAt = new Date(chatSession.updated_on).getTime();
    groups[sections.findIndex(section => updatedAt >= section.since)].sessions.push(chatSession);
  });
  return groups.filter(group => group.sessions.length > 0);
}

function SessionTitle({ chatSession, onRename }: { chatSession: ChatSession; onRename: (title: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(chatSession.title);

  useEffect(() => { setTitle(chatSession.title); setEditing(false); }, [chatSession.id, chatSession.title]);

  const save = () => {
    setEditing(false);
    const trimmed = title.trim();
    if (trimmed && trimmed !== chatSession.title) onRename(trimmed);
    else setTitle(chatSession.title);
  };

  if (editing) {
    return (
      <input
        className="ai-page-title-input"
        value={title}
        maxLength={200}
        aria-label="Tên cuộc trò chuyện"
        autoFocus
        onChange={event => setTitle(event.target.value)}
        onBlur={save}
        onKeyDown={event => {
          if (event.key === 'Enter') save();
          if (event.key === 'Escape') { setTitle(chatSession.title); setEditing(false); }
        }}
      />
    );
  }
  return (
    <button type="button" className="ai-page-title" title="Đổi tên" onClick={() => setEditing(true)}>
      <h1>{chatSession.title}</h1>
      <Pencil aria-hidden="true" />
    </button>
  );
}

/**
 * The AI Agent page: the user's conversations on the left and the open one on the right. A conversation is about one
 * dashboard, chosen when it starts; the server keeps its turns, so reopening it shows every answer and step again.
 */
export function AgentPage() {
  const [themeMode, setThemeMode] = useState(activeSupersetTheme);
  const [sessions, setSessions] = useState<ChatSession[] | null>(null);
  const [sessionsError, setSessionsError] = useState('');
  const [sessionSearch, setSessionSearch] = useState('');
  const [dashboards, setDashboards] = useState<DashboardOption[] | null>(null);
  const [dashboardsError, setDashboardsError] = useState('');
  const [activeSessionId, setActiveSessionId] = useState<number | null>(sessionFromLocation);
  const [newChatDashboardId, setNewChatDashboardId] = useState<number | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [loadingSession, setLoadingSession] = useState(false);
  const [sessionError, setSessionError] = useState('');
  const [draft, setDraft] = useState('');
  const [definitions, setDefinitions] = useState<UserDefinition[]>([]);
  const [definitionsOpen, setDefinitionsOpen] = useState(false);
  // The schema link lab is for administrators; the link shows only once the API says the user may open it.
  const [labOpen, setLabOpen] = useState(labFromLocation);
  const [canUseLab, setCanUseLab] = useState<boolean | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // A conversation started by the running stream is already on screen and must not be reloaded over it.
  const streamedSessionRef = useRef<number | null>(null);
  const transcriptRef = useRef<HTMLDivElement>(null);
  const streaming = turns.some(turn => turn.state === 'streaming');
  useEffect(() => { void canUseSchemaLinkLab().then(setCanUseLab); }, []);
  const activeSession = sessions?.find(chatSession => chatSession.id === activeSessionId) ?? null;
  const newChatDashboard = dashboards?.find(dashboard => dashboard.id === newChatDashboardId) ?? null;

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const syncTheme = () => setThemeMode(activeSupersetTheme());
    const observer = new MutationObserver(syncTheme);
    observer.observe(document.body, { attributes: true, attributeFilter: ['class', 'style', 'data-theme'] });
    observer.observe(document.head, { childList: true });
    const onPopState = () => {
      abortRef.current?.abort();
      setLabOpen(labFromLocation());
      setActiveSessionId(sessionFromLocation());
    };
    window.addEventListener('popstate', onPopState);
    return () => {
      observer.disconnect();
      window.removeEventListener('popstate', onPopState);
      document.body.style.overflow = previousOverflow;
      abortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    listSessions().then(setSessions).catch(error => setSessionsError(errorMessage(error)));
    listDashboards().then(setDashboards).catch(error => setDashboardsError(errorMessage(error)));
  }, []);

  // Opened from a dashboard: a new conversation starts about that dashboard.
  useEffect(() => {
    const dashboardRef = dashboardRefFromLocation();
    if (!dashboards || !dashboardRef) return;
    const linked = dashboards.find(dashboard => (
      String(dashboard.id) === dashboardRef || dashboard.slug === dashboardRef
    ));
    if (linked) setNewChatDashboardId(linked.id);
  }, [dashboards]);

  useEffect(() => {
    setSessionError('');
    if (activeSessionId === null) {
      setTurns([]);
      return undefined;
    }
    if (streamedSessionRef.current === activeSessionId) return undefined;
    let active = true;
    setLoadingSession(true);
    setTurns([]);
    setDefinitions([]);
    getSession(activeSessionId)
      .then(chatSession => {
        if (!active) return;
        setTurns(chatSession.turns.map(turnFromStored));
        setDefinitions(chatSession.definitions);
      })
      .catch(error => { if (active) setSessionError(errorMessage(error)); })
      .finally(() => { if (active) setLoadingSession(false); });
    return () => { active = false; };
  }, [activeSessionId]);

  // A new conversation already uses what the user confirmed on the chosen dashboard.
  useEffect(() => {
    if (activeSessionId !== null) return undefined;
    setDefinitions([]);
    if (newChatDashboardId === null) return undefined;
    let active = true;
    listDefinitions(newChatDashboardId).then(items => { if (active) setDefinitions(items); }).catch(() => undefined);
    return () => { active = false; };
  }, [activeSessionId, newChatDashboardId]);

  useEffect(() => {
    transcriptRef.current?.scrollTo({ top: transcriptRef.current.scrollHeight });
  }, [turns]);

  const navigate = (sessionId: number | null) => {
    if (sessionId === activeSessionId && !labOpen) return;
    setLabOpen(false);
    abortRef.current?.abort();
    streamedSessionRef.current = null;
    window.history.pushState(null, '', sessionHref(sessionId));
    setActiveSessionId(sessionId);
  };

  const startNewChat = () => {
    if (activeSession) setNewChatDashboardId(activeSession.dashboard_id);
    navigate(null);
  };

  const upsertSession = (chatSession: ChatSession) => setSessions(current => [
    chatSession,
    ...(current ?? []).filter(item => item.id !== chatSession.id),
  ]);

  const updateTurn = (turnId: number, change: (turn: Turn) => Turn) => {
    setTurns(current => current.map(turn => turn.id === turnId ? change(turn) : turn));
  };

  const onStreamEvent = (turnId: number, event: ChatStreamEvent) => {
    if (event.name === 'session') {
      const known = sessions?.find(chatSession => chatSession.id === event.data.id);
      const now = new Date().toISOString();
      const dashboardTitle = dashboards?.find(dashboard => dashboard.id === event.data.dashboard_id)?.title ?? null;
      upsertSession(known ? { ...known, updated_on: now } : {
        ...event.data, dashboard_title: dashboardTitle, created_on: now, updated_on: now,
      });
      if (!known) {
        streamedSessionRef.current = event.data.id;
        window.history.pushState(null, '', sessionHref(event.data.id));
        setActiveSessionId(event.data.id);
      }
      return;
    }
    updateTurn(turnId, turn => applyStreamEvent(turn, event));
  };

  /** Ask the draft, or with `retryOf` answer that earlier question again once the user confirmed definitions. */
  const ask = async (text = draft, retryOf: number | null = null) => {
    const question = text.trim();
    if (!question || streaming || (activeSessionId === null && newChatDashboardId === null)) return;
    const turn = newTurn(question, retryOf);
    const turnId = turn.id;
    const controller = new AbortController();
    abortRef.current = controller;
    if (retryOf === null) setDraft('');
    setTurns(current => [...current, turn]);
    try {
      const request = {
        sessionId: activeSessionId, dashboardId: newChatDashboardId, question, retryOf: retryOf ?? undefined,
      };
      await streamChat({ ...request, signal: controller.signal }, event => onStreamEvent(turnId, event));
      updateTurn(turnId, turn => turn.state === 'streaming'
        ? { ...turn, state: 'error', error: 'Kết nối bị ngắt.' }
        : turn);
    } catch (error) {
      const stopped = controller.signal.aborted;
      updateTurn(turnId, turn => stopped
        ? { ...turn, state: 'stopped' }
        : { ...turn, state: 'error', error: errorMessage(error) });
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
    }
  };

  const settleClarification = (turn: Turn, state: 'confirmed' | 'dismissed') => {
    updateTurn(turn.id, current => ({ ...current, clarificationState: state }));
  };

  const clarificationHandlers: ClarificationHandlers = {
    onConfirm: async (turn, confirmed) => {
      if (activeSessionId === null || turn.questionId === undefined) return;
      try {
        setDefinitions(await answerClarification(activeSessionId, turn.questionId, 'confirmed', confirmed));
      } catch (error) {
        window.alert(`Không lưu được cách hiểu: ${errorMessage(error)}`);
        return;
      }
      settleClarification(turn, 'confirmed');
      void ask(turn.question, turn.questionId);
    },
    onDismiss: async turn => {
      if (activeSessionId === null || turn.questionId === undefined) return;
      try {
        await answerClarification(activeSessionId, turn.questionId, 'dismissed');
      } catch (error) {
        window.alert(`Không lưu được: ${errorMessage(error)}`);
        return;
      }
      settleClarification(turn, 'dismissed');
    },
  };

  const saveDefinition = async (definition: UserDefinition, change: { name: string; definition: string }) => {
    try {
      const saved = await updateDefinition(definition.id, change);
      setDefinitions(current => current.map(item => item.id === saved.id ? saved : item));
    } catch (error) {
      window.alert(`Không lưu được định nghĩa: ${errorMessage(error)}`);
    }
  };

  const removeDefinition = async (definition: UserDefinition) => {
    try {
      await deleteDefinition(definition.id);
      setDefinitions(current => current.filter(item => item.id !== definition.id));
    } catch (error) {
      window.alert(`Không xoá được định nghĩa: ${errorMessage(error)}`);
    }
  };

  const rename = async (chatSession: ChatSession, title: string) => {
    try {
      const renamed = await renameSession(chatSession.id, title);
      setSessions(current => current?.map(item => item.id === renamed.id ? renamed : item) ?? null);
    } catch (error) {
      window.alert(`Không đổi được tên: ${errorMessage(error)}`);
    }
  };

  const remove = async (chatSession: ChatSession) => {
    if (!window.confirm(`Xoá cuộc trò chuyện “${chatSession.title}”?`)) return;
    try {
      await deleteSession(chatSession.id);
      setSessions(current => current?.filter(item => item.id !== chatSession.id) ?? null);
      if (chatSession.id === activeSessionId) startNewChat();
    } catch (error) {
      window.alert(`Không xoá được cuộc trò chuyện: ${errorMessage(error)}`);
    }
  };

  const visibleGroups = useMemo(() => {
    const query = sessionSearch.trim().toLocaleLowerCase('vi');
    const matching = (sessions ?? []).filter(chatSession => !query
      || chatSession.title.toLocaleLowerCase('vi').includes(query)
      || (chatSession.dashboard_title ?? '').toLocaleLowerCase('vi').includes(query));
    return groupSessionsByRecency(matching);
  }, [sessions, sessionSearch]);

  const canAsk = activeSessionId !== null || newChatDashboard !== null;
  const canSend = canAsk && draft.trim() !== '';
  const stop = () => abortRef.current?.abort();
  const composer = (
    <form className="ai-page-composer" onSubmit={event => { event.preventDefault(); void ask(); }}>
      <div className="ai-chat-composer-box">
        <textarea
          value={draft}
          rows={2}
          maxLength={2000}
          disabled={!canAsk}
          placeholder={canAsk
            ? 'Hỏi về dữ liệu… (Enter để gửi, Shift+Enter xuống dòng)'
            : 'Chọn dashboard để bắt đầu hỏi'}
          aria-label="Câu hỏi"
          onChange={event => setDraft(event.target.value)}
          onKeyDown={event => {
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              void ask();
            }
          }}
        />
        {streaming ? (
          <button type="button" className="ai-chat-send" title="Dừng" aria-label="Dừng" onClick={stop}>
            <Square aria-hidden="true" />
          </button>
        ) : (
          <button type="submit" className="ai-chat-send" title="Gửi" aria-label="Gửi" disabled={!canSend}>
            <ArrowUp aria-hidden="true" />
          </button>
        )}
      </div>
      <p className="ai-page-composer-note">
        AI Agent có thể sai; khái niệm chưa có định nghĩa chung sẽ được hỏi lại bạn.
      </p>
    </form>
  );

  return (
    <div className="ai-page" data-theme-mode={themeMode}>
      <aside className="ai-page-sidebar" aria-label="Cuộc trò chuyện">
        <button type="button" className="ai-page-new-chat" onClick={startNewChat}>
          <Plus aria-hidden="true" /> Cuộc trò chuyện mới
        </button>
        {canUseLab === true ? (
          <a
            className={`ai-page-lab-link${labOpen ? ' is-active' : ''}`}
            href={`${AGENT_PAGE}${LAB_PAGE}`}
            onClick={event => {
              event.preventDefault();
              abortRef.current?.abort();
              window.history.pushState(null, '', `${AGENT_PAGE}${LAB_PAGE}`);
              setLabOpen(true);
            }}
          >
            <FlaskConical aria-hidden="true" /> Thử phân tích dữ liệu
          </a>
        ) : null}
        <label className="ai-page-search">
          <Search aria-hidden="true" />
          <input
            type="search"
            value={sessionSearch}
            placeholder="Tìm cuộc trò chuyện"
            aria-label="Tìm cuộc trò chuyện"
            onChange={event => setSessionSearch(event.target.value)}
          />
        </label>
        <nav className="ai-page-sessions">
          {sessions === null && !sessionsError ? (
            <p className="ai-page-sessions-state"><LoaderCircle className="ai-spin" aria-hidden="true" /> Đang tải…</p>
          ) : null}
          {sessionsError ? <p className="ai-page-sessions-state is-error">{sessionsError}</p> : null}
          {sessions?.length === 0 ? <p className="ai-page-sessions-state">Chưa có cuộc trò chuyện nào.</p> : null}
          {sessions && sessions.length > 0 && visibleGroups.length === 0 ? (
            <p className="ai-page-sessions-state">Không có cuộc trò chuyện phù hợp.</p>
          ) : null}
          {visibleGroups.map(group => (
            <section key={group.label} className="ai-page-session-group">
              <h2>{group.label}</h2>
              <ul>
                {group.sessions.map(chatSession => (
                  <li key={chatSession.id} className={chatSession.id === activeSessionId ? 'is-active' : undefined}>
                    <a
                      href={sessionHref(chatSession.id)}
                      aria-current={chatSession.id === activeSessionId ? 'page' : undefined}
                      onClick={event => { event.preventDefault(); navigate(chatSession.id); }}
                    >
                      <span className="ai-page-session-title">{chatSession.title}</span>
                      <span className="ai-page-session-dashboard">
                        {chatSession.dashboard_title ?? 'Dashboard đã xoá'}
                      </span>
                    </a>
                    <button
                      type="button"
                      className="ai-page-session-delete"
                      title="Xoá cuộc trò chuyện"
                      aria-label={`Xoá cuộc trò chuyện ${chatSession.title}`}
                      onClick={() => void remove(chatSession)}
                    >
                      <Trash2 aria-hidden="true" />
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </nav>
      </aside>

      <main className="ai-page-main">
        {labOpen ? (
          <div className="ai-page-lab-scroll">
            {canUseLab === null ? (
              <p className="ai-page-state"><LoaderCircle className="ai-spin" aria-hidden="true" /> Đang tải…</p>
            ) : null}
            {canUseLab === true ? <SchemaLinkLab /> : null}
            {canUseLab === false ? (
              <p className="ai-page-state">Chỉ quản trị viên dùng được phòng thử phân tích.</p>
            ) : null}
          </div>
        ) : activeSessionId === null ? (
          <div className="ai-page-start">
            <span className="ai-chat-mark" aria-hidden="true"><Sparkles /></span>
            <h1>Hỏi AI Agent về dữ liệu</h1>
            <p>
              Chọn dashboard cho cuộc trò chuyện. AI Agent xác định thuật ngữ, metric và expert rule cho từng câu hỏi.
            </p>
            <label className={`ai-chat-context${newChatDashboard ? ' is-attached' : ''}`}>
              <LayoutDashboard aria-hidden="true" />
              <span className="ai-chat-context-label">Dashboard</span>
              <select
                value={newChatDashboardId ?? ''}
                disabled={dashboards === null || streaming}
                onChange={event => setNewChatDashboardId(event.target.value ? Number(event.target.value) : null)}
              >
                <option value="">{dashboards === null ? 'Đang tải dashboard…' : 'Chọn dashboard để hỏi'}</option>
                {dashboards?.map(dashboard => (
                  <option key={dashboard.id} value={dashboard.id}>{dashboard.title}</option>
                ))}
              </select>
            </label>
            {dashboardsError ? (
              <p className="ai-chat-context-error">Không tải được dashboard: {dashboardsError}</p>
            ) : null}
            {turns.length > 0 ? (
              <div className="ai-page-transcript is-starting" ref={transcriptRef}>
                {turns.map(turn => <TurnView key={turn.id} turn={turn} />)}
              </div>
            ) : null}
            {composer}
          </div>
        ) : (
          <>
            <header className="ai-page-header">
              <div className="ai-page-header-copy">
                {activeSession ? (
                  <SessionTitle chatSession={activeSession} onRename={title => void rename(activeSession, title)} />
                ) : <h1 className="ai-page-title-placeholder">Cuộc trò chuyện</h1>}
                {activeSession ? (
                  <a className="ai-page-dashboard-chip" href={`/superset/dashboard/${activeSession.dashboard_id}/`}>
                    <LayoutDashboard aria-hidden="true" />
                    {activeSession.dashboard_title ?? 'Dashboard đã xoá'}
                  </a>
                ) : null}
              </div>
              {activeSession ? (
                <button
                  type="button"
                  className={`ai-page-definitions-toggle${definitionsOpen ? ' is-open' : ''}`}
                  aria-expanded={definitionsOpen}
                  onClick={() => setDefinitionsOpen(open => !open)}
                >
                  <BookMarked aria-hidden="true" /> Cách hiểu của bạn
                  {definitions.length > 0 ? <span className="ai-page-count">{definitions.length}</span> : null}
                </button>
              ) : null}
              {activeSession ? (
                <button
                  type="button"
                  className="ai-chat-icon-button"
                  title="Xoá cuộc trò chuyện"
                  aria-label="Xoá cuộc trò chuyện"
                  onClick={() => void remove(activeSession)}
                >
                  <Trash2 aria-hidden="true" />
                </button>
              ) : null}
            </header>
            <div className="ai-page-transcript" ref={transcriptRef}>
              <div className="ai-page-column">
                {loadingSession ? (
                  <p className="ai-page-state"><LoaderCircle className="ai-spin" aria-hidden="true" /> Đang tải…</p>
                ) : null}
                {sessionError ? (
                  <div className="ai-page-state is-error">
                    <MessageSquare aria-hidden="true" />
                    <p>Không mở được cuộc trò chuyện: {sessionError}</p>
                  </div>
                ) : null}
                {turns.map(turn => (
                  <TurnView key={turn.id} turn={turn} clarificationHandlers={clarificationHandlers} />
                ))}
              </div>
            </div>
            {sessionError ? null : <div className="ai-page-column">{composer}</div>}
          </>
        )}
      </main>
      {activeSession && definitionsOpen ? (
        <DefinitionsPanel
          definitions={definitions}
          onSave={saveDefinition}
          onDelete={removeDefinition}
          onClose={() => setDefinitionsOpen(false)}
        />
      ) : null}
    </div>
  );
}
