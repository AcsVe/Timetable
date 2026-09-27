// Local browser storage (IndexedDB).
//  cache  : last successful GET responses — used for read-only viewing when offline (level 1, active).
//  outbox : queued writes for offline editing (level 2) — structure ready, NOT used until
//           the `offline_edit_enabled` setting is switched on and the sync logic is built.
const DB_NAME = 'timetable';
const DB_VERSION = 1;
let dbp = null;

function open() {
  if (dbp) return dbp;
  dbp = new Promise((resolve, reject) => {
    if (!('indexedDB' in self)) return reject(new Error('no indexedDB'));
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains('cache')) db.createObjectStore('cache', { keyPath: 'url' });
      if (!db.objectStoreNames.contains('outbox')) {
        // { idempotency_key, method, url, body, base_version, created_at, status }
        const ob = db.createObjectStore('outbox', { keyPath: 'idempotency_key' });
        ob.createIndex('created_at', 'created_at');
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  return dbp;
}

async function tx(store, mode, fn) {
  const db = await open();
  return new Promise((resolve, reject) => {
    const t = db.transaction(store, mode);
    const s = t.objectStore(store);
    const out = fn(s);
    t.oncomplete = () => resolve(out && 'result' in out ? out.result : undefined);
    t.onerror = () => reject(t.error);
  });
}

export async function cachePut(url, data) {
  try { await tx('cache', 'readwrite', s => s.put({ url, data, at: Date.now() })); } catch (_) { /* best effort */ }
}

export async function cacheGet(url) {
  try {
    const row = await tx('cache', 'readonly', s => s.get(url));
    return row || null;
  } catch (_) { return null; }
}

export async function cacheClear() {
  try { await tx('cache', 'readwrite', s => s.clear()); } catch (_) { /* ignore */ }
}

// Level 2 hook (inactive): kept so enabling offline editing later needs no storage migration.
export async function outboxAdd(entry) {
  return tx('outbox', 'readwrite', s => s.put({ ...entry, created_at: Date.now(), status: 'pending' }));
}
