import * as api from './api.js';
import { captureStaticText, lang, setLang, t, onLangChange } from './i18n.js';
import { state, isAdmin } from './store.js';
import { h, jumpTo, openForm, put, swap, toast, toastError } from './ui.js';
import { buildNav, drawFavorites, loadNavPrefs, revealRoute } from './nav.js';

const ROUTES = {
  home: () => import('./views/home.js'),
  grid: () => import('./views/grid.js'),
  lessons: () => import('./views/lessons.js'),
  validate: () => import('./views/validate.js'),
  reports: () => import('./views/reports.js'),
  loads: () => import('./views/loads.js'),
  meetings: () => import('./views/meetings.js'),
  curriculum: () => import('./views/curriculum.js'),
  plans: () => import('./views/plans.js'),
  cover: () => import('./views/cover.js'),
  generate: () => import('./views/generate.js'),
  mail: () => import('./views/mail.js'),
  exams: () => import('./views/exams.js'),
  duties: () => import('./views/duties.js'),
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
  const raw = location.hash.replace(/^#\/?/, '') || 'home';
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
  document.querySelectorAll('#sidebar a[data-route]').forEach(a => a.classList.toggle('active', a.dataset.route === path || path.startsWith(`${a.dataset.route}/`)));
  revealRoute(path);
  closeNav();
  const here = document.querySelector('#side-nav .nav-group a.active, #side-nav .nav-top a.active');
  document.getElementById('page-title').textContent = here ? t(here.dataset.label) : '';
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

// ---------------------------------------------------------------------------
// Shell: off-canvas menu on phones, user menu, school name and logo in the sidebar
// ---------------------------------------------------------------------------
const SYSTEM_ICON = '/static/brand/system.svg';
function closeNav() {
  document.body.classList.remove('nav-open');
  const btn = document.getElementById('nav-toggle');
  if (btn) btn.setAttribute('aria-expanded', 'false');
}
function setupShell() {
  const btn = document.getElementById('nav-toggle');
  btn.onclick = () => {
    const open = document.body.classList.toggle('nav-open');
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
  };
  document.addEventListener('click', e => {
    if (e.target.closest('[data-nav-close]')) closeNav();
    for (const d of document.querySelectorAll('details.user-menu[open]')) if (!d.contains(e.target)) d.removeAttribute('open');
  });
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    closeNav();
    for (const d of document.querySelectorAll('details.user-menu[open]')) d.removeAttribute('open');
  });
  document.getElementById('change-password').onclick = () => {
    document.getElementById('user-menu').removeAttribute('open');
    changePassword();
  };
}

async function changePassword() {
  const done = await openForm({
    title: t('تغيير كلمة المرور'),
    submitLabel: t('حفظ'),
    fields: [
      { name: 'current_password', label: t('كلمة المرور الحالية'), type: 'password', full: true },
      { name: 'new_password', label: t('كلمة المرور الجديدة'), type: 'password', full: true, help: t('ثمانية أحرف على الأقل') },
      { name: 'confirm', label: t('تأكيد كلمة المرور الجديدة'), type: 'password', full: true },
    ],
    onSubmit: async v => {
      if (!v.current_password || !v.new_password) throw new Error(t('أكمل الحقول'));
      if ((v.new_password || '').length < 8) throw new Error(t('ثمانية أحرف على الأقل'));
      if (v.new_password !== v.confirm) throw new Error(t('كلمتا المرور غير متطابقتين'));
      return api.post('/auth/me/password', { current_password: v.current_password, new_password: v.new_password });
    },
  });
  if (done) toast(t('تم تغيير كلمة المرور'), 'ok');
}

/** The school's name and logo in the sidebar (the system icon until a logo is uploaded). */
export function drawBrand() {
  const school = state.school;
  const name = school ? (lang === 'en' && school.name_en ? school.name_en : school.name_ar) : t('جدولة الحصص');
  const el = document.getElementById('school-name');
  el.textContent = name;
  el.title = name;
  const img = document.getElementById('school-logo');
  const logo = school && school.logo_path;
  img.src = logo || SYSTEM_ICON;
  img.classList.toggle('sys-icon', !logo);
  img.alt = logo ? `${t('شعار')} ${name}` : '';
  img.hidden = false;
}

