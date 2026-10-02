// Duty roster (per term): who supervises what (purpose), where (location, floor, corridor), when (time slot,
// from–to) and on which day. A grid by day like the printed roster, plus a list with bulk actions.
import * as api from '../api.js';
import { lang, t } from '../i18n.js';
import { byId, canEdit, currentTimetable, isAdmin, list } from '../store.js';
import { bulkTable, confirmBox, h, nameOf, openForm, put, searchBox, swap, toast, toastError, matchesQuery, countBy, withCount } from '../ui.js';
import { notifyDialog } from './notify.js';
import { collectExtra, editLists, editModule, extraFields, extraLabel, extraText, extraValues, label, loadModule, placeSubFields, title } from './modconf.js';

const DUTY_LISTS = [
  ['duty_types', 'الغايات', 'مثل: الطابور الصباحي، الاستراحات، مغادرة الطلبة', { nested: false, itemLabel: 'غاية' }],
  ['locations', 'المواقع: الطوابق والممرات', 'أضف الطابق أو المبنى عنصراً رئيسياً، ثم أضف تحته ممراته أو أجزاءه عناصرَ فرعية.', { itemLabel: 'موقع أو طابق', subLabel: 'ممر أو جزء' }],
  ['time_labels', 'الفترات', 'مثل: قبل بدء الدوام، الاستراحة الأولى، نهاية الدوام', { nested: false, itemLabel: 'فترة' }],
];

const hm = x => (x ? String(x).slice(0, 5) : '');

