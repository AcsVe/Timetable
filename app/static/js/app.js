import * as api from './api.js';
import { captureStaticText, lang, setLang, t, onLangChange } from './i18n.js';
import { state, isAdmin } from './store.js';
import { h, jumpTo, toastError } from './ui.js';

const ROUTES = {
  grid: () => import('./views/grid.js'),
  lessons: () => import('./views/lessons.js'),
  validate: () => import('./views/validate.js'),
  reports: () => import('./views/reports.js'),
  timetables: () => import('./views/timetables.js'),
  bells: () => import('./views/bells.js'),
  availability: () => import('./views/availability.js'),
  school: () => import('./views/school.js'),
  import: () => import('./views/import.js'),
  setup: () => import('./views/crud.js'),
};

const view = document.getElementById('view');
let renderToken = 0;

// ---------------------------------------------------------------------------
// Scroll memory + in-page anchors
//  - clicking a link (sidebar or in-page)  → the new page opens at its top (never hidden under the top bar)
//  - browser back/forward, reload, re-render → the page returns to where you were
//  - "#/bells?to=assign" opens a page and jumps to the element with id="assign"
// ---------------------------------------------------------------------------
const SCROLL_KEY = 'scroll-pos';
let positions = {};
try { positions = JSON.parse(sessionStorage.getItem(SCROLL_KEY) || '{}'); } catch (_) { positions = {}; }
let currentPath = null;
let freshNavigation = false;
if ('scrollRestoration' in history) history.scrollRestoration = 'manual';

function parseHash() {
  const raw = location.hash.replace(/^#\/?/, '') || 'grid';
  const [path, query = ''] = raw.split('?');
  return { path, params: new URLSearchParams(query) };
}
function savePosition() {
  if (!currentPath) return;
  positions[currentPath] = window.scrollY;
  try { sessionStorage.setItem(SCROLL_KEY, JSON.stringify(positions)); } catch (_) { /* ignore */ }
}
window.addEventListener('scroll', () => { if (currentPath) positions[currentPath] = window.scrollY; }, { passive: true });
window.addEventListener('beforeunload', savePosition);
document.addEventListener('click', e => {
  const a = e.target.closest('a[href^="#/"]');
  if (a && !e.ctrlKey && !e.metaKey && !e.shiftKey) freshNavigation = true;
});

/** Scroll an element to just below the sticky top bar and flash it. */
export { jumpTo };

async function route() {
  const { path, params } = parseHash();
  const samePage = path === currentPath;
  savePosition();
  const fresh = freshNavigation && !samePage;
  freshNavigation = false;
  const keepY = samePage ? window.scrollY : null;
  currentPath = path;

  const [name, ...rest] = path.split('/');
  document.querySelectorAll('#sidebar a').forEach(a => a.classList.toggle('active', a.dataset.route === path));
  document.getElementById('sidebar').classList.remove('open');
  const loader = ROUTES[name];
  const token = ++renderToken;
  if (!loader) { view.replaceChildren(h('p', {}, t('الصفحة غير موجودة'))); return; }
  if (!samePage) view.replaceChildren(h('p', { class: 'muted' }, t('جارٍ التحميل…')));
  try {
    const mod = await loader();
    const root = h('div');
    await mod.render(root, rest, params);
    if (token !== renderToken) return;
    view.replaceChildren(root);
    // Wait one frame so the new page has its full height before scrolling.
    requestAnimationFrame(() => {
      const target = params.get('to');
      if (target && jumpTo(target, { smooth: false })) return;
      if (keepY !== null) window.scrollTo(0, keepY);
      else if (fresh) window.scrollTo(0, 0);
      else window.scrollTo(0, positions[path] || 0);
    });
  } catch (e) {
    if (token === renderToken) view.replaceChildren(h('p', { class: 'form-error' }, e.message || String(e)));
    console.error(e);
  }
}
export const rerender = route;

export async function loadTimetables() {
  const r = await api.get('/api/timetables');
  const terms = await api.get('/api/terms').then(x => x.items).catch(() => []);
  const termName = Object.fromEntries(terms.map(x => [x.id, x.name_ar]));
  state.timetables = r.items;
  const saved = localStorage.getItem('ttId');
  const pick = state.timetables.find(x => x.id === saved)
    || state.timetables.find(x => x.status === 'published')
    || state.timetables.find(x => x.status === 'draft') || state.timetables[0];
  state.ttId = pick ? pick.id : null;
  const sel = document.getElementById('tt-select');
  const label = { draft: t('مسودة'), published: t('منشور'), archived: t('مؤرشف') };
  sel.replaceChildren(...(state.timetables.length ? state.timetables.map(x =>
    h('option', { value: x.id, selected: x.id === state.ttId },
      `${x.name} — ${termName[x.term_id] || ''} (${label[x.status]})`))
    : [h('option', { value: '' }, t('لا يوجد جدول بعد'))]));
}

function trackTopbarHeight() {
  const bar = document.querySelector('.topbar');
  const set = () => document.documentElement.style.setProperty('--topbar-h', `${bar.offsetHeight}px`);
  set();
  if ('ResizeObserver' in window) new ResizeObserver(set).observe(bar);
  else window.addEventListener('resize', set);
}

async function boot() {
  trackTopbarHeight();
  captureStaticText();
  setLang(lang);
  document.getElementById('lang-toggle').onclick = () => setLang(lang === 'ar' ? 'en' : 'ar');
  document.getElementById('nav-toggle').onclick = () => document.getElementById('sidebar').classList.toggle('open');
  api.onOfflineChange(off => { document.getElementById('offline-banner').hidden = !off; });
  onLangChange(async () => { await loadTimetables().catch(() => {}); route(); });

  try {
    state.me = (await api.get('/auth/me')).user;
  } catch (e) { toastError(e); return; }
  document.getElementById('user-name').textContent = state.me.display_name;
  if (!isAdmin()) document.querySelectorAll('[data-admin]').forEach(a => a.remove());

  try {
    const school = (await api.get('/api/school')).items[0];
    state.school = school || null;
    if (school) {
      document.getElementById('school-name').textContent = lang === 'en' && school.name_en ? school.name_en : school.name_ar;
      if (school.logo_path) { const img = document.getElementById('school-logo'); img.src = school.logo_path; img.hidden = false; }
    }
  } catch (_) { /* optional */ }

  await loadTimetables().catch(toastError);
  document.getElementById('tt-select').onchange = e => {
    state.ttId = e.target.value;
    localStorage.setItem('ttId', state.ttId);
    route();
  };
  window.addEventListener('hashchange', route);
  route();

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(err => console.warn('SW', err));
  }
}

boot();
