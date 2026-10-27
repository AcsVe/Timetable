// Side menu: groups that fold and unfold, a «المفضلة» list at the top (star next to every page), both
// remembered in the user's account (so they follow the user to every device) with a local copy for a fast
// first paint, and the menu's own scroll position kept for the session.
import * as api from './api.js';
import { t } from './i18n.js';
import { h } from './ui.js';

const LOCAL = 'nav:prefs';
let prefs = { favorites: [], collapsed: [] };
let saveTimer = null;
let favHost = null;

// the scrolling menu inside the sidebar (the brand block above it stays put)
const sidebar = () => document.getElementById('side-nav');
const links = () => [...sidebar().querySelectorAll('.nav-item > a[data-route]')];

/** Build the structure once, before the static texts are captured for translation (labels are Arabic here). */
export function buildNav() {
  const sb = sidebar();
  const kids = [...sb.children];
  const top = h('div', { class: 'nav-top' });
  let group = top;
  const groups = [top];
  for (const el of kids) {
    if (el.classList.contains('nav-title')) {
      const id = el.dataset.group;
      const body = h('div', { class: 'nav-body', id: `nav-body-${id}` });
      const btn = h('button', { type: 'button', class: 'nav-title', 'aria-expanded': 'true', 'aria-controls': body.id,
                                dataset: { group: id }, onclick: () => toggle(id) },
        ...el.childNodes, h('span', { class: 'nav-chevron', 'aria-hidden': 'true' }));
      group = h('section', { class: 'nav-group', dataset: { group: id } }, btn, body);
      groups.push(group);
      el.remove();
      continue;
    }
    if (el.tagName === 'A') {
      el.dataset.label = el.textContent.trim();
      const star = h('button', { type: 'button', class: 'nav-star', title: 'إضافة إلى المفضلة', 'aria-label': 'إضافة إلى المفضلة',
                                 'aria-pressed': 'false', dataset: { route: el.dataset.route }, onclick: e => { e.preventDefault(); toggleFav(el.dataset.route); } }, '☆');
      const item = h('div', { class: 'nav-item' }, el, star);
      (group === top ? top : group.querySelector('.nav-body')).append(item);
    }
  }
  favHost = h('section', { class: 'nav-favs', hidden: true }, h('div', { class: 'nav-fav-title' }, h('i', { class: 'fa-solid fa-star', 'aria-hidden': 'true' }), h('span', {}, 'المفضلة')), h('div', { class: 'nav-fav-list' }));
  sb.replaceChildren(favHost, ...groups);
  // remembered locally until the account's copy arrives
  try { apply(JSON.parse(localStorage.getItem(LOCAL) || 'null') || prefs); } catch (_) { apply(prefs); }
  try {
    const y = Number(sessionStorage.getItem('nav:scroll') || 0);
    if (y) requestAnimationFrame(() => { sb.scrollTop = y; });
  } catch (_) { /* ignore */ }
  sb.addEventListener('scroll', () => { try { sessionStorage.setItem('nav:scroll', String(sb.scrollTop)); } catch (_) { /* ignore */ } }, { passive: true });
}

/** The account's saved menu (from /auth/me). */
export function loadNavPrefs(me) {
  const nav = me && me.ui_prefs && me.ui_prefs.nav;
  if (nav) apply(nav);
}

function apply(p) {
  prefs = { favorites: [...(p.favorites || [])], collapsed: [...(p.collapsed || [])] };
  for (const g of sidebar().querySelectorAll('.nav-group')) setCollapsed(g, prefs.collapsed.includes(g.dataset.group));
  drawFavorites();
}

function setCollapsed(g, on) {
  g.classList.toggle('collapsed', on);
  g.querySelector('.nav-title').setAttribute('aria-expanded', on ? 'false' : 'true');
}

function toggle(id) {
  const on = !prefs.collapsed.includes(id);
  prefs.collapsed = on ? [...prefs.collapsed, id] : prefs.collapsed.filter(x => x !== id);
  setCollapsed(sidebar().querySelector(`.nav-group[data-group="${id}"]`), on);
  save();
}

function toggleFav(route) {
  prefs.favorites = prefs.favorites.includes(route) ? prefs.favorites.filter(x => x !== route) : [...prefs.favorites, route];
  drawFavorites();
  save();
}

/** Favourites in the order they were added; pages the user may not open (removed links) are skipped. */
export function drawFavorites() {
  if (!favHost) return;
  const byRoute = Object.fromEntries(links().map(a => [a.dataset.route, a]));
  const favs = prefs.favorites.filter(r => byRoute[r]);
  const list = favHost.querySelector('.nav-fav-list');
  list.replaceChildren(...favs.map(r => h('div', { class: 'nav-item' },
    h('a', { href: byRoute[r].getAttribute('href'), dataset: { route: r, fav: '1' },
             class: byRoute[r].classList.contains('active') ? 'active' : null },
      byRoute[r].querySelector('i') ? byRoute[r].querySelector('i').cloneNode(true) : null, h('span', {}, t(byRoute[r].dataset.label))),
    h('button', { type: 'button', class: 'nav-star on', title: t('إزالة من المفضلة'), 'aria-label': t('إزالة من المفضلة'),
                  'aria-pressed': 'true', onclick: e => { e.preventDefault(); toggleFav(r); } }, '★'))));
  favHost.querySelector('.nav-fav-title span').textContent = `${t('المفضلة')} (${favs.length})`;
  favHost.hidden = !favs.length;
  for (const s of sidebar().querySelectorAll('.nav-star[data-route]')) {
    const on = prefs.favorites.includes(s.dataset.route);
    s.textContent = on ? '★' : '☆';
    s.classList.toggle('on', on);
    s.setAttribute('aria-pressed', on ? 'true' : 'false');
    const label = t(on ? 'إزالة من المفضلة' : 'إضافة إلى المفضلة');
    s.title = label;
    s.setAttribute('aria-label', label);
  }
}

/** The page being opened stays visible: its group unfolds (only on screen, the saved choice is kept). */
export function revealRoute(path) {
  const a = links().find(x => x.dataset.route === path || path.startsWith(`${x.dataset.route}/`));
  const g = a && a.closest('.nav-group.collapsed');
  if (g && !prefs.favorites.includes(a.dataset.route)) setCollapsed(g, false);
}

function save() {
  try { localStorage.setItem(LOCAL, JSON.stringify(prefs)); } catch (_) { /* ignore */ }
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => { api.put('/auth/me/prefs', { nav: prefs }).catch(() => {}); }, 400);
}
