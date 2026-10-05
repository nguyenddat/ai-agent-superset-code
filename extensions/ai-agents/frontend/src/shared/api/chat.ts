export type InlineChartPayload = {
  title: string;
  src: string;
};

export type ChatStreamEvent = {
  token?: string;
  message?: string;
  summary?: string;
  tool?: string;
  output?: string;
  chart?: InlineChartPayload;
};

async function getJson(path: string) {
  const response = await fetch(path, { credentials: 'same-origin' });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`);
  return body.result ?? body;
}

export async function streamChat(dashboardRef: string, query: string, onEvent: (name: string, data: ChatStreamEvent) => void) {
  const [user, dashboard, csrf] = await Promise.all([
    getJson('/api/v1/me/'),
    getJson(`/api/v1/dashboard/${encodeURIComponent(dashboardRef)}`),
    getJson('/api/v1/security/csrf_token/'),
  ]);
  const response = await fetch('/api/v1/chat/stream', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
    body: JSON.stringify({ user_id: user.id, dashboard_id: dashboard.id, query }),
  });
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error || `Chat request failed (${response.status})`);
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