function drawUser() {
  const me = state.me;
  document.getElementById('user-name').textContent = me.display_name;
  document.getElementById('menu-name').textContent = me.display_name;
  document.getElementById('menu-email').textContent = me.email;
  document.getElementById('user-avatar').textContent = (me.display_name || me.email || '?').trim().slice(0, 1);
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
  buildNav();            // before the static texts are captured, so the menu's new labels are translated too
  captureStaticText();
  setLang(lang);
  document.getElementById('lang-toggle').onclick = () => setLang(lang === 'ar' ? 'en' : 'ar');
  setupShell();
  api.onOfflineChange(off => { document.getElementById('offline-banner').hidden = !off; });
  onLangChange(async () => { drawFavorites(); drawBrand(); await loadTimetables().catch(() => {}); route(); });

  try {
    state.me = (await api.get('/auth/me')).user;
  } catch (e) { toastError(e); return; }
  drawUser();
  if (!isAdmin()) document.querySelectorAll('[data-admin]').forEach(a => (a.closest('.nav-item') || a).remove());
  loadNavPrefs(state.me);

  try {
    const school = (await api.get('/api/school')).items[0];
    state.school = school || null;
  } catch (_) { /* optional */ }
  drawBrand();

  await loadTimetables().catch(toastError);
  setupNotifications();
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

// ---------------------------------------------------------------------------
// In-app notifications (e.g. «you have a cover period tomorrow»)
// ---------------------------------------------------------------------------
async function refreshNotifications() {
  try {
    const r = await api.get('/api/notifications/mine');
    const badge = document.getElementById('notif-count');
    badge.textContent = r.unread > 9 ? '9+' : String(r.unread);
    badge.hidden = !r.unread;
    return r;
  } catch (_) { return null; }
}
// Phone / computer alerts (Web Push) for this device.
const b64ToBytes = s => { const b = atob((s + '='.repeat((4 - s.length % 4) % 4)).replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from(b, c => c.charCodeAt(0)); };
async function pushPanel() {
  const box = h('div', { class: 'push-box' });
  if (!('serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window)) {
    return h('p', { class: 'muted small' }, t('هذا المتصفح لا يدعم تنبيهات الجهاز. على iPhone وiPad: أضف النظام إلى الشاشة الرئيسية ثم افتحه من أيقونته.'));
  }
  const reg = await Promise.race([navigator.serviceWorker.ready, new Promise(r => setTimeout(() => r(null), 3000))]);
  if (!reg) return h('p', { class: 'muted small' }, t('تنبيهات الجهاز غير متاحة الآن؛ أعد تحميل الصفحة.'));
  async function draw() {
    const sub = await reg.pushManager.getSubscription();
    const denied = Notification.permission === 'denied';
    swap(box,
      h('span', { class: `chip ${sub ? 'ok' : ''}` }, sub ? t('تنبيهات هذا الجهاز مفعّلة') : t('تنبيهات هذا الجهاز غير مفعّلة')),
      denied ? h('span', { class: 'reasons small' }, t('رُفض الإذن في المتصفح؛ اسمح بالإشعارات لهذا الموقع من إعدادات المتصفح.')) : null,
      !sub && !denied ? h('button', { type: 'button', class: 'btn small', id: 'push-enable', onclick: async () => {
        try {
          if (await Notification.requestPermission() !== 'granted') { draw(); return; }
          const key = await api.get('/api/push/key');
          const s2 = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(key.public_key) });
          await api.post('/api/push/subscribe', s2.toJSON());
          toast(t('فُعِّلت التنبيهات على هذا الجهاز'), 'ok');
        } catch (e) { toastError(e); }
        draw();
      } }, t('تفعيل التنبيهات على هذا الجهاز')) : null,
      sub ? h('button', { type: 'button', class: 'btn small ghost', onclick: async () => {
        try { const r = await api.post('/api/push/test', {}); toast(`${t('أُرسل تنبيه التجربة إلى أجهزتك')}: ${r.sent}`, r.sent ? 'ok' : 'err'); }
        catch (e) { toastError(e); }
      } }, t('تنبيه تجربة')) : null,
      sub ? h('button', { type: 'button', class: 'btn small ghost', onclick: async () => {
        try { await api.post('/api/push/unsubscribe', { endpoint: sub.endpoint }); await sub.unsubscribe(); toast(t('أُوقفت التنبيهات على هذا الجهاز'), 'ok'); }
        catch (e) { toastError(e); }
        draw();
      } }, t('إيقاف التنبيهات على هذا الجهاز')) : null);
  }
  await draw();
  return box;
}

function setupNotifications() {
  const btn = document.getElementById('notif-btn');
  if (!btn) return;
  refreshNotifications();
  setInterval(refreshNotifications, 5 * 60 * 1000);
  btn.onclick = async () => {
    const r = await refreshNotifications();
    const dlg = document.getElementById('modal');
    const form = document.getElementById('modal-form');
    form.innerHTML = '';
    const items = r ? r.items : [];
    put(form, h('h2', {}, t('الإشعارات')), await pushPanel(),
      items.length ? items.map(n => h('div', { class: `msg-card${n.read ? '' : ' unread'}` },
        h('div', { class: 'toolbar' }, h('b', {}, lang === 'en' && n.title_en ? n.title_en : n.title_ar),
          h('span', { class: 'muted small', dir: 'ltr' }, (n.created_at || '').slice(0, 16).replace('T', ' ')),
          n.url ? h('a', { class: 'btn small ghost', href: n.url, onclick: () => dlg.close() }, t('فتح')) : null),
        n.body && n.body.text ? h('pre', { class: 'msg-text', dir: 'auto' }, n.body.text) : null))
        : h('p', { class: 'muted' }, t('لا توجد إشعارات')),
      h('div', { class: 'modal-actions' }, h('button', { class: 'btn', type: 'button', onclick: () => dlg.close() }, t('إغلاق'))));
    dlg.onclose = null;
    dlg.showModal();
    if (r && r.unread) { api.post('/api/notifications/read', {}).then(refreshNotifications).catch(() => {}); }
  };
}

boot();
