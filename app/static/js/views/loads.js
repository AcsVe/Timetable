// Conditional weekly-load rules (قواعد النصاب): who a rule covers (stage / subjects / teachers),
// what is expected (exact, range, at least, at most, or each teacher's own target), what is counted,
// and how the result is shown (text, colour or both, with the school's own words and colours).
import * as api from '../api.js';
import { lang, t } from '../i18n.js';
import { byId, canEdit, currentTimetable, list } from '../store.js';
import { bulkTable, confirmBox, h, nameOf, openForm, put, searchBox, swap, toast, toastError } from '../ui.js';
import { noTimetable } from './ctx.js';

const MODES = [['exact', 'عدد محدد من الحصص'], ['range', 'بين حدّين'], ['min', 'لا يقل عن'], ['max', 'لا يزيد على'],
               ['target', 'النصاب المسجّل لكل معلم']];
const DISPLAYS = [['both', 'نص ولون'], ['text', 'نص فقط (مناسب للطباعة بالأبيض والأسود)'], ['color', 'لون فقط']];
const DEFAULT_COLORS = { under: '#c2410c', ok: '#15803d', over: '#b91c1c' };

/** A status badge drawn the way the rule asks: words, a colour, or both. */
export function statusBadge(r) {
  if (!r || r.status === 'none') return h('span', { class: 'muted' }, '—');
  const text = lang === 'en' ? r.label_en : r.label;
  const delta = r.status === 'ok' ? '' : ` (${r.status === 'under' ? '−' : '+'}${r.delta})`;
  const showText = r.display !== 'color';
  const showColor = r.display !== 'text';
  return h('span', { class: `load-badge ${r.status}${showColor ? ' colored' : ''}`, title: lang === 'en' ? r.message_en : r.message,
                     style: showColor && r.color ? { '--c': r.color } : null },
    showText ? `${text}${delta}` : h('span', { class: 'sr-only' }, `${text}${delta}`), showColor && !showText ? delta.trim() || '✓' : null);
}

/** Small notice: "3 teachers under their load, 1 over" with a link to this page (used on other screens). */
export async function loadNotice(tt) {
  try {
    const r = await api.get(`/api/timetables/${tt.id}/load-status`);
    const s = r.summary;
    if (!s.under && !s.over) return s.ok ? h('p', { class: 'notice ok no-print' }, `${t('النصاب مكتمل لجميع المعلمين المشمولين بالقواعد')} (${s.ok})`) : null;
    return h('p', { class: 'notice warn no-print' }, `${t('تنبيه النصاب')}: `,
      s.under ? `${t('نقص')}: ${s.under}` : '', s.under && s.over ? ' — ' : '', s.over ? `${t('زيادة')}: ${s.over}` : '',
      ' · ', h('a', { href: '#/loads' }, t('عرض التفاصيل')));
  } catch (_) { return null; }
}

