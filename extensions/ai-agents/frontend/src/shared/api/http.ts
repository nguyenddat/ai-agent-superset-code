/** GET as the signed-in user; the body's `result` when it has one, the body otherwise. */
export async function getJson(path: string) {
  const response = await fetch(path, { credentials: 'same-origin' });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || body.message || `Request failed (${response.status})`);
  return body.result ?? body;
}

/** A write as the signed-in user, with the CSRF token Superset asks for. */
export async function sendJson(path: string, method: 'POST' | 'PUT' | 'DELETE', payload?: unknown) {
  const csrf = await getJson('/api/v1/security/csrf_token/');
  const response = await fetch(path, {
    method,
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || body.message || `Request failed (${response.status})`);
  return body.result ?? body;
}
