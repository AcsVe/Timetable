// Configurable screens (exam timetable, duty roster): renamed field labels, value lists
// (with sub-items such as «الطابق الأول › الممر الشرقي»), and extra fields the school adds —
// optionally shown under a built-in field as its sub-field.
import * as api from '../api.js';
import { lang, t } from '../i18n.js';
import { isAdmin } from '../store.js';
import { h, openForm, toast } from '../ui.js';

export const SEP = ' › ';
const TYPES = [['text', 'نص'], ['number', 'رقم'], ['select', 'قائمة اختيار'], ['teachers', 'معلمون'],
               ['date', 'تاريخ'], ['time', 'وقت'], ['bool', 'نعم / لا'], ['textarea', 'نص طويل']];

export async function loadModule(name) {
  return api.get(`/api/modules/${name}`);
}

export const label = (mod, field) => {
  const l = mod.labels[field];
  return l ? (lang === 'en' && l.en ? l.en : l.ar) : field;
};
export const extraLabel = f => (lang === 'en' && f.label_en ? f.label_en : f.label_ar);
export const title = mod => (lang === 'en' && mod.title.en ? mod.title.en : mod.title.ar);

/** «الطابق الأول › الممر الشرقي» → shown as is; the list editor writes one item per line, a sub-item starting with «-». */
export function listToText(items) {
  const out = [];
  let parent = null;
  for (const it of items) {
    const parts = it.split(SEP);
    if (parts.length > 1 && parts.slice(0, -1).join(SEP) === parent) out.push(`- ${parts.at(-1)}`);
    else if (parts.length > 1) { parent = parts.slice(0, -1).join(SEP); out.push(parent, `- ${parts.at(-1)}`); }
    else { parent = it; out.push(it); }
  }
  // a parent that is only a heading (not an item itself) is written once anyway; harmless
  return out.join('\n');
}
export function textToList(text) {
  const items = [];
  let parent = null;
  for (const raw of String(text || '').split('\n')) {
    const line = raw.trim();
    if (!line) continue;
    if (/^[-–•]/.test(line) && parent) {
      items.push(`${parent}${SEP}${line.replace(/^[-–•]\s*/, '')}`);
    } else {
      parent = line.replace(/\s*[›>]\s*/g, SEP);
      items.push(parent);
    }
  }
  // a heading that has sub-items is kept too, so «الطابق الأول» alone can still be chosen
  return [...new Set(items)];
}

/** Form fields for the extra fields of one level ("session" / "room"), keyed "x:<key>". */
export function extraFields(mod, level, teacherOptions) {
  return mod.extra_fields.filter(f => (f.level || 'session') === level).map(f => ({
    name: `x:${f.key}`, label: f.parent ? `${label(mod, f.parent)} › ${extraLabel(f)}` : extraLabel(f),
    type: f.type === 'teachers' ? 'multi' : f.type === 'select' ? 'list' : f.type,
    options: f.type === 'teachers' ? teacherOptions : f.options, placeholder: f.placeholder || undefined,
    sub: !!f.parent, parent: f.parent, full: f.type === 'textarea',
  }));
}

/** Put each sub-field straight after its parent field. */
export function placeSubFields(fields, extras) {
  const out = [...fields];
  for (const x of extras) {
    let at = x.parent ? out.findIndex(f => f.name === x.parent) : -1;
    if (at < 0) { out.push(x); continue; }
    while (at + 1 < out.length && out[at + 1].sub && out[at + 1].parent === x.parent) at++;
    out.splice(at + 1, 0, x);
  }
  return out;
}

export const extraValues = (mod, level, extra) => Object.fromEntries(
  mod.extra_fields.filter(f => (f.level || 'session') === level).map(f => [`x:${f.key}`, (extra || {})[f.key]]));
export function collectExtra(mod, level, values) {
  const out = {};
  for (const f of mod.extra_fields.filter(x => (x.level || 'session') === level)) {
    const v = values[`x:${f.key}`];
    if (v !== undefined && v !== null && v !== '' && !(Array.isArray(v) && !v.length)) out[f.key] = v;
  }
  return out;
}
export function extraText(f, v, teacherName) {
  if (v === undefined || v === null || v === '') return '';
  if (f.type === 'teachers') return (Array.isArray(v) ? v : [v]).map(teacherName).join('، ');
  if (f.type === 'bool') return v ? '✓' : '';
  return String(v);
}

// ---------------------------------------------------------------------------
// List editor: every item (and sub-item, such as a corridor under its floor) can be added,
// renamed, moved up or down and deleted. A renamed item is renamed in the saved records too.
// ---------------------------------------------------------------------------
/**
 * items: ["الطابق الأول", "الطابق الأول › الممر الشرقي", …]; nested=false for a flat list.
 * Returns { el, value() → items, renames() → {old: new}, count() }.
 */