export async function render(root) {
  const tt = currentTimetable();
  if (!tt) return noTimetable(root);
  const [stages, subjects, teachers] = await Promise.all([list('stages'), list('subjects'), list('teachers')]);
  const stage = byId(stages), subject = byId(subjects), teacher = byId(teachers);
  const readOnly = tt.status === 'archived';
  let rules = [];
  let status = null;
  let rq = '', sq = '', statusFilter = '';
  let rulesTable = null;
  const rulesHost = h('div');
  const statusHost = h('div');
  const groupsHost = h('div');
  const summaryHost = h('div');

  const scopeText = p => [
    p.stage_ids?.length ? `${t('المرحلة')}: ${p.stage_ids.map(x => nameOf(stage[x])).join('، ')}` : '',
    p.subject_ids?.length ? `${t('المبحث')}: ${p.subject_ids.map(x => nameOf(subject[x])).join('، ')}` : '',
    p.teacher_ids?.length ? `${t('المعلمون')}: ${p.teacher_ids.map(x => nameOf(teacher[x])).join('، ')}` : '',
  ].filter(Boolean).join(' · ') || t('جميع المعلمين');
  const expectText = p => ({ exact: `${p.value}${p.tolerance ? ` ± ${p.tolerance}` : ''}`, range: `${p.min}–${p.max}`,
                             min: `${t('لا يقل عن')} ${p.min}`, max: `${t('لا يزيد على')} ${p.max}`,
                             target: `${t('النصاب المسجّل لكل معلم')}${p.tolerance ? ` ± ${p.tolerance}` : ''}` }[p.mode] || '');

  async function load() {
    const [r, st] = await Promise.all([
      api.get(`/api/constraint-rules?timetable_id=${tt.id}&kind=weekly_load`),
      api.get(`/api/timetables/${tt.id}/load-status`)]);
    rules = r.items;
    status = st;
    drawRules(); drawStatus();
  }

  function drawRules() {
    rulesTable = bulkTable({
      items: rules, text: r => [r.params.name, scopeText(r.params), expectText(r.params)].join(' '),
      columns: [
        { label: t('القاعدة'), get: r => h('b', {}, r.params.name || '—') },
        { label: t('تنطبق على'), get: r => scopeText(r.params) },
        { label: t('النصاب المطلوب'), get: r => expectText(r.params) },
        { label: t('ما يُحتسب'), get: r => [r.params.count === 'scope' ? t('حصص النطاق فقط') : t('جميع حصص المعلم'), ' · ',
                                                r.params.basis === 'placed' ? t('المُدرَج في الجدول') : t('المُسنَد في الدروس')] },
        { label: t('طريقة الإظهار'), get: r => h('span', {}, t(DISPLAYS.find(d => d[0] === r.params.display)?.[1] || ''), ' ',
          ['under', 'ok', 'over'].map(k => h('span', { class: 'swatch', title: r.params.texts[k], style: { background: r.params.colors[k] } }))) },
        { label: t('مفعّلة'), get: r => (r.is_active ? '✓' : '—') },
      ],
      actions: r => (canEdit() && !readOnly ? [h('button', { class: 'btn small ghost', onclick: () => edit(r) }, t('تعديل')), ' ',
                                              h('button', { class: 'btn small ghost', onclick: () => remove(r) }, t('حذف'))] : null),
      onBulkDelete: canEdit() && !readOnly ? async items => {
        const res = await api.post('/api/constraint-rules/bulk-delete', { items: items.map(x => ({ id: x.id, version: x.version })) });
        toast(`${t('تم الحذف')}: ${res.count}`, 'ok'); await load();
      } : null,
      emptyText: t('لا توجد قواعد بعد. وما لم تُضَف قاعدة يُقارَن كل معلم بنصابه المسجّل في بياناته.'),
    });
    rulesTable.setQuery(rq);
    swap(rulesHost, rulesTable.el);
  }

  function drawStatus() {
    const s = status.summary;
    swap(summaryHost, h('div', { class: 'stats' },
      [['ok', t('مكتمل')], ['under', t('نقص')], ['over', t('زيادة')], ['none', t('بلا نصاب محدد')]].map(([k, l]) =>
        h('button', { type: 'button', class: `stat stat-btn${statusFilter === k ? ' active' : ''}`, 'aria-pressed': statusFilter === k ? 'true' : 'false',
                      onclick: () => { statusFilter = statusFilter === k ? '' : k; drawStatus(); } }, h('b', {}, s[k]), l))));
    const rows = status.teachers.filter(r => (!statusFilter || r.status === statusFilter));
    const tb = bulkTable({
      items: rows.map(r => ({ ...r, id: r.teacher_id })),
      text: r => [r.name, r.name_en, r.subjects.join(' '), r.label, r.rule_name].join(' '),
      columns: [
        { label: t('المعلم'), get: r => (lang === 'en' && r.name_en ? r.name_en : r.name) },
        { label: t('المباحث'), get: r => r.subjects.join('، ') },
        { label: t('المُسنَد'), cls: 'num', get: r => r.assigned },
        { label: t('المُدرَج في الجدول'), cls: 'num', get: r => r.placed },
        { label: t('النصاب المطلوب'), cls: 'num', get: r => (lang === 'en' ? r.expected_en : r.expected) },
        { label: t('الحالة'), get: r => statusBadge(r) },
        { label: t('القاعدة'), get: r => r.rule_name || (r.default_rule ? t('النصاب المسجّل للمعلم') : '') },
      ],
      emptyText: t('لا يوجد معلمون في هذه الحالة'),
    });
    tb.setQuery(sq);
    swap(statusHost, tb.el);
    swap(groupsHost, status.groups.length ? h('div', { class: 'group-cards' }, status.groups.map(g =>
      h('div', { class: 'stat group-card' }, h('div', { class: 'toolbar' }, h('b', {}, g.name || g.scope), statusBadge({ ...g, delta: 0, label_en: g.label })),
        h('div', { class: 'muted small' }, g.scope),
        h('div', {}, `${t('عدد المعلمين')}: ${g.teachers} — ${t('مجموع الحصص')}: ${g.actual} ${t('من')} ${g.expected}`),
        h('div', { class: 'small' }, `${t('مكتمل')}: ${g.counts.ok} · ${t('نقص')}: ${g.counts.under} · ${t('زيادة')}: ${g.counts.over}`)))) : null);
  }

  // ------------------------------------------------------------------ form
  const fields = () => [
    { name: 'name', label: t('اسم القاعدة'), placeholder: t('مثال: نصاب معلمي المرحلة الثانوية'), full: true },
    { name: 'stage_ids', label: t('المراحل (اتركها فارغة لجميع المراحل)'), type: 'multi', options: stages.map(s => ({ value: s.id, label: nameOf(s) })) },
    { name: 'subject_ids', label: t('المباحث (اتركها فارغة لجميع المباحث)'), type: 'multi', options: subjects.map(s => ({ value: s.id, label: nameOf(s) })) },
    { name: 'teacher_ids', label: t('معلمون محددون (اتركها فارغة لجميع المعلمين)'), type: 'multi',
      options: [...teachers].sort((a, b) => nameOf(a).localeCompare(nameOf(b), 'ar')).map(x => ({ value: x.id, label: nameOf(x) })) },
    { name: 'mode', label: t('النصاب المطلوب'), type: 'select', required: true, options: MODES.map(([v, l]) => ({ value: v, label: t(l) })) },
    { name: 'value', label: t('عدد الحصص (للعدد المحدد)'), type: 'number', min: 0, placeholder: '20' },
    { name: 'min', label: t('الحد الأدنى'), type: 'number', min: 0, placeholder: '18' },
    { name: 'max', label: t('الحد الأعلى'), type: 'number', min: 0, placeholder: '24' },
    { name: 'tolerance', label: t('السماح (± حصة)'), type: 'number', min: 0, placeholder: '0',
      help: t('يُعَدّ النصاب مكتملاً إذا كان الفرق ضمن هذا العدد') },
    { name: 'count', label: t('الحصص المحتسبة'), type: 'select', required: true, options: [
      { value: 'all', label: t('جميع حصص المعلم') }, { value: 'scope', label: t('حصص المراحل والمباحث المختارة فقط') }] },
    { name: 'basis', label: t('أساس الحساب'), type: 'select', required: true, options: [
      { value: 'assigned', label: t('المُسنَد في الدروس') }, { value: 'placed', label: t('المُدرَج في الجدول') }] },
    { name: 'display', label: t('طريقة الإظهار'), type: 'select', required: true, options: DISPLAYS.map(([v, l]) => ({ value: v, label: t(l) })) },
    { name: 'text_under', label: t('نص النقص'), placeholder: t('نقص') },
    { name: 'color_under', label: t('لون النقص'), type: 'color' },
    { name: 'text_ok', label: t('نص الاكتمال'), placeholder: t('مكتمل') },
    { name: 'color_ok', label: t('لون الاكتمال'), type: 'color' },
    { name: 'text_over', label: t('نص الزيادة'), placeholder: t('زيادة') },
    { name: 'color_over', label: t('لون الزيادة'), type: 'color' },
    { name: 'is_active', label: t('القاعدة مفعّلة'), type: 'bool' },
  ];
  const toValues = r => {
    const p = r ? r.params : {};
    return { name: p.name, stage_ids: p.stage_ids || [], subject_ids: p.subject_ids || [], teacher_ids: p.teacher_ids || [],
             mode: p.mode || 'exact', value: p.value, min: p.min, max: p.max, tolerance: p.tolerance || null,
             count: p.count || 'all', basis: p.basis || 'assigned', display: p.display || 'both',
             text_under: p.texts?.under, text_ok: p.texts?.ok, text_over: p.texts?.over,
             color_under: p.colors?.under || DEFAULT_COLORS.under, color_ok: p.colors?.ok || DEFAULT_COLORS.ok,
             color_over: p.colors?.over || DEFAULT_COLORS.over, is_active: r ? r.is_active : true };
  };
  const toParams = v => ({ name: v.name || '', stage_ids: v.stage_ids, subject_ids: v.subject_ids, teacher_ids: v.teacher_ids,
    mode: v.mode, value: v.value, min: v.min, max: v.max, tolerance: v.tolerance || 0, count: v.count, basis: v.basis,
    display: v.display, colors: { under: v.color_under, ok: v.color_ok, over: v.color_over },
    texts: { under: v.text_under || t('نقص'), ok: v.text_ok || t('مكتمل'), over: v.text_over || t('زيادة') } });
  const save = async (v, r) => {
    if (r) await api.patch(`/api/constraint-rules/${r.id}`, { version: r.version, params: toParams(v), is_active: v.is_active });
    else await api.post('/api/constraint-rules', { timetable_id: tt.id, kind: 'weekly_load', scope_type: 'global',
                                                   params: toParams(v), is_active: v.is_active, strength: 'soft' });
    toast(t('تم الحفظ'), 'ok'); await load();
  };
  const add = () => openForm({ title: t('قاعدة نصاب جديدة'), fields: fields(), values: toValues(null), onSubmit: v => save(v, null) });
  const edit = r => openForm({ title: t('تعديل قاعدة النصاب'), fields: fields(), values: toValues(r), onSubmit: v => save(v, r) });
  async function remove(r) {
    if (!(await confirmBox(t('أتريد حذف هذا السجل؟')))) return;
    try { await api.del(`/api/constraint-rules/${r.id}`, r.version); toast(t('تم الحذف'), 'ok'); await load(); } catch (e) { toastError(e); }
  }

  put(root, h('h1', { class: 'title' }, `${t('قواعد النصاب الأسبوعي')} — ${tt.name}`),
    h('p', { class: 'muted' }, t('حدِّد النصاب المطلوب لمرحلة أو لمبحث أو لمعلم أو لعدة معلمين. وتُطبَّق على كل معلم القاعدةُ الأخص به: قاعدة المعلم، ثم المبحث، ثم المرحلة، ثم جميع المعلمين. ويظهر اكتمال النصاب أو نقصه أو زيادته بالنص أو باللون أو بهما معاً كما تختار.')),
    readOnly ? h('p', { class: 'reasons' }, t('هذا الجدول مؤرشف وللقراءة فقط')) : null,
    h('div', { class: 'toolbar sticky' },
      canEdit() && !readOnly ? h('button', { class: 'btn', onclick: add }, `+ ${t('قاعدة نصاب جديدة')}`) : null,
      searchBox(v => { rq = v; rulesTable && rulesTable.setQuery(v); }, t('ابحث في القواعد…')),
      h('a', { class: 'btn ghost', href: '#/reports', onclick: () => sessionStorage.setItem('reports', JSON.stringify({ kind: 'load-status' })) }, t('طباعة تقرير النصاب'))),
    rulesHost,
    h('h2', { class: 'section-title' }, t('حالة النصاب')),
    summaryHost, groupsHost,
    h('div', { class: 'toolbar' }, searchBox(v => { sq = v; drawStatus(); }, t('ابحث عن معلم أو مبحث…'))),
    statusHost);
  await load();
}
