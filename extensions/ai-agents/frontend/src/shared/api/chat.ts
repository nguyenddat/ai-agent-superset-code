export type BIContract = {
  user_intent: { objective: string };
  data_resolve: {
    sources: Array<{
      dataset_id: number;
      columns: string[];
      metrics: Array<{ name: string; aggregation: string | null }>;
      filters: Array<{ field: string; operator: string; value: string | string[] }>;
      group_by: string[];
    }>;
    combination: 'single' | 'independent' | 'join';
    combination_key: string[];
    time_range: string | null;
    time_grain: string | null;
    order_by: string[];
  };
  chart_resolve: {
    mode: 'auto' | 'chart' | 'table' | 'single_value';
    viz_type: string | null;
    data_shape: 'raw' | 'aggregated' | 'scalar';
    data_grain: string;
    x_axis: string | null;
    y_axis: string[];
    series: string | null;
    time_comparison?: 'previous_day' | null;
    title: string | null;
  };
};

export type ValidationError = { code: string; path: string; message: string };

export type MetadataResolution = {
  status: 'ready' | 'unsupported';
  chart_type: string | null;
  viz_type: string | null;
  dataset_id: number | null;
  config: Record<string, unknown>;
  time_range: string | null;
  message: string;
};

export type ChatStreamEvent = {
  token?: string;
  message?: string;
  tool?: string;
  output?: string;
  contract?: BIContract;
  resolution?: MetadataResolution | null;
  sql?: string | null;
  chart_url?: string | null;
  chart_error?: string | null;
  summary?: { column_count: number; columns: Array<{ name: string; type?: string | null }>; row_count: number } | null;
  success?: boolean;
  errors?: ValidationError[];
  attempts?: number;
  attempt?: number;
  dashboard_title?: string;
  authorized_dataset_count?: number;
  datasets?: Record<string, string>;
};

const CHAT_ENDPOINT = '/extensions/text-to-bi/text-to-bi-code/chat/stream';

export function currentDashboardRef(): string | null {
  const match = window.location.pathname.match(/\/dashboard\/([^/?#]+)/);
  return match && match[1] !== 'list' ? decodeURIComponent(match[1]) : null;
}

async function getJson(path: string) {
  const response = await fetch(path, { credentials: 'same-origin' });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`);
  return body.result ?? body;
}

export async function streamChat(dashboardRef: string, query: string, onEvent: (name: string, data: ChatStreamEvent) => void) {
  const [dashboard, csrf] = await Promise.all([
    getJson(`/api/v1/dashboard/${encodeURIComponent(dashboardRef)}`),
    getJson('/api/v1/security/csrf_token/'),
  ]);
  const response = await fetch(CHAT_ENDPOINT, {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
    body: JSON.stringify({ dashboard_id: dashboard.id, query }),
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
    const name = lines.find(line => line.startsWith('event:'))?.slice(6).trim() || 'message';
    const data = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trim()).join('\n');
    if (data) onEvent(name, JSON.parse(data));
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
