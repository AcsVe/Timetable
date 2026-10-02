// Meetings (department meetings, heads of department…): a lesson with members and no classes. It blocks
// its members like a lesson, shows in their timetables and in the teachers' master sheet under its title,
// and may be left out of the teaching load. Its time is set here, in the grid, or by the generator.
import * as api from '../api.js';
import { t } from '../i18n.js';
import { byId, currentTimetable, isAdmin, list } from '../store.js';
import { bulkTable, confirmBox, h, nameOf, openForm, put, searchBox, swap, toast, toastError } from '../ui.js';
import { noTimetable } from './ctx.js';
import { notifyDialog } from './notify.js';

export async function render(root) {
  const tt = currentTimetable();
  if (!tt) return noTimetable(root);
  const [teachers, subjects, stages, rooms, weekdays, scheds] = await Promise.all([
    list('teachers'), list('subjects'), list('stages'), list('rooms'), list('weekdays'), list('bell-schedules')]);
  const teacher = byId(teachers), room = byId(rooms), day = byId(weekdays), sched = byId(scheds);
  const days = weekdays.filter(d => d.is_school_day).sort((a, b) => a.sort_order - b.sort_order);
  const readOnly = tt.status === 'archived';
  const editable = isAdmin() && !readOnly;
  const sorted = [...teachers].sort((a, b) => nameOf(a).localeCompare(nameOf(b), 'ar'));
  const realSubjects = subjects.filter(s => s.name_ar !== 'اجتماع');
  let meetings = [];
  let query = '';
  let table = null;
  const host = h('div');
  const summary = h('p', { class: 'muted small count' });

  async function load() {
    const r = await api.get(`/api/timetables/${tt.id}/lessons`);
    meetings = r.items.filter(l => l.kind === 'meeting').map(l => ({ ...l, cards: l.cards.sort((a, b) => (a.created_at < b.created_at ? -1 : 1)) }));
    draw();
  }

  const when = l => {
    const placed = l.cards.filter(c => c.weekday_id);
    if (!placed.length) return h('span', { class: 'chip warn' }, t('لم يُحدَّد موعده'));
    return placed.map(c => h('span', { class: 'chip' }, `${nameOf(day[c.weekday_id])} — ${t('الحصة')} ${c.period_no}`,
      c.duration > 1 ? `–${c.period_no + c.duration - 1}` : '', c.is_locked ? ' 🔒' : ''));
  };
  const members = l => l.teachers.map(x => nameOf(teacher[x.teacher_id])).filter(Boolean);

  function draw() {
    const unplaced = meetings.filter(l => l.cards.some(c => !c.weekday_id)).length;
    summary.textContent = unplaced ? `${t('لم يُحدَّد موعدها')}: ${unplaced} ${t('من')} ${meetings.length}` : '';
    table = bulkTable({
      items: meetings,
      text: l => [l.title, ...members(l), nameOf(room[l.preferred_room_id])].join(' '),
      columns: [
        { label: t('الاجتماع'), get: l => h('b', {}, l.title) },
        { label: t('الموعد'), get: when },
        { label: t('الأعضاء'), get: l => h('span', { title: members(l).join('، ') }, `${members(l).length} — `,
          h('span', { class: 'muted small' }, members(l).slice(0, 4).join('، ') + (members(l).length > 4 ? '…' : ''))) },
        { label: t('القاعة'), get: l => nameOf(room[l.preferred_room_id]) || '—' },
        { label: t('التوقيت'), get: l => (l.bell_schedule_id ? nameOf(sched[l.bell_schedule_id]) : t('توقيت المدرسة')) },
        { label: t('ضمن النصاب'), get: l => (l.counts_load ? t('نعم') : t('لا')) },
      ],
      actions: l => (editable ? [h('button', { class: 'btn small ghost', onclick: () => edit(l) }, t('تعديل')), ' ',
                                 h('button', { class: 'btn small ghost danger-text', onclick: () => remove(l) }, t('حذف'))] : null),
      onBulkDelete: editable ? async items => {
        for (const l of items) await api.del(`/api/lessons/${l.id}`, l.version);
        toast(`${t('تم الحذف')}: ${items.length}`, 'ok'); await load();
      } : null,
      emptyText: t('لا توجد اجتماعات بعد. أضف اجتماعاً لكل قسم أو لرؤساء الأقسام.'),
    });
    table.setQuery(query);
    swap(host, table.el);
  }

  // ------------------------------------------------------------------ form
  const teacherOpts = sorted.map(x => ({ value: x.id, label: `${nameOf(x)}${x.is_head ? ` — ${t('رئيس قسم')}` : ''}` }));
  const fields = () => [
    { name: 'title', label: t('عنوان الاجتماع'), required: true, full: true, placeholder: t('مثال: اجتماع قسم الحاسوب') },
    { name: 'teachers', label: t('الأعضاء'), type: 'multi', options: teacherOpts },
    { name: 'periods_per_week', label: t('عدد مرات الاجتماع في الأسبوع'), type: 'number', min: 1, max: 10, required: true },
    { name: 'duration', label: t('مدة الاجتماع (عدد الحصص المتتالية)'), type: 'select', required: true,
      options: [1, 2, 3].map(n => ({ value: String(n), label: String(n) })) },
    { name: 'weekday_id', label: t('اليوم (اختياري)'), type: 'select', options: days.map(d => ({ value: d.id, label: nameOf(d) })),
      help: t('اتركه فارغاً ليحدده المولّد التلقائي أو لتسحبه في الشبكة') },
    { name: 'period_no', label: t('الحصة (اختياري)'), type: 'number', min: 1, max: 20, placeholder: '7' },
    { name: 'is_locked', label: t('تثبيت الموعد فلا يغيّره المولّد'), type: 'bool' },
    { name: 'preferred_room_id', label: t('القاعة (اختياري)'), type: 'select', options: rooms.map(r => ({ value: r.id, label: nameOf(r) })) },
    { name: 'bell_schedule_id', label: t('التوقيت الذي تُحسب عليه ساعة الاجتماع'), type: 'select',
      options: scheds.map(s => ({ value: s.id, label: nameOf(s) })),
      help: t('اتركه فارغاً لتُقبل أي حصة موجودة في توقيت المدرسة ذلك اليوم') },
    { name: 'counts_load', label: t('يُحسب ضمن نصاب المعلمين'), type: 'bool' },
    { name: 'notes', label: t('ملاحظات'), type: 'textarea', full: true },
  ];
  // quick ways to fill the members: a department (teachers of a subject), heads of department, a stage
  function quickAdd() {
    const pick = ids => {
      const box = document.querySelector('#f-teachers .multi-opts');
      if (!box) return;
      let n = 0;
      box.querySelectorAll('input').forEach(i => { if (ids.has(i.value) && !i.checked) { i.checked = true; n++; } });
      box.dispatchEvent(new Event('change', { bubbles: true }));
      toast(`${t('أُضيف')}: ${n}`, 'ok');
    };
    const bySubject = h('select', { 'aria-label': t('معلمو مبحث') },
      h('option', { value: '' }, t('— معلمو مبحث (قسم) —')),
      realSubjects.map(s => h('option', { value: s.id }, `${nameOf(s)} (${teachers.filter(x => (x.subject_ids || []).includes(s.id)).length})`)));
    const byStage = h('select', { 'aria-label': t('معلمو مرحلة') },
      h('option', { value: '' }, t('— معلمو مرحلة —')),
      stages.map(s => h('option', { value: s.id }, `${nameOf(s)} (${teachers.filter(x => (x.stage_ids || []).includes(s.id)).length})`)));
    const heads = teachers.filter(x => x.is_head);
    return h('div', { class: 'full quick-add' },
      h('b', {}, t('إضافة سريعة للأعضاء')),
      h('div', { class: 'toolbar' },
        bySubject, h('button', { type: 'button', class: 'btn small ghost', onclick: () => {
          if (bySubject.value) pick(new Set(teachers.filter(x => (x.subject_ids || []).includes(bySubject.value)).map(x => x.id)));
        } }, t('إضافة')),
        byStage, h('button', { type: 'button', class: 'btn small ghost', onclick: () => {
          if (byStage.value) pick(new Set(teachers.filter(x => (x.stage_ids || []).includes(byStage.value)).map(x => x.id)));
        } }, t('إضافة')),
        h('button', { type: 'button', class: 'btn small ghost', id: 'add-heads', onclick: () => {
          if (!heads.length) { toast(t('لم يُحدَّد أي رئيس قسم بعد؛ حدِّده من صفحة المعلمين'), 'err'); return; }
          pick(new Set(heads.map(x => x.id)));
        } }, `${t('رؤساء الأقسام')} (${heads.length})`)),
      h('p', { class: 'muted small' }, t('تُضاف الأسماء إلى المحددين، ويمكنك بعدها إزالة من لا يحضر.')));
  }
  const toValues = l => {
    const c = l?.cards?.[0];
    return l ? { title: l.title, teachers: l.teachers.map(x => x.teacher_id), periods_per_week: l.periods_per_week,
                 duration: String(l.duration), weekday_id: c?.weekday_id || '', period_no: c?.period_no ?? null,
                 is_locked: !!c?.is_locked, preferred_room_id: l.preferred_room_id || '', bell_schedule_id: l.bell_schedule_id || '',
                 counts_load: l.counts_load, notes: l.notes }
      : { periods_per_week: 1, duration: '1', weekday_id: '', counts_load: false, is_locked: true };
  };
  async function save(v, l) {
    if (!v.teachers.length) throw new Error(t('اختر أعضاء الاجتماع (معلماً واحداً على الأقل)'));
    if ((v.weekday_id && !v.period_no) || (!v.weekday_id && v.period_no)) throw new Error(t('اختر اليوم والحصة معاً، أو اتركهما فارغين'));
    const body = { kind: 'meeting', title: v.title, teachers: v.teachers.map(id => ({ teacher_id: id })),
                   periods_per_week: v.periods_per_week, duration: Number(v.duration), preferred_room_id: v.preferred_room_id || null,
                   bell_schedule_id: v.bell_schedule_id || null, counts_load: !!v.counts_load, notes: v.notes };
    const saved = l ? await api.patch(`/api/lessons/${l.id}`, { ...body, version: l.version })
      : await api.post('/api/lessons', { ...body, timetable_id: tt.id });
    // the first meeting of the week goes to the chosen day and period
    const card = [...saved.cards].sort((a, b) => (a.created_at < b.created_at ? -1 : 1))[0];
    if (card) {
      const want = v.weekday_id ? { weekday_id: v.weekday_id, period_no: v.period_no } : null;
      const moved = want && (card.weekday_id !== want.weekday_id || card.period_no !== want.period_no);
      const lockChange = !!v.is_locked !== !!card.is_locked;
      if (moved || lockChange || (!want && card.weekday_id && l)) {
        try {
          await api.patch(`/api/cards/${card.id}`, { version: card.version, ...(want || { weekday_id: null, period_no: null }),
                                                     is_locked: want ? !!v.is_locked : false });
        } catch (e) {
          await load();
          toastError(e);
          return true;      // the meeting is saved; only its time could not be set
        }
      }
    }
    toast(t('تم الحفظ'), 'ok');
    await load();
    return true;
  }
  // the quick-add tools sit right under the members list
  const withQuick = p => { const q = quickAdd(); document.querySelector('#f-teachers')?.closest('.field')?.after(q); return p; };
  const add = () => withQuick(openForm({ title: t('اجتماع جديد'), fields: fields(), values: toValues(null), onSubmit: v => save(v, null) }));
  const edit = l => withQuick(openForm({ title: `${t('تعديل')} — ${l.title}`, fields: fields(), values: toValues(l), onSubmit: v => save(v, l) }));
  async function remove(l) {
    if (!(await confirmBox(`${t('أتريد حذف الاجتماع')} «${l.title}»؟`))) return;
    try { await api.del(`/api/lessons/${l.id}`, l.version); toast(t('تم الحذف'), 'ok'); await load(); } catch (e) { toastError(e); }
  }
  async function notify() {
    const r = await api.get(`/api/timetables/${tt.id}/meetings/messages`);
    if (!r.messages.length) { toast(t('لا توجد اجتماعات محددة المواعيد بعد'), 'err'); return; }
    await notifyDialog({ title: t('إبلاغ أعضاء الاجتماعات'), messages: r.messages, canSend: isAdmin(),
                         send: body => api.post(`/api/timetables/${tt.id}/meetings/notify`, body) });
  }
  const report = fmt => {
    if (fmt === 'screen') { sessionStorage.setItem('reports', JSON.stringify({ kind: 'meetings' })); location.hash = '#/reports'; return; }
    window.open(`/api/timetables/${tt.id}/reports/meetings?format=${fmt}`, '_blank');
  };

  put(root, h('h1', { class: 'title' }, `${t('الاجتماعات')} — ${tt.name}`),
    h('p', { class: 'muted' }, t('اجتماع القسم أو رؤساء الأقسام حصةٌ بلا صف: تمنع إعطاء أعضائها حصصاً في وقتها، وتظهر في جدول كل معلم وفي الجدول العام للمعلمين. ويمكنك أن تحدد موعدها هنا، أو تسحبها في شبكة الجدول (عرض المعلم)، أو تتركها للمولّد التلقائي ليختار حصةً يتفرغ فيها جميع الأعضاء.')),
    readOnly ? h('p', { class: 'reasons' }, t('هذا الجدول مؤرشف وللقراءة فقط')) : null,
    h('div', { class: 'toolbar sticky' },
      editable ? h('button', { class: 'btn', id: 'add-meeting', onclick: add }, `+ ${t('اجتماع جديد')}`) : null,
      searchBox(v => { query = v; table && table.setQuery(v); }, t('ابحث بالعنوان أو باسم المعلم…'))),
    h('div', { class: 'toolbar' },
      h('button', { class: 'btn ghost', onclick: () => report('pdf') }, t('طباعة جدول الاجتماعات PDF')),
      h('button', { class: 'btn ghost', onclick: () => report('xlsx') }, t('تصدير Excel')),
      h('button', { class: 'btn ghost', id: 'notify-meetings', onclick: () => notify().catch(toastError) }, t('إبلاغ الأعضاء'))),
    summary, host);
  await load();
}