export async function render(root) {
  const [terms, stages, teachers, weekdays] = await Promise.all([list('terms'), list('stages'), list('teachers'), list('weekdays')]);
  let mod = await loadModule('duties');
  const tt = currentTimetable();
  const days = weekdays.filter(d => d.is_school_day).sort((a, b) => a.sort_order - b.sort_order);
  const day = byId(days), stage = byId(stages), teacher = byId(teachers);
  let termId = sessionStorage.getItem('duties:term') || tt?.term_id || terms[0]?.id || '';
  let view = sessionStorage.getItem('duties:view') || 'grid';
  let duties = [];
  let query = '';
  let table = null;
  const host = h('div');
  const issuesHost = h('div');
  const teacherName = id => nameOf(teacher[id]) || '?';
  const teacherOpts = () => [...teachers].sort((a, b) => nameOf(a).localeCompare(nameOf(b), 'ar')).map(x => ({ value: x.id, label: nameOf(x) }));
  const when = d => [d.time_label, d.starts_at ? `${hm(d.starts_at)}\u200e–\u200e${hm(d.ends_at)}` : ''].filter(Boolean).join(' ');
  const textOf = d => [nameOf(day[d.weekday_id]) || t('كل الأيام'), when(d), d.duty_type, d.location, nameOf(stage[d.stage_id]),
                       ...(d.teacher_ids || []).map(teacherName), d.notes].join(' ');

  async function load() {
    duties = termId ? (await api.get(`/api/duty-assignments?term_id=${termId}`)).items : [];
    api.get('/api/duty-assignments').then(r => {   // how many records each term holds
      const n = countBy(r.items, x => x.term_id);
      for (const o of termSel.options) o.textContent = withCount(o.dataset.label, n[o.value] || 0);
    }).catch(() => {});
    draw();
    checkIssues();
  }
  async function checkIssues() {
    if (!termId) { swap(issuesHost); return; }
    try {
      const q = new URLSearchParams({ term_id: termId, what: 'duties' });
      if (tt && tt.term_id === termId) q.set('timetable_id', tt.id);
      const r = await api.get(`/api/school-ops/check?${q}`);
      swap(issuesHost, r.duties.length ? h('details', { class: 'issues notice warn', open: r.duties.length <= 5 },
        h('summary', {}, `${t('تنبيهات جدول المناوبة')}: ${r.duties.length}`),
        h('ul', {}, r.duties.map(i => h('li', { class: i.code === 'duty_no_teacher' ? 'warn' : 'err' }, lang === 'en' ? i.message_en : i.message))))
        : h('p', { class: 'notice ok' }, t('لا توجد تعارضات في المناوبة')));
    } catch (e) { swap(issuesHost); }
  }

  // ------------------------------------------------------------------ grid by day
  function gridView() {
    const shown = duties.filter(d => matchesQuery(textOf(d), query));
    const keyOf = d => JSON.stringify([d.time_label || '', hm(d.starts_at), hm(d.ends_at), d.duty_type, d.location || '', d.stage_id || '']);
    const groups = new Map();
    for (const d of [...shown].sort((a, b) => (a.sort_order - b.sort_order) || hm(a.starts_at).localeCompare(hm(b.starts_at)))) {
      if (!groups.has(keyOf(d))) groups.set(keyOf(d), { sample: d, items: [] });
      groups.get(keyOf(d)).items.push(d);
    }
    if (!groups.size) return h('p', { class: 'muted' }, query ? t('لا توجد نتائج مطابقة للبحث') : t('لا توجد مناوبات لهذا الفصل بعد'));
    const cell = (g, dayId) => {
      const items = g.items.filter(d => !d.weekday_id || d.weekday_id === dayId);
      return h('td', { class: 'duty-cell' },
        items.map(d => h('div', { class: `duty-entry${d.weekday_id ? '' : ' every-day'}`, title: d.weekday_id ? '' : t('مناوبة في كل الأيام') },
          (d.teacher_ids || []).length ? d.teacher_ids.map(x => h('span', { class: 'chip' }, teacherName(x))) : h('span', { class: 'reasons' }, t('بلا معلم')),
          canEdit() ? h('button', { class: 'btn small ghost', 'aria-label': t('تعديل'), title: t('تعديل'), onclick: () => edit(d) }, '✎') : null)),
        canEdit() ? h('button', { class: 'btn small ghost add-here', title: t('إضافة مناوبة في هذه الخانة'),
          'aria-label': t('إضافة مناوبة في هذه الخانة'),
          onclick: () => add({ ...g.sample, id: undefined, version: undefined, teacher_ids: [], weekday_ids: [dayId], notes: null }) }, '+') : null);
    };
    const total = shown.reduce((a, d) => a + (d.weekday_id ? 1 : days.length) * Math.max(1, (d.teacher_ids || []).length), 0);
    return h('div', {}, h('div', { class: 'count-line muted small' },
      `${t('العدد الإجمالي')}: ${shown.length}${query ? ` ${t('من')} ${duties.length}` : ''} — ${t('مناوبات المعلمين في الأسبوع')}: ${total}`),
      h('div', { class: 'grid-scroll' }, h('table', { class: 'data duty-grid' },
      h('thead', {}, h('tr', {}, h('th', {}, `${label(mod, 'time_label')} / ${label(mod, 'duty_type')} / ${label(mod, 'location')}`),
        days.map(d => h('th', {}, nameOf(d))))),
      h('tbody', {}, [...groups.values()].map(g => h('tr', {},
        h('th', { class: 'duty-head' }, h('b', {}, g.sample.duty_type), when(g.sample) ? h('div', { dir: 'auto' }, when(g.sample)) : null,
          g.sample.location ? h('div', { class: 'muted' }, g.sample.location) : null,
          g.sample.stage_id ? h('div', { class: 'muted' }, nameOf(stage[g.sample.stage_id])) : null),
        days.map(d => cell(g, d.id))))))));
  }

  function draw() {
    const xs = mod.extra_fields;
    if (view === 'grid') { table = null; swap(host, gridView()); return; }
    table = bulkTable({
      items: duties, text: textOf,
      columns: [
        { label: label(mod, 'weekday_id'), get: d => nameOf(day[d.weekday_id]) || t('كل الأيام') },
        { label: label(mod, 'time_label'), get: d => h('span', { dir: 'auto' }, when(d)) },
        { label: label(mod, 'duty_type'), get: d => h('b', {}, d.duty_type) },
        { label: label(mod, 'location'), get: d => d.location || '' },
        { label: label(mod, 'stage_id'), get: d => nameOf(stage[d.stage_id]) },
        { label: label(mod, 'teacher_ids'), get: d => (d.teacher_ids || []).map(x => h('span', { class: 'chip' }, teacherName(x))) },
        ...xs.map(f => ({ label: extraLabel(f), get: d => extraText(f, (d.extra || {})[f.key], teacherName) })),
      ],
      actions: d => (canEdit() ? [h('button', { class: 'btn small ghost', onclick: () => edit(d) }, t('تعديل')), ' ',
                                  h('button', { class: 'btn small ghost', onclick: () => remove(d) }, t('حذف'))] : null),
      onBulkDelete: canEdit() ? async items => {
        const r = await api.post('/api/duty-assignments/bulk-delete', { items: items.map(x => ({ id: x.id, version: x.version })) });
        toast(`${t('تم الحذف')}: ${r.count}`, 'ok'); await load();
      } : null,
      emptyText: t('لا توجد مناوبات لهذا الفصل بعد'),
    });
    table.setQuery(query);
    swap(host, table.el);
  }

  // ------------------------------------------------------------------ form
  function formFields(creating) {
    const dayField = creating
      ? { name: 'weekday_ids', label: `${label(mod, 'weekday_id')} (${t('اختر يوماً أو أكثر، أو اتركها كلها فارغة لكل الأيام')})`, type: 'multi',
          options: days.map(d => ({ value: d.id, label: nameOf(d) })) }
      : { name: 'weekday_id', label: label(mod, 'weekday_id'), type: 'select', options: days.map(d => ({ value: d.id, label: nameOf(d) })),
          help: t('اتركه فارغاً لتكون المناوبة في كل الأيام') };
    const base = [
      dayField,
      { name: 'duty_type', label: label(mod, 'duty_type'), type: 'list', required: true, options: mod.lists.duty_types },
      { name: 'location', label: label(mod, 'location'), type: 'list', options: mod.lists.locations },
      { name: 'time_label', label: label(mod, 'time_label'), type: 'list', options: mod.lists.time_labels },
      { name: 'starts_at', label: label(mod, 'starts_at'), type: 'time' },
      { name: 'ends_at', label: label(mod, 'ends_at'), type: 'time' },
      { name: 'stage_id', label: label(mod, 'stage_id'), type: 'select', options: stages.map(s => ({ value: s.id, label: nameOf(s) })) },
      { name: 'sort_order', label: t('الترتيب في الجدول'), type: 'number', min: 0, placeholder: '0' },
      { name: 'teacher_ids', label: label(mod, 'teacher_ids'), type: 'multi', options: teacherOpts() },
      { name: 'notes', label: label(mod, 'notes'), type: 'textarea', placeholder: t('ملاحظات تظهر في التقرير') },
    ];
    return placeSubFields(base, extraFields(mod, 'session', teacherOpts()));
  }
  const bodyOf = v => ({ term_id: termId, duty_type: v.duty_type, location: v.location, time_label: v.time_label,
                         starts_at: v.starts_at, ends_at: v.ends_at, stage_id: v.stage_id, sort_order: v.sort_order ?? 0,
                         teacher_ids: v.teacher_ids, notes: v.notes, extra: collectExtra(mod, 'session', v) });
  const add = (values = {}) => openForm({ title: t('مناوبة جديدة'), fields: formFields(true),
    values: { ...values, ...extraValues(mod, 'session', values.extra) },
    onSubmit: async v => {
      const ids = v.weekday_ids && v.weekday_ids.length ? v.weekday_ids : [null];
      for (const wd of ids) await api.post('/api/duty-assignments', { ...bodyOf(v), weekday_id: wd });
      toast(ids.length > 1 ? `${t('تم الحفظ')}: ${ids.length}` : t('تم الحفظ'), 'ok');
      await load();
    } });
  const edit = d => openForm({ title: t('تعديل المناوبة'), fields: formFields(false),
    values: { ...d, ...extraValues(mod, 'session', d.extra) },
    onSubmit: async v => {
      await api.patch(`/api/duty-assignments/${d.id}`, { ...bodyOf(v), weekday_id: v.weekday_id, version: d.version });
      toast(t('تم الحفظ'), 'ok'); await load();
    },
    extra: canEdit() ? h('div', { class: 'toolbar' }, h('button', { type: 'button', class: 'btn small danger',
      onclick: async () => { document.getElementById('modal').close(); await remove(d); } }, t('حذف المناوبة'))) : null });
  async function remove(d) {
    if (!(await confirmBox(t('أتريد حذف هذا السجل؟')))) return;
    try { await api.del(`/api/duty-assignments/${d.id}`, d.version); toast(t('تم الحذف'), 'ok'); await load(); } catch (e) { toastError(e); }
  }
  const copyFrom = () => openForm({ title: t('نسخ مناوبات فصل آخر إلى هذا الفصل'), fields: [
      { name: 'from', label: t('انسخ من الفصل الدراسي'), type: 'select', required: true,
        options: terms.filter(x => x.id !== termId).map(x => ({ value: x.id, label: nameOf(x) })) },
      { name: 'replace', label: t('احذف مناوبات هذا الفصل الحالية أولاً'), type: 'bool' }],
    onSubmit: async v => {
      const r = await api.post('/api/duty-assignments/copy', { from_term_id: v.from, to_term_id: termId, replace: v.replace });
      toast(`${t('تم النسخ')}: ${r.copied}`, 'ok'); await load();
    } });

  const report = (kind, fmt) => {
    if (!tt) { toastError(new api.ApiError(0, { message: t('اختر جدولاً من أعلى الصفحة أولاً') })); return; }
    const style = localStorage.getItem('report:style') || 'plain';
    window.open(`/api/timetables/${tt.id}/reports/${kind}?format=${fmt}&lang=${lang}&style=${style}`, '_blank');
  };
  const termSel = h('select', { id: 'duty-term', 'aria-label': t('الفصل الدراسي'), onchange: e => { termId = e.target.value; sessionStorage.setItem('duties:term', termId); load(); } },
    terms.map(x => h('option', { value: x.id, selected: x.id === termId, dataset: { label: nameOf(x) } }, nameOf(x))));
  const viewSel = h('select', { id: 'duty-view', 'aria-label': t('طريقة العرض'), onchange: e => { view = e.target.value; sessionStorage.setItem('duties:view', view); draw(); } },
    [['grid', t('حسب الأيام')], ['list', t('قائمة مع تحديد متعدد')]].map(([v, l]) => h('option', { value: v, selected: v === view }, l)));

  put(root, h('h1', { class: 'title' }, title(mod)),
    h('p', { class: 'muted' }, t('يُبنى جدول المناوبة لكل فصل دراسي: الغاية من المناوبة، وموقعها (الطابق والممر)، وفترتها ووقتها، والمعلمون المناوبون. ويُنبَّه إلى المعلم المناوب في مكانين في الوقت نفسه، أو في أثناء حصة له في الجدول.')),
    h('div', { class: 'toolbar sticky' },
      h('label', { class: 'inline' }, `${t('الفصل الدراسي')}:`, termSel),
      canEdit() && termId ? h('button', { class: 'btn', onclick: () => add() }, `+ ${t('مناوبة جديدة')}`) : null,
      searchBox(v => { query = v; if (table) table.setQuery(v); else draw(); }, t('ابحث بالمعلم أو الموقع أو الغاية…')),
      h('label', { class: 'inline' }, `${t('العرض')}:`, viewSel)),
    h('div', { class: 'toolbar' },
      h('button', { class: 'btn ghost', onclick: () => report('duty-roster', 'pdf') }, t('طباعة جدول المناوبة PDF')),
      h('button', { class: 'btn ghost', onclick: () => report('duty-roster', 'xlsx') }, t('تصدير Excel')),
      h('button', { class: 'btn ghost', onclick: () => report('duty-teachers', 'pdf') }, t('مناوبات كل معلم')),
      termId ? h('button', { class: 'btn ghost', id: 'notify-duties', onclick: async () => {
        try {
          const r = await api.get(`/api/school-ops/messages?what=duties&term_id=${termId}`);
          await notifyDialog({ title: t('إبلاغ المعلمين المناوبين'), messages: r.messages, canSend: canEdit(),
                               send: body => api.post('/api/duty-assignments/notify', { term_id: termId, ...body }) });
        } catch (e) { toastError(e); }
      } }, t('إبلاغ المناوبين')) : null,
      canEdit() && terms.length > 1 ? h('button', { class: 'btn ghost', onclick: copyFrom }, t('نسخ من فصل آخر')) : null,
      isAdmin() ? h('button', { class: 'btn ghost', id: 'edit-lists', onclick: async () => {
        if (await editLists(mod, DUTY_LISTS)) { mod = await loadModule('duties'); swap(root); render(root); }
      } }, t('تعديل القوائم: الغايات والمواقع والفترات')) : null,
      isAdmin() ? h('button', { class: 'btn ghost', onclick: async () => {
        if (await editModule(mod)) { mod = await loadModule('duties'); swap(root); render(root); }
      } }, t('تسميات الحقول والحقول الإضافية')) : null),
    issuesHost, host);
  await load();
}
