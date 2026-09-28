// Lessons: what must be taught (subject × sections/groups × teachers × periods per week).
import * as api from '../api.js';
import { t } from '../i18n.js';
import { canEdit } from '../store.js';
import { confirmBox, h, nameOf, openForm, toast, toastError, put, swap } from '../ui.js';
import { loadContext, noTimetable } from './ctx.js';

export async function render(root) {
  let ctx = await loadContext();
  if (!ctx) return noTimetable(root);
  const f = JSON.parse(sessionStorage.getItem('lessons:filter') || '{}');
  const host = h('div');
  const loadHost = h('div');

  const targetOptions = () => {
    const out = [];
    for (const s of ctx.sortedSections()) {
      out.push({ value: `sec:${s.id}`, label: `${ctx.sectionLabel(s.id)} — ${t('كامل الشعبة')}` });
      for (const d of ctx.divisions.filter(d => d.section_id === s.id)) {
        for (const g of ctx.groups.filter(g => g.division_id === d.id)) {
          out.push({ value: `grp:${s.id}:${g.id}`, label: `${ctx.sectionLabel(s.id)} — ${d.name}: ${nameOf(g)}` });
        }
      }
    }
    return out;
  };
  const encodeTargets = l => l.targets.map(tg => (tg.group_id ? `grp:${tg.section_id}:${tg.group_id}` : `sec:${tg.section_id}`));
  const decodeTargets = vals => vals.map(v => {
    const [k, s, g] = v.split(':');
    return k === 'grp' ? { section_id: s, group_id: g } : { section_id: s, group_id: null };
  });

  function formFields() {
    return [
      { name: 'subject_id', label: t('المبحث'), type: 'select', required: true,
        options: ctx.subjects.map(s => ({ value: s.id, label: nameOf(s) })) },
      { name: 'periods_per_week', label: t('عدد الحصص أسبوعياً'), type: 'number', min: 1, required: true },
      { name: 'duration', label: t('مدة البطاقة'), type: 'select', required: true,
        options: [1, 2, 3, 4].map(n => ({ value: n, label: n === 1 ? t('حصة مفردة') : n === 2 ? t('حصة مزدوجة') : `${n} ${t('حصص متتالية')}` })) },
      { name: 'preferred_room_id', label: t('القاعة المفضلة'), type: 'select', options: ctx.rooms.map(r => ({ value: r.id, label: nameOf(r) })) },
      { name: 'teachers', label: t('المعلمون'), type: 'multi',
        options: [...ctx.teachers].sort((a, b) => nameOf(a).localeCompare(nameOf(b), 'ar')).map(x => ({ value: x.id, label: nameOf(x) })) },
      { name: 'targets', label: t('الشعب / المجموعات (اختيار أكثر من شعبة يعني درساً مشتركاً)'), type: 'multi', options: targetOptions() },
      { name: 'notes', label: t('ملاحظات'), type: 'textarea' },
    ];
  }

  async function reload() { ctx = await loadContext(); draw(); }

  async function save(v, lesson) {
    const body = { subject_id: v.subject_id, periods_per_week: v.periods_per_week, duration: Number(v.duration),
                   preferred_room_id: v.preferred_room_id, notes: v.notes,
                   teachers: v.teachers.map(id => ({ teacher_id: id })), targets: decodeTargets(v.targets) };
    let r;
    if (lesson) r = await api.patch(`/api/lessons/${lesson.id}`, { ...body, version: lesson.version });
    else r = await api.post('/api/lessons', { ...body, timetable_id: ctx.tt.id });
    toast(r.cards_reset ? t('تم الحفظ، وأُعيد إنشاء البطاقات لتغيّر مدتها') : t('تم الحفظ'), 'ok');
    await reload();
  }
  const add = () => openForm({ title: t('درس جديد'), fields: formFields(),
    values: { periods_per_week: 1, duration: 1, subject_id: f.subject || undefined, teachers: f.teacher ? [f.teacher] : [],
              targets: f.section ? [`sec:${f.section}`] : [] },
    onSubmit: v => save(v, null) });
  const edit = l => openForm({ title: t('تعديل الدرس'), fields: formFields(),
    values: { ...l, teachers: l.teachers.map(x => x.teacher_id), targets: encodeTargets(l) }, onSubmit: v => save(v, l) });
  async function remove(l) {
    if (!(await confirmBox(t('أتريد حذف الدرس وجميع بطاقاته من الجدول؟')))) return;
    try { await api.del(`/api/lessons/${l.id}`, l.version); toast(t('تم الحذف'), 'ok'); await reload(); }
    catch (e) { toastError(e); }
  }

  function matches(l) {
    if (f.subject && l.subject_id !== f.subject) return false;
    if (f.teacher && !l.teachers.some(x => x.teacher_id === f.teacher)) return false;
    if (f.section && !l.targets.some(x => x.section_id === f.section)) return false;
    if (f.stage && !l.targets.some(x => ctx.grade[ctx.section[x.section_id]?.grade_id]?.stage_id === f.stage)) return false;
    return true;
  }

  function draw() {
    const rows = ctx.lessons.filter(matches).map(l => {
      const total = l.cards.reduce((a, c) => a + c.duration, 0);
      const placed = l.cards.filter(c => c.weekday_id).reduce((a, c) => a + c.duration, 0);
      const subj = ctx.subject[l.subject_id];
      return h('tr', { dataset: { id: l.id } },
        h('td', {}, h('span', { class: 'swatch', style: { background: subj?.color || '#dbe7f7' } }), ' ', nameOf(subj)),
        h('td', {}, l.targets.map(tg => h('span', { class: 'chip' }, ctx.targetLabel(tg)))),
        h('td', {}, l.teachers.map(x => h('span', { class: 'chip' }, nameOf(ctx.teacher[x.teacher_id])))),
        h('td', {}, l.periods_per_week),
        h('td', {}, l.duration === 1 ? t('مفردة') : l.duration === 2 ? t('مزدوجة') : l.duration),
        h('td', { class: placed < total ? 'muted' : '' }, `${placed} / ${total}`),
        h('td', { style: { whiteSpace: 'nowrap' } }, canEdit() && !ctx.readOnly ? [
          h('button', { class: 'btn small ghost', onclick: () => edit(l) }, t('تعديل')), ' ',
          h('button', { class: 'btn small ghost', onclick: () => remove(l) }, t('حذف'))] : null));
    });
    swap(host, rows.length
      ? h('table', { class: 'data' }, h('thead', {}, h('tr', {},
          [t('المبحث'), t('الشعب / المجموعات'), t('المعلمون'), t('الحصص أسبوعياً'), t('المدة'), t('المُدرَج في الجدول'), ''].map(x => h('th', {}, x)))),
          h('tbody', {}, rows))
      : h('p', { class: 'muted' }, t('لا توجد دروس مطابقة')));
    drawLoads();
  }

  function drawLoads() {
    const load = {};
    for (const l of ctx.lessons) for (const x of l.teachers) load[x.teacher_id] = (load[x.teacher_id] || 0) + l.periods_per_week;
    const rows = [...ctx.teachers].filter(x => load[x.id] || x.target_weekly_periods)
      .sort((a, b) => nameOf(a).localeCompare(nameOf(b), 'ar')).map(x => {
        const n = load[x.id] || 0, target = x.target_weekly_periods;
        const cls = target == null ? '' : n > target ? 'reasons' : n < target ? 'muted' : '';
        return h('tr', {}, h('td', {}, nameOf(x)), h('td', { class: cls }, n), h('td', {}, target ?? '—'));
      });
    swap(loadHost, rows.length ? h('details', {}, h('summary', {}, t('ملخص نصاب المعلمين')),
      h('table', { class: 'data', style: { marginTop: '8px', maxWidth: '520px' } },
        h('thead', {}, h('tr', {}, [t('المعلم'), t('المُسنَد'), t('النصاب')].map(x => h('th', {}, x)))), h('tbody', {}, rows))) : '');
  }

  const setF = (k, v) => { f[k] = v || undefined; sessionStorage.setItem('lessons:filter', JSON.stringify(f)); draw(); };
  const sel = (k, label, opts) => h('label', { class: 'inline' }, `${label}:`, h('select', { onchange: e => setF(k, e.target.value) },
    h('option', { value: '' }, t('الكل')), opts.map(o => h('option', { value: o.value, selected: o.value === f[k] }, o.label))));

  put(root, h('h1', { class: 'title' }, `${t('الدروس والتوزيع')} — ${ctx.tt.name}`),
    ctx.readOnly ? h('p', { class: 'reasons' }, t('هذا الجدول مؤرشف وللقراءة فقط')) : null,
    h('div', { class: 'toolbar sticky' },
      canEdit() && !ctx.readOnly ? h('button', { class: 'btn', onclick: add }, `+ ${t('درس جديد')}`) : null,
      sel('stage', t('المرحلة'), ctx.stages.map(s => ({ value: s.id, label: nameOf(s) }))),
      sel('section', t('الشعبة'), ctx.sortedSections().map(s => ({ value: s.id, label: ctx.sectionLabel(s.id) }))),
      sel('teacher', t('المعلم'), ctx.teachers.map(x => ({ value: x.id, label: nameOf(x) }))),
      sel('subject', t('المبحث'), ctx.subjects.map(x => ({ value: x.id, label: nameOf(x) })))),
    loadHost, host);
  draw();
}