export function listEditor(items, { nested = true, itemLabel = 'عنصر', subLabel = 'عنصر فرعي', id } = {}) {
  const nodes = [];
  const find = name => nodes.find(n => n.orig === name);
  for (const it of items || []) {
    const parts = String(it).split(SEP);
    if (!nested || parts.length === 1) {
      if (!find(it)) nodes.push({ name: it, orig: it, children: [] });
      continue;
    }
    const head = parts[0];
    const rest = parts.slice(1).join(SEP);
    let p = find(head);
    if (!p) { p = { name: head, orig: head, children: [], headingOnly: true }; nodes.push(p); }
    if (!p.children.some(c => c.orig === rest)) p.children.push({ name: rest, orig: rest });
  }
  const el = h('div', { class: 'tree-edit', id });
  const counter = h('p', { class: 'muted small count' });
  const move = (arr, i, d) => { const j = i + d; if (j < 0 || j >= arr.length) return; [arr[i], arr[j]] = [arr[j], arr[i]]; draw(); };
  let focusNode = null;   // the item just added gets the cursor
  let toFocus = null;
  const addAndFocus = (arr, at, node) => { arr.splice(at, 0, node); focusNode = node; draw(); };
  function row(arr, i, node, sub, parent) {
    const input = h('input', {
      value: node.name, class: sub ? 'tree-sub' : 'tree-main',
      'aria-label': sub ? `${t(subLabel)} — ${parent.name}` : t(itemLabel),
      placeholder: sub ? t(subLabel) : t(itemLabel),
      oninput: e => { node.name = e.target.value; recount(); },
      onkeydown: e => {          // Enter adds the next item instead of submitting the whole dialog
        if (e.key !== 'Enter') return;
        e.preventDefault();
        addAndFocus(arr, i + 1, sub ? { name: '', orig: null } : { name: '', orig: null, children: [] });
      },
    });
    if (focusNode === node) { focusNode = null; toFocus = input; }
    const renamed = node.orig !== null && node.name.trim() && node.name.trim() !== node.orig;
    return h('div', { class: `tree-row${sub ? ' sub' : ''}` },
      sub ? h('span', { class: 'tree-branch', 'aria-hidden': 'true' }, '↳') : null,
      input,
      renamed ? h('span', { class: 'chip warn small', title: `${t('كان')}: ${node.orig}` }, t('مُعدَّل')) : null,
      h('button', { type: 'button', class: 'btn small ghost icon', title: t('نقل لأعلى'), 'aria-label': t('نقل لأعلى'), disabled: i === 0, onclick: () => move(arr, i, -1) }, '↑'),
      h('button', { type: 'button', class: 'btn small ghost icon', title: t('نقل لأسفل'), 'aria-label': t('نقل لأسفل'), disabled: i === arr.length - 1, onclick: () => move(arr, i, 1) }, '↓'),
      !sub && nested ? h('button', { type: 'button', class: 'btn small ghost', onclick: () => {
        addAndFocus(node.children, node.children.length, { name: '', orig: null });
      } }, `+ ${t(subLabel)}`) : null,
      h('button', { type: 'button', class: 'btn small ghost danger-text', 'aria-label': `${t('حذف')} — ${node.name}`, onclick: () => {
        arr.splice(i, 1); draw();
      } }, t('حذف')));
  }
  function recount() {
    const subs = nodes.reduce((a, n) => a + (n.children || []).length, 0);
    counter.textContent = nested
      ? `${t('العناصر الرئيسية')}: ${nodes.length} — ${t('العناصر الفرعية')}: ${subs}`
      : `${t('العدد')}: ${nodes.length}`;
  }
  function draw() {
    el.replaceChildren(counter,
      ...nodes.map((n, i) => h('div', { class: 'tree-node' }, row(nodes, i, n, false),
        ...(n.children || []).map((c, j) => row(n.children, j, c, true, n)))),
      ...(nodes.length ? [] : [h('p', { class: 'muted small' }, t('القائمة فارغة'))]),
      h('button', { type: 'button', class: 'btn small', onclick: () => {
        addAndFocus(nodes, nodes.length, { name: '', orig: null, children: [] });
      } }, `+ ${t(itemLabel)}`));
    recount();
    if (toFocus) { toFocus.focus(); toFocus = null; }   // at once, so the first typed letter is not lost
  }
  draw();
  focusNode = null;
  const clean = s => String(s || '').replace(/\s*[›>]\s*/g, ' ').replace(/\s+/g, ' ').trim();
  return {
    el,
    count: () => nodes.length,
    value() {
      const out = [];
      for (const n of nodes) {
        const name = clean(n.name);
        if (!name) continue;
        out.push(name);
        for (const c of n.children || []) { const cn = clean(c.name); if (cn) out.push(`${name}${SEP}${cn}`); }
      }
      return [...new Set(out)];
    },
    renames() {
      const map = {};
      for (const n of nodes) {
        const name = clean(n.name);
        if (!name) continue;
        if (n.orig !== null && n.orig !== name && !n.headingOnly) map[n.orig] = name;
        for (const c of n.children || []) {
          const cn = clean(c.name);
          if (!cn || c.orig === null || n.orig === null) continue;
          const from = `${n.orig}${SEP}${c.orig}`, to = `${name}${SEP}${cn}`;
          if (from !== to) map[from] = to;
        }
      }
      return map;
    },
  };
}

