// Small DOM helpers: element builder, toast, modal forms, confirm.
import { t } from './i18n.js';
import { errorText } from './api.js';

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'style' && typeof v === 'object') {
      for (const [sk, sv] of Object.entries(v)) {
        if (sv === null || sv === undefined) continue;
        if (sk.startsWith('--')) el.style.setProperty(sk, sv); else el.style[sk] = sv;
      }
    }
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else if (v === true) el.setAttribute(k, '');
    else el.setAttribute(k, v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

/** append children, skipping null/false (Element.append would print "null"). */
export function put(el, ...kids) {
  el.append(...kids.flat(Infinity).filter(k => k !== null && k !== undefined && k !== false));
  return el;
}
/** replaceChildren with the same null-skipping rule. */
export function swap(el, ...kids) {
  el.replaceChildren(...kids.flat(Infinity).filter(k => k !== null && k !== undefined && k !== false));
  return el;
}

let toastTimer;
export function toast(msg, kind = '') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = `toast show ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = 'toast'; }, kind === 'err' ? 6000 : 2800);
}
export const toastError = e => toast(errorText(e), 'err');

/**
 * Modal form.
 * fields: [{name, label, type: text|number|bool|select|multi|color|date|time|datetime|password|textarea,
 *           options: [{value,label}], required, full, help, placeholder}]
 * onSubmit(values) may throw ApiError → shown inside the modal, modal stays open.
 */
export function openForm({ title, fields, values = {}, submitLabel, onSubmit, extra }) {
  const dlg = document.getElementById('modal');
  const form = document.getElementById('modal-form');
  form.innerHTML = '';
  const err = h('div', { class: 'form-error', role: 'alert' });
  const inputs = {};
  const grid = h('div', { class: 'form-grid' });
  for (const f of fields) {
    const id = `f-${f.name}`;
    const v = values[f.name];
    let input;
    if (f.type === 'select') {
      input = h('select', { id, name: f.name, 'aria-label': f.label },
        f.required ? null : h('option', { value: '' }, '—'),
        (f.options || []).map(o => h('option', { value: o.value, selected: String(o.value) === String(v ?? '') }, o.label)));
    } else if (f.type === 'multi') {
      input = multiPicker(f, v, id);
    } else if (f.type === 'list') {
      // free text with suggestions from a configured list (e.g. locations «الطابق الأول › الممر الشرقي»)
      const listId = `${id}-list`;
      input = h('span', { class: 'list-input' },
        h('input', { id, name: f.name, type: 'text', value: v ?? '', list: listId, autocomplete: 'off',
                     placeholder: f.placeholder || t('اختر من القائمة أو اكتب قيمة جديدة'), 'aria-label': f.label,
                     required: f.required ? true : null }),
        h('datalist', { id: listId }, (f.options || []).map(o => h('option', { value: typeof o === 'string' ? o : o.value }))));
    } else if (f.type === 'bool') {
      input = h('input', { id, name: f.name, type: 'checkbox', checked: !!v });
    } else if (f.type === 'textarea') {
      input = h('textarea', { id, name: f.name, rows: 3, placeholder: f.placeholder || null, 'aria-label': f.label }, v ?? '');
    } else {
      const type = { number: 'number', color: 'color', date: 'date', time: 'time', datetime: 'datetime-local',
                     password: 'password', email: 'email' }[f.type] || 'text';
      let val = v ?? '';
      if (f.type === 'datetime' && val) val = String(val).slice(0, 16);
      if (f.type === 'time' && val) val = String(val).slice(0, 5);
      if (f.type === 'color' && !val) val = '#dbe7f7';
      input = h('input', { id, name: f.name, type, value: val, placeholder: f.placeholder ?? defaultPlaceholder(f),
                           min: f.min, max: f.max, 'aria-label': f.label, title: f.help || null,
                           required: f.required && f.type !== 'password' ? true : null, autocomplete: 'off' });
    }
    inputs[f.name] = { f, input };
    const wrap = h('div', { class: `field${f.full || f.type === 'multi' || f.type === 'textarea' ? ' full' : ''}${f.sub ? ' sub' : ''}` },
      f.type === 'bool' ? h('label', { class: 'inline', for: id }, input, f.label) : [h('label', { for: id }, f.label), input],
      f.help ? h('div', { class: 'muted', style: { fontSize: '.8rem' } }, f.help) : null);
    grid.append(wrap);
  }
  const submit = h('button', { class: 'btn', type: 'submit', value: 'ok' }, submitLabel || t('حفظ'));
  put(form, h('h2', {}, title), grid, extra || null, err,
    h('div', { class: 'modal-actions' },
      h('button', { class: 'btn ghost', type: 'button', onclick: () => dlg.close() }, t('إلغاء')), submit));

  return new Promise(resolve => {
    form.onsubmit = async ev => {
      ev.preventDefault();
      const out = {};
      for (const [name, { f, input }] of Object.entries(inputs)) {
        if (f.type === 'multi') out[name] = [...input.querySelectorAll('.multi-opts input:checked')].map(i => i.value);
        else if (f.type === 'list') { const x = input.querySelector('input').value.trim(); out[name] = x || null; }
        else if (f.type === 'bool') out[name] = input.checked;
        else if (f.type === 'number') out[name] = input.value === '' ? null : Number(input.value);
        else if (f.type === 'datetime') out[name] = input.value ? new Date(input.value).toISOString() : null;
        else if (f.type === 'password') { if (input.value) out[name] = input.value; }
        else out[name] = input.value === '' ? null : input.value;
      }
      submit.disabled = true;
      err.textContent = '';
      try {
        const r = await onSubmit(out);
        dlg.close();
        resolve(r);
      } catch (e) {
        err.textContent = errorText(e);
      } finally {
        submit.disabled = false;
      }
    };
    dlg.onclose = () => resolve(null);
    dlg.showModal();
  });
}

function defaultPlaceholder(f) {
  if (f.type === 'number') return f.min != null ? String(f.min) : null;
  if (['text', undefined, 'email'].includes(f.type)) return f.type === 'email' ? 'name@school.edu.jo' : null;
  return null;
}

/** Checkbox list; long lists get a live search box and select-all / clear buttons. */
export function multiPicker(f, value, id) {
  const set = new Set((value || []).map(String));
  const opts = f.options || [];
  if (!opts.length) return h('div', { class: 'multi', id, dataset: { multi: f.name } }, h('span', { class: 'muted' }, t('لا توجد عناصر')));
  const list = h('div', { class: 'multi-opts' }, opts.map(o => h('label', { dataset: { text: String(o.label).toLowerCase() } },
    h('input', { type: 'checkbox', value: o.value, checked: set.has(String(o.value)), 'aria-label': o.label }), o.label)));
  const count = h('span', { class: 'muted small count' });
  const recount = () => { count.textContent = `${t('المحدد')}: ${list.querySelectorAll('input:checked').length} ${t('من')} ${opts.length}`; };
  list.addEventListener('change', recount);
  recount();
  const visible = () => [...list.querySelectorAll('label')].filter(l => !l.hidden).map(l => l.querySelector('input'));
  const tools = h('div', { class: 'multi-tools' },
    opts.length > 8 ? h('input', { type: 'search', placeholder: t('ابحث في القائمة…'), 'aria-label': `${t('ابحث')} — ${f.label}`,
                 oninput: e => {
                   const q = e.target.value.trim().toLowerCase();
                   list.querySelectorAll('label').forEach(l => { l.hidden = !!q && !l.dataset.text.includes(q); });
                 } }) : null,
    opts.length > 1 ? h('button', { type: 'button', class: 'btn small ghost', onclick: () => { visible().forEach(i => { i.checked = true; }); recount(); } },
      opts.length > 8 ? t('تحديد الظاهر') : t('تحديد الكل')) : null,
    opts.length > 1 ? h('button', { type: 'button', class: 'btn small ghost', onclick: () => { visible().forEach(i => { i.checked = false; }); recount(); } }, t('إلغاء التحديد')) : null,
    count);
  return h('div', { class: 'multi', id, dataset: { multi: f.name }, role: 'group', 'aria-label': f.label }, tools, list);
}

/** "Label (n)" for any option that stands for several records; «الكل (n)» for the all-option. */
export const withCount = (label, n) => (n === undefined || n === null ? label : `${label} (${n})`);
export const allOption = (n, label) => h('option', { value: '' }, withCount(label || t('الكل'), n));
/** Count records by a key: countBy(items, x => x.section_id) → {id: n}. Keys may be arrays. */
export function countBy(items, key) {
  const out = {};
  for (const x of items) for (const k of [].concat(key(x) ?? [])) if (k != null) out[k] = (out[k] || 0) + 1;
  return out;
}

/** Live search box (filters while typing — also on phones). */
export function searchBox(onInput, placeholder) {
  return h('input', { type: 'search', class: 'search-box', placeholder: placeholder || t('ابحث…'),
                      'aria-label': placeholder || t('ابحث'), autocomplete: 'off', oninput: e => onInput(e.target.value.trim()) });
}

const norm = s => String(s ?? '').toLowerCase().replace(/[\u064B-\u0652]/g, '').replace(/[أإآ]/g, 'ا').replace(/ة/g, 'ه').replace(/ى/g, 'ي');
export const matchesQuery = (text, q) => !q || norm(text).includes(norm(q));

/**
 * List screen table with a checkbox per row, "select all", and a bulk-delete bar.
 * columns: [{label, get(item) → node|text, cls}]; text(item) → searchable text.
 * Returns { el, setQuery(q), setItems(items) }.
 */
export function bulkTable({ items, columns, text, actions, onBulkDelete, emptyText, rowClass, bulkActions = [], deleteLabel }) {
  let all = items, q = '';
  const selectable = !!onBulkDelete || bulkActions.length > 0;
  const selected = new Set();
  const host = h('div');
  const bar = h('div', { class: 'bulk-bar', hidden: true });
  const countLine = h('div', { class: 'count-line muted small', role: 'status' });
  function draw() {
    const shown = all.filter(x => matchesQuery(text ? text(x) : '', q));
    countLine.textContent = [
      q ? `${t('المعروض')}: ${shown.length} ${t('من')} ${all.length}` : `${t('العدد الإجمالي')}: ${all.length}`,
      selected.size ? `${t('المحدد')}: ${selected.size}` : ''].filter(Boolean).join(' — ');
    countLine.hidden = !all.length;
    for (const id of [...selected]) if (!all.some(x => x.id === id)) selected.delete(id);
    const head = h('input', { type: 'checkbox', 'aria-label': t('تحديد الكل'), title: t('تحديد الكل'),
      checked: shown.length > 0 && shown.every(x => selected.has(x.id)),
      onchange: e => { shown.forEach(x => (e.target.checked ? selected.add(x.id) : selected.delete(x.id))); draw(); } });
    const rows = shown.map(x => h('tr', { dataset: { id: x.id }, class: [selected.has(x.id) ? 'selected' : '', rowClass ? rowClass(x) : ''].join(' ').trim() || null },
      selectable ? h('td', { class: 'check' }, h('input', { type: 'checkbox', checked: selected.has(x.id), 'aria-label': t('تحديد'),
        onchange: e => { e.target.checked ? selected.add(x.id) : selected.delete(x.id); draw(); } })) : null,
      columns.map(c => h('td', { class: c.cls || null }, c.get(x))),
      actions ? h('td', { class: 'row-actions' }, actions(x)) : null));
    swap(host, shown.length
      ? h('div', { class: 'grid-scroll' }, h('table', { class: 'data' },
          h('thead', {}, h('tr', {}, selectable ? h('th', { class: 'check' }, head) : null,
            columns.map(c => h('th', {}, c.label)), actions ? h('th') : null)),
          h('tbody', {}, rows)))
      : h('p', { class: 'muted' }, q ? t('لا توجد نتائج مطابقة للبحث') : (emptyText || t('لا توجد سجلات بعد'))));
    bar.hidden = !selected.size;
    swap(bar, h('span', {}, `${t('المحدد')}: ${selected.size}`),
      h('button', { type: 'button', class: 'btn small ghost', onclick: () => { selected.clear(); draw(); } }, t('إلغاء التحديد')),
      bulkActions.map(a => h('button', { type: 'button', class: 'btn small', onclick: async () => {
        const chosen = all.filter(x => selected.has(x.id));
        if (!chosen.length) return;
        try { await a.run(chosen); selected.clear(); draw(); } catch (e) { toastError(e); }
      } }, a.label)),
      onBulkDelete ? h('button', { type: 'button', class: 'btn small danger', onclick: async () => {
        const chosen = all.filter(x => selected.has(x.id));
        if (!chosen.length || !(await confirmBox(`${t('أتريد حذف السجلات المحددة؟')} (${chosen.length})`))) return;
        try { await onBulkDelete(chosen); selected.clear(); } catch (e) { toastError(e); }
      } }, deleteLabel || t('حذف المحدد')) : null);
  }
  draw();
  return {
    el: h('div', {}, bar, countLine, host),
    setQuery(v) { q = v; draw(); },
    setItems(v) { all = v; draw(); },
    selected: () => all.filter(x => selected.has(x.id)),
  };
}

export function confirmBox(message) {
  const dlg = document.getElementById('modal');
  const form = document.getElementById('modal-form');
  form.innerHTML = '';
  form.append(h('p', {}, message), h('div', { class: 'modal-actions' },
    h('button', { class: 'btn ghost', type: 'button', onclick: () => dlg.close('no') }, t('إلغاء')),
    h('button', { class: 'btn danger', type: 'button', onclick: () => dlg.close('yes') }, t('تأكيد'))));
  return new Promise(resolve => {
    dlg.onclose = () => resolve(dlg.returnValue === 'yes');
    dlg.returnValue = '';
    dlg.showModal();
  });
}

export const nameOf = o => (o ? (document.documentElement.lang === 'en' && o.name_en ? o.name_en : (o.name_ar ?? o.name ?? '')) : '');

/**
 * "On this page" bar: buttons that jump to sections of a long page. The URL is updated
 * (#/page?to=id) so reload / sharing the link opens the same spot.
 * links: [{ id, label }]
 */
// Scroll an element to just below everything pinned at the top (topbar + sticky toolbars/page nav),
// so the target never lands hidden behind them.
export function jumpTo(id, { smooth = true } = {}) {
  const el = typeof id === 'string' ? document.getElementById(id) : id;
  if (!el) return false;
  let covered = 0;
  for (const s of document.querySelectorAll('.topbar, .toolbar.sticky, .page-nav')) {
    const cs = getComputedStyle(s);
    if (s.contains(el) || cs.display === 'none' || !['sticky', 'fixed'].includes(cs.position)) continue;
    covered = Math.max(covered, (parseFloat(cs.top) || 0) + s.offsetHeight);
  }
  const y = el.getBoundingClientRect().top + window.scrollY - covered - 10;
  window.scrollTo({ top: Math.max(0, y), behavior: smooth ? 'smooth' : 'auto' });
  el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash');
  return true;
}

export function pageNav(links) {
  const go = id => {
    const base = location.hash.split('?')[0];
    history.replaceState(null, '', `${base}?to=${encodeURIComponent(id)}`);
    jumpTo(id);
  };
  return h('nav', { class: 'page-nav no-print', 'aria-label': t('على هذه الصفحة') },
    h('span', { class: 'muted' }, `${t('انتقل إلى')}:`),
    links.map(l => h('button', { type: 'button', class: 'btn small ghost', onclick: () => go(l.id) }, l.label)));
}
