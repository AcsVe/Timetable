/* Service worker — served from /sw.js so its scope is the whole site.
 *
 * Level 1 offline support (read-only):
 *  - app shell (page + static files) is cached so the app opens without a connection;
 *  - API data is cached separately by the page in IndexedDB (see static/js/api.js);
 *  - writes are never queued here: offline saves are refused with a clear message.
 * Bump VERSION when static files change.
 */
const VERSION = '2026.09.28-1';
const SHELL = `shell-${VERSION}`;
const FONTS = 'fonts-v1';
const PRECACHE = [
  '/offline',
  '/manifest.webmanifest',
  '/static/css/app.css',
  '/static/js/main.js',
  '/static/js/app.js',
  '/static/js/api.js',
  '/static/js/idb.js',
  '/static/js/i18n.js',
  '/static/js/store.js',
  '/static/js/ui.js',
  '/static/js/views/ctx.js',
  '/static/js/views/grid.js',
  '/static/js/views/lessons.js',
  '/static/js/views/validate.js',
  '/static/js/views/reports.js',
  '/static/js/views/timetables.js',
  '/static/js/views/bells.js',
  '/static/js/views/availability.js',
  '/static/js/views/school.js',
  '/static/js/views/import.js',
  '/static/js/views/crud.js',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(SHELL).then(c => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(k => k !== SHELL && k !== FONTS).map(k => caches.delete(k))))
      .then(() => self.clients.claim()));
});

self.addEventListener('fetch', event => {
  const req = event.request;
  if (req.method !== 'GET') return;                       // writes always go to the network
  const url = new URL(req.url);

  if (url.origin === self.location.origin) {
    if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/auth/')) return;  // handled by the page
    if (req.mode === 'navigate') { event.respondWith(navigate(req)); return; }
    if (url.pathname.startsWith('/static/')) { event.respondWith(staleWhileRevalidate(req)); return; }
    return;
  }
  if (url.hostname.endsWith('fonts.googleapis.com') || url.hostname.endsWith('fonts.gstatic.com')) {
    event.respondWith(cacheFirst(req, FONTS));
  }
});

async function navigate(req) {
  const cache = await caches.open(SHELL);
  try {
    const res = await fetch(req);
    // Only cache the real app page, never the login redirect.
    if (res.ok && !res.redirected && new URL(req.url).pathname === '/') cache.put('/', res.clone());
    return res;
  } catch (e) {
    return (await cache.match('/')) || (await cache.match('/offline')) || Response.error();
  }
}

async function staleWhileRevalidate(req) {
  const cache = await caches.open(SHELL);
  const cached = await cache.match(req, { ignoreSearch: true });
  const network = fetch(req).then(res => { if (res.ok) cache.put(req, res.clone()); return res; }).catch(() => null);
  return cached || (await network) || Response.error();
}

async function cacheFirst(req, name) {
  const cache = await caches.open(name);
  const hit = await cache.match(req);
  if (hit) return hit;
  try {
    const res = await fetch(req);
    if (res.ok || res.type === 'opaque') cache.put(req, res.clone());
    return res;
  } catch (e) { return Response.error(); }
}
