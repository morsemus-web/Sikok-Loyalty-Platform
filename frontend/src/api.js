import { auth } from './store';

export async function api(path, { method = 'GET', body, withAuth = false } = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (withAuth && auth.token) headers.Authorization = `Bearer ${auth.token}`;

  const res = await fetch(path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  const txt = await res.text();
  const data = txt ? JSON.parse(txt) : null;

  if (!res.ok) {
    const err = new Error(data?.detail || res.statusText);
    err.status = res.status;
    err.detail = data?.detail;
    throw err;
  }
  return data;
}
