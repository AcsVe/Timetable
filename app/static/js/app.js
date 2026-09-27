import * as api from './api.js';
import { captureStaticText, lang, setLang, t, onLangChange } from './i18n.js';
import { state, isAdmin } from './store.js';
import { h, toastError } from './ui.js';

const ROUTES = {
  grid: () => import('./views/grid.js'),
  lessons: () => import('./views/lessons.js'),
  validate: () => import('./views/validate.js'),
  timetables: () => import('./views/timetables.js'),
  bells: () => import('./views/bells.js'),
  availability: () => import('./views/availability.js'),
  school: () => import('./views/school.js'),
  setup: () => import('./views/crud.js'),
};

const view = document.getElementById('view');
let renderToken = 0;

async function route() {
  const hash = location.hash.replace(/^#\/?/, '') || 'grid';
  const [name, ...rest] = hash.split('/');
  document.querySelectorAll('#sidebar a').forEach(a => a.classList.toggle('active', a.dataset.route === hash));
  document.getElementById('sidebar').classList.remove('open');
  const loader = ROUTES[name];
  const token = ++renderToken;
  if (!loader) { view.replaceChildren(h('p', {}, t('الصفحة غير موجودة'))); return; }
  view.replaceChildren(h('p', { class: 'muted' }, t('جارٍ التحميل…')));
  try {
    const mod = await loader();
    const root = h('div');
    await mod.render(root, rest);
    if (token === renderToken) view.replaceChildren(root);
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

async function boot() {
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