/** The whole saved configuration of a screen, ready for PUT (labels only where renamed). */
function configValue(mod, over = {}) {
  return {
    title: mod.title,
    labels: Object.fromEntries(Object.keys(mod.labels).filter(k => mod.labels[k].ar !== mod.default_labels[k].ar
      || mod.labels[k].en !== mod.default_labels[k].en).map(k => [k, mod.labels[k]])),
    lists: mod.lists,
    extra_fields: mod.extra_fields,
    ...over,
  };
}

async function saveConfig(mod, value, renames) {
  const r = await api.put(`/api/settings/module:${mod.name}`, { value, renames });
  toast(r.renamed_records ? `${t('تم الحفظ')} — ${t('عُدِّلت السجلات المرتبطة')}: ${r.renamed_records}` : t('تم الحفظ'), 'ok');
  return true;
}

/**
 * The lists of a screen (duty purposes, locations with floors and corridors, time slots…), one
 * editor each. lists: [[key, title, help, {nested, itemLabel, subLabel}]]
 */
export async function editLists(mod, lists, { only } = {}) {
  if (!isAdmin()) return null;
  const chosen = only ? lists.filter(([k]) => k === only) : lists;
  const editors = {};
  const host = h('div', { class: 'lists-editor full' },
    h('p', { class: 'muted small' }, t('أضف أي عنصر أو عنصر فرعي، أو عدّل اسمه، أو رتّبه، أو احذفه، ثم اضغط «حفظ». وتغيير اسم عنصر يغيّره في كل السجلات المحفوظة التي تستخدمه. أما حذف عنصر فلا يحذف السجلات التي تستخدمه.')),
    ...chosen.map(([k, title_, help, opts = {}]) => {
      editors[k] = listEditor(mod.lists[k] || [], { ...opts, id: `list-${k}` });
      return h('section', { class: 'list-block' }, h('h3', {}, t(title_)), help ? h('p', { class: 'muted small' }, t(help)) : null, editors[k].el);
    }));
  return openForm({
    title: `${t('تعديل القوائم')} — ${title(mod)}`, fields: [], extra: host, submitLabel: t('حفظ القوائم'),
    onSubmit: async () => {
      const lists_ = { ...mod.lists };
      const renames = {};
      for (const [k, ed] of Object.entries(editors)) {
        lists_[k] = ed.value();
        const r = ed.renames();
        if (Object.keys(r).length) renames[k] = r;
      }
      return saveConfig(mod, configValue(mod, { lists: lists_ }), renames);
    },
  });
}

