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
// Editor: screen title, field labels, lists and extra fields — one dialog, saved at once.
// ---------------------------------------------------------------------------
export async function editModule(mod, { lists }) {
  if (!isAdmin()) return null;
  const rows = mod.extra_fields.map(f => ({ ...f, options: (f.options || []).join('\n') }));
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
        r.type === 'select' ? h('label', { class: 'full' }, t('الخيارات (خيار في كل سطر)'),
          h('textarea', { rows: 3, 'aria-label': t('الخيارات (خيار في كل سطر)'), oninput: e => { r.options = e.target.value; } }, r.options || '')) : null,
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
    ...lists.map(([k, l, help]) => ({ name: `list:${k}`, label: t(l), type: 'textarea', full: true, help: t(help) })),
    ...Object.keys(mod.labels).map(k => ({ name: `label:${k}`, label: `${t('تسمية الحقل')}: ${mod.default_labels[k].ar}`,
                                           placeholder: mod.default_labels[k].ar })),
  ];
  const values = { title_ar: mod.title.ar, title_en: mod.title.en };
  for (const [k] of lists) values[`list:${k}`] = listToText(mod.lists[k] || []);
  for (const k of Object.keys(mod.labels)) values[`label:${k}`] = mod.labels[k].ar === mod.default_labels[k].ar ? '' : mod.labels[k].ar;
  return openForm({
    title: `${t('تخصيص الحقول والقوائم')} — ${title(mod)}`, fields, values, extra: host, submitLabel: t('حفظ التخصيص'),
    onSubmit: async v => {
      const value = {
        title: { ar: v.title_ar || '', en: v.title_en || '' },
        labels: Object.fromEntries(Object.keys(mod.labels).filter(k => v[`label:${k}`]).map(k => [k, { ar: v[`label:${k}`], en: '' }])),
        lists: Object.fromEntries(lists.map(([k]) => [k, textToList(v[`list:${k}`])])),
        extra_fields: rows.filter(r => (r.label_ar || '').trim()).map(r => ({
          key: r.key, label_ar: r.label_ar.trim(), label_en: (r.label_en || '').trim(), type: r.type || 'text',
          parent: r.parent || null, level: r.level || 'session', placeholder: r.placeholder || '',
          show_in_report: r.show_in_report !== false,
          options: r.type === 'select' ? String(r.options || '').split('\n').map(x => x.trim()).filter(Boolean) : [] })),
      };
      await api.put(`/api/settings/module:${mod.name}`, { value });
      toast(t('تم حفظ التخصيص'), 'ok');
      return true;
    },
  });
}
