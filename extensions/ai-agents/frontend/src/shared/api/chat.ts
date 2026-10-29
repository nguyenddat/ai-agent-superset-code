import { getJson, sendJson } from './http';

export type QuestionStatus = 'resolved' | 'needs_review' | 'failed';
export type MissingKind = 'glossary' | 'metric' | 'expert_rule';

export type ToolStartEvent = { id: string; name: string; arguments: Record<string, unknown> };
export type ToolEndEvent = {
  id: string;
  name: string;
  status: 'ok' | 'error';
  result?: unknown;
  error?: string;
  duration_ms: number;
};
export type DefinitionKind = 'glossary' | 'expert_rule';

export type DefinitionOption = { label: string; definition: string };

/** A question back to the user about a concept the agent could not find, with ways to read it, likeliest first. */
export type DefinitionDraft = {
  kind: DefinitionKind;
  concept: string | null;
  name: string;
  question: string;
  options: DefinitionOption[];
};

/** What the user answered to one question: the option they chose or their own words. */
export type ConfirmedDefinition = { kind: DefinitionKind; concept: string | null; name: string; definition: string };

/** A condition stored with a definition: the column, its business name, the comparison and the threshold. */
export type DefinitionCondition = { column: string; label: string; operator: string; value: ResultCell | ResultCell[] };

/** A definition the user confirmed; the agent uses it in all their conversations about the dashboard. */
export type UserDefinition = ConfirmedDefinition & {
  id: number;
  /** For a qualitative concept, the conditions every later question applies; null when none could be stored. */
  conditions: { dataset_id: number; filters: DefinitionCondition[] } | null;
  dashboard_id: number;
  source_question_id: number | null;
  /** `promoted` once administrators cover the concept with a shared term or rule. */
  review_status: 'pending' | 'promoted' | 'ignored';
  updated_on: string;
};

export type UsedDefinition = { id: number; kind: DefinitionKind; name: string; definition: string };

export type FilterSource = 'expert_rule' | 'user_definition' | 'time' | 'place' | 'question';
export type ResultCell = string | number | null;

/** One condition of the metric query, with the label of a key value when it has one. */
export type ResultFilter = {
  column: string;
  label: string;
  operator: '==' | '!=' | '<' | '<=' | '>' | '>=' | 'IN' | 'NOT IN';
  value: ResultCell | ResultCell[];
  shown_value: ResultCell | ResultCell[];
  source: FilterSource;
};

/** What the approved metrics answered: a row per dimension value, a column per metric. */
export type Coverage = { column: string; min: string; max: string; start: string; end: string;
  status: 'full' | 'partial' | 'none' };

/** A piece of a formula sentence: plain text, or a column shown by its business label or its physical name. */
export type FormulaPart = { text: string } | { column: string; label: string };

export type QueryResult = {
  scope: string;
  presentation: 'number' | 'table' | 'bar' | 'line';
  dimensions: Array<{ name: string; label: string; temporal: boolean }>;
  /** `compared_name` is the row key of the metric's value in the compared period, when there is one. */
  metrics: Array<{
    name: string; label: string; unit: string | null; format: string | null; compared_name?: string | null;
  }>;
  filters: ResultFilter[];
  rows: Array<Record<string, ResultCell>>;
  row_count: number;
  total_rows?: number;
  truncated: boolean;
  order?: { metric_name: string; label: string; direction: 'asc' | 'desc' } | null;
  limit?: number | null;
  comparison?: { label: string; start: string; end: string; coverage: Coverage | null } | null;
  coverage?: Coverage | null;
  notes: string[];
  /** True when the metric is one the agent built on an aggregate dataset that no administrator has approved yet. */
  provisional?: boolean;
  /**
   * How a provisional metric computes its figure: a sentence of text and columns, or null parts when the formula is
   * beyond what a sentence tells faithfully, so only the expression is shown.
   */
  formula?: { expression: string; parts: FormulaPart[] | null };
  /** A provisional figure that looks like a wrong formula: no matching rows, or only zeros. */
  doubt?: 'empty' | 'zero' | null;
  /** What the agent asked the Semantic Layer for each metric; `sql` only when it shows it (to administrators). */
  queries?: Array<{
    metric: string;
    /** The compared period's label, or null for the period asked about. */
    period?: string | null;
    dataset_id: number;
    metric_id: number;
    request: { dimensions: string[]; filters: Array<{ column: string; operator: string; value: unknown }> };
    sql: string | null;
  }>;
};

export type DoneEvent = {
  question_id: number | null;
  status: QuestionStatus;
  missing: MissingKind[];
  clarifications: DefinitionDraft[];
  user_definitions: UsedDefinition[];
  result: QueryResult | null;
  query_error: string | null;
};

export type SessionEvent = { id: number; title: string; dashboard_id: number };

export type ChatStreamEvent =
  | { name: 'session'; data: SessionEvent }
  | { name: 'tool_start'; data: ToolStartEvent }
  | { name: 'tool_end'; data: ToolEndEvent }
  | { name: 'result'; data: QueryResult }
  | { name: 'token'; data: { text: string } }
  | { name: 'error'; data: { message: string } }
  | { name: 'done'; data: DoneEvent };

export type ChatSession = {
  id: number;
  title: string;
  dashboard_id: number;
  dashboard_title: string | null;
  created_on: string;
  updated_on: string;
};

