// API client.
// GET  : network first; on success cached in IndexedDB; on network failure the cached copy is
//        returned and the app switches to read-only "offline" mode.
// Write: always sends an Idempotency-Key (uuid). Offline → refused with a clear message (no silent save).
import { cacheGet, cachePut } from './idb.js';
import { t, lang } from './i18n.js';

let offline = false;
const listeners = new Set();
export const isOffline = () => offline;
export function onOfflineChange(fn) { listeners.add(fn); }
function setOffline(v) {
  if (offline === v) return;
  offline = v;
  listeners.forEach(fn => fn(v));
}
window.addEventListener('online', () => setOffline(false));
window.addEventListener('offline', () => setOffline(true));

export function uuid() {
  if (crypto.randomUUID) return crypto.randomUUID();
  return ([1e7] + -1e3 + -4e3 + -8e3 + -1e11).replace(/[018]/g, c =>
    (c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16));
}

export class ApiError extends Error {
  constructor(status, body) {
    super((body && (lang === 'en' ? body.message_en : body.message)) || `HTTP ${status}`);
    this.status = status;
    this.body = body || {};
  }
  get details() { return this.body.details; }
  get code() { return this.body.error; }
}

export async function get(url) {
  let res;
  try {
    res = await fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
  } catch (e) {
    const cached = await cacheGet(url);
    setOffline(true);
    if (cached) return cached.data;
    throw new ApiError(0, { message: t('لا يوجد اتصال، ولا نسخة محفوظة من هذه البيانات'),
                             message_en: 'Offline and no saved copy of this data' });
  }
  if (res.status === 401) { location.href = '/auth/login?next=/'; throw new ApiError(401, {}); }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, body);
  setOffline(false);
  cachePut(url, body);
  return body;
}

async function write(method, url, body, { key } = {}) {
  if (offline || navigator.onLine === false) {
    throw new ApiError(0, { error: 'offline', message: 'لا يوجد اتصال، لا يمكن الحفظ الآن',
                             message_en: 'No connection — cannot save right now' });
  }
  let res;
  try {
    res = await fetch(url, {
      method, credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'Idempotency-Key': key || uuid() },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (e) {
    setOffline(true);
    throw new ApiError(0, { error: 'offline', message: 'لا يوجد اتصال، لا يمكن الحفظ الآن',
                             message_en: 'No connection — cannot save right now' });
  }
  if (res.status === 401) { location.href = '/auth/login?next=/'; throw new ApiError(401, {}); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

export const post = (url, body, opts) => write('POST', url, body ?? {}, opts);
export const patch = (url, body, opts) => write('PATCH', url, body, opts);
export const put = (url, body, opts) => write('PUT', url, body, opts);
export const del = (url, version, opts) => write('DELETE', `${url}?version=${version}`, undefined, opts);

/** Human-readable error text including per-field / per-conflict details. */
export function errorText(e) {
  if (!(e instanceof ApiError)) return String(e && e.message || e);
  const d = e.details;
  const lines = [e.message];
  if (Array.isArray(d)) {
    d.slice(1, 4).forEach(c => lines.push(lang === 'en' ? (c.message_en || c.message || c.code) : (c.message || c.code)));
  } else if (d && typeof d === 'object') {
    if (d.message) lines.push(d.message);
    else if (d.field) lines.push(`${t('الحقل')}: ${d.field}${d.reason ? ' — ' + d.reason : ''}`);
    else if (e.code === 'has_dependents') lines.push(Object.entries(d).map(([k, v]) => `${t(k)}: ${v}`).join('، '));
  }
  return lines.filter(Boolean).join('\n');
}
