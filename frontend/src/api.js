import { auth } from './store';

const RETRYABLE_STATUS = new Set([408, 425, 429, 502, 503, 504]);
const MAX_RETRIES = 3;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function api(path, { method = 'GET', body, withAuth = false } = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (withAuth && auth.token) headers.Authorization = `Bearer ${auth.token}`;

  // Idempotent methods get retried. POST/PATCH/DELETE fail fast so we never
  // double-submit a stamp request or signup.
  const retryable = method === 'GET' || method === 'HEAD';
  const attempts = retryable ? MAX_RETRIES : 1;

  let lastErr;

  for (let i = 0; i < attempts; i++) {
    try {
      const res = await fetch(path, {
        method,
        headers,
        body: body ? JSON.stringify(body) : undefined,
      });

      if (!res.ok && retryable && RETRYABLE_STATUS.has(res.status) && i < attempts - 1) {
        await sleep(250 * 2 ** i);  // 250ms, 500ms, 1s
        continue;
      }

      const txt = await res.text();
      const data = txt ? JSON.parse(txt) : null;

      if (!res.ok) {
        const err = new Error(data?.detail || res.statusText);
        err.status = res.status;
        err.detail = data?.detail;
        throw err;
      }
      return data;
    } catch (e) {
      // fetch() throws on network failure (offline, DNS, TLS) — retry those too.
      const isNetwork = !e.status;
      if (retryable && isNetwork && i < attempts - 1) {
        lastErr = e;
        await sleep(250 * 2 ** i);
        continue;
      }
      throw e;
    }
  }

  throw lastErr || new Error('Request failed after retries');
}