export type StoredToolCall = ToolStartEvent & Partial<Omit<ToolEndEvent, 'status'>> & {
  status: 'running' | 'ok' | 'error';
};

export type StoredTurn = {
  id: number;
  question: string;
  answer: string;
  tool_calls: StoredToolCall[];
  status: QuestionStatus;
  missing: MissingKind[];
  error: string | null;
  clarifications: DefinitionDraft[];
  clarification_state: ClarificationState | null;
  retry_of: number | null;
  result: QueryResult | null;
  asked_on: string;
};

export type ClarificationState = 'pending' | 'confirmed' | 'dismissed';

const AGENT_API = '/extensions/text-to-bi/superset-ai-agent';
const CHAT_ENDPOINT = `${AGENT_API}/chat/stream`;
const SESSIONS_ENDPOINT = `${AGENT_API}/sessions`;
const DEFINITIONS_ENDPOINT = `${AGENT_API}/definitions`;

/** The signed-in user's conversations, most recently active first. */
export function listSessions(): Promise<ChatSession[]> {
  return getJson(`${SESSIONS_ENDPOINT}/`);
}

/** One conversation with its turns and the definitions the user confirmed on its dashboard. */
export function getSession(
  sessionId: number,
): Promise<ChatSession & { turns: StoredTurn[]; definitions: UserDefinition[] }> {
  return getJson(`${SESSIONS_ENDPOINT}/${sessionId}`);
}

/** Keep what the user answered for their conversations about the dashboard; or dismiss the questions. */
export function answerClarification(
  sessionId: number, questionId: number, state: 'confirmed' | 'dismissed', definitions: ConfirmedDefinition[] = [],
): Promise<UserDefinition[]> {
  const path = `${SESSIONS_ENDPOINT}/${sessionId}/questions/${questionId}/clarification`;
  return sendJson(path, 'PUT', { state, definitions });
}

/** What the user confirmed concepts mean on a dashboard. */
export function listDefinitions(dashboardId: number): Promise<UserDefinition[]> {
  return getJson(`${DEFINITIONS_ENDPOINT}/?dashboard_id=${dashboardId}`);
}

export function updateDefinition(
  definitionId: number, change: { name: string; definition: string },
): Promise<UserDefinition> {
  return sendJson(`${DEFINITIONS_ENDPOINT}/${definitionId}`, 'PUT', change);
}

export async function deleteDefinition(definitionId: number): Promise<void> {
  await sendJson(`${DEFINITIONS_ENDPOINT}/${definitionId}`, 'DELETE');
}

export function renameSession(sessionId: number, title: string): Promise<ChatSession> {
  return sendJson(`${SESSIONS_ENDPOINT}/${sessionId}`, 'PUT', { title });
}

export async function deleteSession(sessionId: number): Promise<void> {
  await sendJson(`${SESSIONS_ENDPOINT}/${sessionId}`, 'DELETE');
}

export type DashboardOption = { id: number; title: string; slug: string | null };

// The AI Agent's own question statistics are not a dashboard to ask about.
const HIDDEN_DASHBOARD_SLUGS = new Set(['ai-agent-tong-quan']);
const DASHBOARD_QUERY = '(columns:!(id,dashboard_title,slug),'
  + 'order_column:dashboard_title,order_direction:asc,page_size:100)';

/** The dashboards this user may open, which are the ones a question can be attached to. */
export async function listDashboards(): Promise<DashboardOption[]> {
  const dashboards: Array<{ id: number; dashboard_title: string; slug: string | null }> = await getJson(
    `/api/v1/dashboard/?q=${encodeURIComponent(DASHBOARD_QUERY)}`,
  );
  return dashboards
    .filter(dashboard => !dashboard.slug || !HIDDEN_DASHBOARD_SLUGS.has(dashboard.slug))
    .map(dashboard => ({ id: dashboard.id, title: dashboard.dashboard_title, slug: dashboard.slug }));
}

/**
 * Ask one question in a conversation, or start one about `dashboardId` when there is no `sessionId` yet; `retryOf`
 * answers an earlier question again once the user confirmed definitions. The server keeps the conversation's history;
 * each event it streams goes to `onEvent`, starting with `session`.
 */
export async function streamChat(
  request: {
    sessionId: number | null; dashboardId: number | null; question: string; retryOf?: number; signal: AbortSignal;
  },
  onEvent: (event: ChatStreamEvent) => void,
) {
  const csrf = await getJson('/api/v1/security/csrf_token/');
  const response = await fetch(CHAT_ENDPOINT, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
    body: JSON.stringify(request.sessionId === null
      ? { dashboard_id: request.dashboardId, question: request.question }
      : { session_id: request.sessionId, question: request.question, retry_of: request.retryOf }),
    signal: request.signal,
  });
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error || body.message || body.msg || `Chat request failed (${response.status})`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  const dispatch = (frame: string) => {
    const lines = frame.split(/\r?\n/);
    const name = lines.find(line => line.startsWith('event:'))?.slice(6).trim();
    const data = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trim()).join('\n');
    if (name && data) onEvent({ name, data: JSON.parse(data) } as ChatStreamEvent);
  };

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const frames = buffer.split(/\r?\n\r?\n/);
    buffer = frames.pop() || '';
    frames.forEach(dispatch);
    if (done) break;
  }
  if (buffer.trim()) dispatch(buffer);
}