// ---------------------------------------------------------------------------
// Editor: screen title, field labels, lists and extra fields — one dialog, saved at once.
// ---------------------------------------------------------------------------
export async function editModule(mod) {
  if (!isAdmin()) return null;
  const rows = mod.extra_fields.map(f => ({ ...f, options: [...(f.options || [])] }));
  const optEditors = new Map();
  const optionEditor = r => {
    if (!optEditors.has(r)) optEditors.set(r, listEditor(r.options || [], { nested: false, itemLabel: 'خيار' }));
    return optEditors.get(r);
  };
  const host = h('div', { class: 'extra-editor full' });
  const fieldOpts = Object.keys(mod.labels).map(k => [k, label(mod, k)]);
  function draw() {
    host.replaceChildren(
      h('h3', {}, t('حقول إضافية')),
      h('p', { class: 'muted small' }, t('أضف أي حقل تحتاج إليه. والحقل الفرعي يظهر تحت الحقل الذي تختاره له، مثل: «الموقع › الطابق».')),
      ...rows.map((r, i) => h('fieldset', { class: 'extra-row' },
        h('legend', {}, `${t('الحقل')} ${i + 1}`),
        h('label', {}, t('الاسم (عربي)'), h('input', { value: r.label_ar || '', required: true, placeholder: t('مثال: رقم الجلوس'),
          'aria-label': t('الاسم (عربي)'), oninput: e => { r.label_ar = e.target.value; } })),
        h('label', {}, t('الاسم (إنجليزي)'), h('input', { value: r.label_en || '', placeholder: 'Seat number',
          'aria-label': t('الاسم (إنجليزي)'), oninput: e => { r.label_en = e.target.value; } })),
        h('label', {}, t('النوع'), h('select', { 'aria-label': t('النوع'), onchange: e => { r.type = e.target.value; draw(); } },
          TYPES.map(([v, l]) => h('option', { value: v, selected: (r.type || 'text') === v }, t(l))))),
        h('label', {}, t('حقل فرعي تحت'), h('select', { 'aria-label': t('حقل فرعي تحت'), onchange: e => { r.parent = e.target.value || null; } },
          h('option', { value: '' }, t('— حقل مستقل —')),
          fieldOpts.map(([v, l]) => h('option', { value: v, selected: r.parent === v }, l)))),
        mod.name === 'exams' ? h('label', {}, t('مستوى الحقل'), h('select', { 'aria-label': t('مستوى الحقل'), onchange: e => { r.level = e.target.value; } },
          h('option', { value: 'session', selected: (r.level || 'session') === 'session' }, t('الامتحان كله')),
          h('option', { value: 'room', selected: r.level === 'room' }, t('كل قاعة على حدة')))) : null,
        h('label', {}, t('نص توضيحي داخل الحقل'), h('input', { value: r.placeholder || '', placeholder: t('مثال: من 1 إلى 30'),
          'aria-label': t('نص توضيحي داخل الحقل'), oninput: e => { r.placeholder = e.target.value; } })),
        r.type === 'select' ? h('div', { class: 'full' }, h('b', {}, t('خيارات القائمة')), optionEditor(r).el) : null,
        h('label', { class: 'inline' }, h('input', { type: 'checkbox', checked: r.show_in_report !== false,
          onchange: e => { r.show_in_report = e.target.checked; } }), t('يظهر في التقرير المطبوع')),
        h('button', { type: 'button', class: 'btn small ghost', onclick: () => { rows.splice(i, 1); draw(); } }, t('حذف الحقل')))),
      h('button', { type: 'button', class: 'btn small ghost', onclick: () => {
        rows.push({ key: `f${Date.now().toString(36).slice(-5)}`, label_ar: '', type: 'text', level: 'session', show_in_report: true });
        draw();
      } }, `+ ${t('حقل إضافي')}`));
  }
  draw();
  const fields = [
    { name: 'title_ar', label: t('اسم الشاشة والتقرير (عربي)'), required: true },
    { name: 'title_en', label: t('اسم الشاشة والتقرير (إنجليزي)') },
    ...Object.keys(mod.labels).map(k => ({ name: `label:${k}`, label: `${t('تسمية الحقل')}: ${mod.default_labels[k].ar}`,
                                           placeholder: mod.default_labels[k].ar })),
  ];
  const values = { title_ar: mod.title.ar, title_en: mod.title.en };
  for (const k of Object.keys(mod.labels)) values[`label:${k}`] = mod.labels[k].ar === mod.default_labels[k].ar ? '' : mod.labels[k].ar;
  return openForm({
    title: `${t('تسميات الحقول والحقول الإضافية')} — ${title(mod)}`, fields, values, extra: host, submitLabel: t('حفظ التخصيص'),
    onSubmit: async v => {
      const renames = {};
      const extra_fields = rows.filter(r => (r.label_ar || '').trim()).map(r => {
        let options = [];
        if (r.type === 'select') {
          const ed = optionEditor(r);
          options = ed.value();
          const rn = ed.renames();
          if (Object.keys(rn).length) renames[`x:${r.key}`] = rn;
        }
        return { key: r.key, label_ar: r.label_ar.trim(), label_en: (r.label_en || '').trim(), type: r.type || 'text',
                 parent: r.parent || null, level: r.level || 'session', placeholder: r.placeholder || '',
                 show_in_report: r.show_in_report !== false, options };
      });
      const value = configValue(mod, {
        title: { ar: v.title_ar || '', en: v.title_en || '' },
        labels: Object.fromEntries(Object.keys(mod.labels).filter(k => v[`label:${k}`]).map(k => [k, { ar: v[`label:${k}`], en: '' }])),
        extra_fields,
      });
      return saveConfig(mod, value, renames);
    },
  });
}
