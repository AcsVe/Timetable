// Bell schedules (timing templates) and which template applies to each grade on each day.
import * as api from '../api.js';
import { countAr, t } from '../i18n.js';
import { byId, canEdit, currentTimetable, invalidate, list } from '../store.js';
import { confirmBox, h, jumpTo, nameOf, openForm, pageNav, put, swap, toast, toastError } from '../ui.js';

const toMin = s => { const [a, b] = String(s).slice(0, 5).split(':').map(Number); return a * 60 + b; };
const toTime = m => `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;

export async function render(root) {
  const [stages, grades, terms, weekdays] = await Promise.all([list('stages'), list('grades'), list('terms'), list('weekdays')]);
  const days = weekdays.filter(d => d.is_school_day).sort((a, b) => a.sort_order - b.sort_order);
  const tt = currentTimetable();
  let termId = sessionStorage.getItem('bells:term') || tt?.term_id || terms[0]?.id || '';
  let stageId = sessionStorage.getItem('bells:stage') || stages[0]?.id || '';
  let selectedSchedule = null;
  const schedHost = h('div');
  const editorHost = h('div');
  const assignHost = h('div');

  // -------------------------------------------------------------- templates
  async function drawSchedules() {
    const scheds = await list('bell-schedules');
    const st = byId(stages);
    swap(schedHost, 
      h('div', { class: 'toolbar' },
        canEdit() ? h('button', { class: 'btn', onclick: newSchedule }, `+ ${t('قالب توقيت جديد')}`) : null),
      scheds.length ? h('table', { class: 'data' },
        h('thead', {}, h('tr', {}, [t('القالب'), t('المرحلة'), t('عدد الحصص'), t('من'), t('إلى'), ''].map(x => h('th', {}, x)))),
        h('tbody', {}, scheds.map(s => {
          const lessons = s.slots.filter(x => x.kind === 'lesson');
          return h('tr', {},
            h('td', {}, nameOf(s)), h('td', {}, s.stage_id ? nameOf(st[s.stage_id]) : t('عامّ لجميع المراحل')),
            h('td', {}, lessons.length), h('td', {}, s.slots[0]?.starts_at.slice(0, 5) || ''),
            h('td', {}, s.slots.at(-1)?.ends_at.slice(0, 5) || ''),
            h('td', { style: { whiteSpace: 'nowrap' } },
              h('button', { class: 'btn small ghost', onclick: () => { selectedSchedule = s; drawEditor(); jumpTo('slots'); } }, t('تعديل الحصص')), ' ',
              canEdit() ? h('button', { class: 'btn small ghost', onclick: () => cloneSchedule(s) }, t('نسخ كقالب جديد')) : null, ' ',
              canEdit() ? h('button', { class: 'btn small ghost', onclick: () => removeSchedule(s) }, t('حذف')) : null));
        })))
        : h('p', { class: 'muted' }, t('لا توجد قوالب بعد')));
  }

  const stageOpts = () => stages.map(s => ({ value: s.id, label: nameOf(s) }));
  const newSchedule = () => openForm({ title: t('قالب توقيت جديد'), fields: [
    { name: 'name_ar', label: t('اسم القالب'), required: true, placeholder: t('دوام عادي') },
    { name: 'stage_id', label: t('المرحلة'), type: 'select', options: stageOpts() },
    { name: 'start', label: t('موعد بدء الحصة الأولى'), type: 'time', required: true },
    { name: 'count', label: t('عدد الحصص'), type: 'number', min: 1, max: 12, required: true },
    { name: 'length', label: t('مدة الحصة (بالدقائق)'), type: 'number', min: 10, required: true },
    { name: 'breaks', label: t('استراحة بعد الحصص (مثال: 3، 5)'), placeholder: '3' },
    { name: 'break_length', label: t('مدة الاستراحة (بالدقائق)'), type: 'number', min: 5 }],
    values: { start: '07:45', count: 7, length: 45, breaks: '3', break_length: 20, stage_id: stageId },
    onSubmit: async v => {
      const breaks = new Set(String(v.breaks || '').split(/[,،\s]+/).filter(Boolean).map(Number));
      const slots = [];
      let m = toMin(v.start), slot = 1;
      for (let p = 1; p <= v.count; p++) {
        slots.push({ slot_no: slot++, kind: 'lesson', period_no: p, starts_at: toTime(m), ends_at: toTime(m + v.length) });
        m += v.length;
        if (breaks.has(p) && p < v.count) {
          slots.push({ slot_no: slot++, kind: 'break', period_no: null, label_ar: t('الاستراحة'), starts_at: toTime(m),
                       ends_at: toTime(m + (v.break_length || 20)) });
          m += v.break_length || 20;
        }
      }
      const s = await api.post('/api/bell-schedules', { name_ar: v.name_ar, stage_id: v.stage_id, slots });
      invalidate('bell-schedules');
      selectedSchedule = s;
      await drawSchedules(); drawEditor(); await drawAssignments();
    } });
  const cloneSchedule = s => openForm({ title: t('نسخ كقالب جديد'), values: { name_ar: `${s.name_ar} (${t('نسخة')})` },
    fields: [{ name: 'name_ar', label: t('اسم القالب'), required: true }],
    onSubmit: async v => {
      const c = await api.post('/api/bell-schedules', { name_ar: v.name_ar, stage_id: s.stage_id, slots: s.slots });
      invalidate('bell-schedules'); selectedSchedule = c; await drawSchedules(); drawEditor(); await drawAssignments();
    } });
  async function removeSchedule(s) {
    if (!(await confirmBox(t('أتريد حذف هذا السجل؟')))) return;
    try { await api.del(`/api/bell-schedules/${s.id}`, s.version); invalidate('bell-schedules'); await drawSchedules(); }
    catch (e) { toastError(e); }
  }

  // -------------------------------------------------------------- slot editor
  function drawEditor() {
    if (!selectedSchedule) { swap(editorHost, ); return; }
    const s = selectedSchedule;
    let rows = s.slots.map(x => ({ ...x, starts_at: x.starts_at.slice(0, 5), ends_at: x.ends_at.slice(0, 5) }));
    const body = h('tbody');
    function renumber() {
      let p = 0;
      rows.forEach((r, i) => { r.slot_no = i + 1; r.period_no = r.kind === 'lesson' ? ++p : null; });
    }
    function drawRows() {
      renumber();
      body.replaceChildren(...rows.map((r, i) => h('tr', {},
        h('td', {}, r.kind === 'lesson' ? `${t('الحصة')} ${r.period_no}` : ''),
        h('td', {}, h('select', { disabled: !canEdit(), onchange: e => { r.kind = e.target.value; drawRows(); } },
          h('option', { value: 'lesson', selected: r.kind === 'lesson' }, t('حصة')),
          h('option', { value: 'break', selected: r.kind === 'break' }, t('استراحة')))),
        h('td', {}, h('input', { value: r.label_ar || '', disabled: !canEdit(), oninput: e => { r.label_ar = e.target.value || null; } })),
        h('td', {}, h('input', { type: 'time', value: r.starts_at, disabled: !canEdit(), oninput: e => { r.starts_at = e.target.value; } })),
        h('td', {}, h('input', { type: 'time', value: r.ends_at, disabled: !canEdit(), oninput: e => { r.ends_at = e.target.value; } })),
        h('td', {}, canEdit() ? h('button', { class: 'btn small ghost', onclick: () => { rows.splice(i, 1); drawRows(); } }, '×') : null))));
    }
    function addRow(kind) {
      const last = rows.at(-1);
      const start = last ? toMin(last.ends_at) : 7 * 60 + 45;
      rows.push({ kind, label_ar: kind === 'break' ? t('الاستراحة') : null, starts_at: toTime(start),
                  ends_at: toTime(start + (kind === 'lesson' ? 45 : 20)) });
      drawRows();
    }
    async function saveSlots() {
      try {
        const payload = rows.map(({ slot_no, kind, period_no, label_ar, starts_at, ends_at }) =>
          ({ slot_no, kind, period_no, label_ar: label_ar || null, starts_at, ends_at }));
        selectedSchedule = await api.patch(`/api/bell-schedules/${s.id}`, { version: s.version, slots: payload });
        invalidate('bell-schedules');
        toast(t('تم الحفظ'), 'ok');
        await drawSchedules(); drawEditor();
      } catch (e) { toastError(e); }
    }
    drawRows();
    swap(editorHost, h('div', { class: 'stat', id: 'slots', style: { marginTop: '14px' } },
      h('h3', {}, `${t('حصص القالب')}: ${nameOf(s)}`),
      h('table', { class: 'data' }, h('thead', {}, h('tr', {},
        ['', t('النوع'), t('التسمية'), t('من'), t('إلى'), ''].map(x => h('th', {}, x)))), body),
      canEdit() ? h('div', { class: 'toolbar', style: { marginTop: '10px' } },
        h('button', { class: 'btn ghost small', onclick: () => addRow('lesson') }, `+ ${t('حصة')}`),
        h('button', { class: 'btn ghost small', onclick: () => addRow('break') }, `+ ${t('استراحة')}`),
        h('div', { class: 'spacer' }),
        h('button', { class: 'btn', onclick: saveSlots }, t('حفظ الحصص'))) : null));
  }

  // -------------------------------------------------------------- assignment grid
  async function drawAssignments() {
    if (!termId || !stageId) { swap(assignHost, h('p', { class: 'muted' }, t('أضف فصلاً دراسياً ومرحلة أولاً'))); return; }
    const [scheds, assigns] = await Promise.all([
      list('bell-schedules'), list('bell-assignments', `?term_id=${termId}&stage_id=${stageId}`)]);
    const stageGrades = grades.filter(g => g.stage_id === stageId).sort((a, b) => a.sort_order - b.sort_order);
    const find = (gradeId, dayId) => assigns.find(a => a.weekday_id === dayId && (a.grade_id || null) === gradeId);
    const opts = scheds.filter(s => !s.stage_id || s.stage_id === stageId);

    const cell = (gradeId, day) => {
      const a = find(gradeId, day.id);
      const sel = h('select', { disabled: !canEdit(), dataset: { grade: gradeId || '', day: day.id },
        onchange: e => setCell(gradeId, day, a, e.target.value) },
        h('option', { value: '' }, gradeId ? t('— وفق المرحلة —') : t('— بدون —')),
        opts.map(s => h('option', { value: s.id, selected: a && a.bell_schedule_id === s.id }, nameOf(s))));
      return h('td', {}, sel);
    };
    const rows = [
      h('tr', {}, h('th', {}, t('جميع صفوف المرحلة')), days.map(d => cell(null, d))),
      ...stageGrades.map(g => h('tr', {}, h('th', {}, nameOf(g)), days.map(d => cell(g.id, d)))),
    ];

    // bulk "apply to…" tool
    const bulkSched = h('select', {}, opts.map(s => h('option', { value: s.id }, nameOf(s))));
    const dayChecks = days.map(d => h('label', { class: 'inline' }, h('input', { type: 'checkbox', value: d.id, checked: true }), nameOf(d)));
    const gradeChecks = stageGrades.map(g => h('label', { class: 'inline' }, h('input', { type: 'checkbox', value: g.id }), nameOf(g)));
    async function applyBulk() {
      const weekday_ids = dayChecks.map(l => l.firstChild).filter(i => i.checked).map(i => i.value);
      const grade_ids = gradeChecks.map(l => l.firstChild).filter(i => i.checked).map(i => i.value);
      if (!bulkSched.value || !weekday_ids.length) { toast(t('اختر قالباً ويوماً واحداً على الأقل'), 'err'); return; }
      try {
        const r = await api.post('/api/bell-assignments/bulk', { term_id: termId, stage_id: stageId,
          bell_schedule_id: bulkSched.value, weekday_ids, grade_ids: grade_ids.length ? grade_ids : null });
        toast(`${t('تم التطبيق')}: ${countAr(r.created + r.updated, 'record')}`, 'ok');
        invalidate('bell-assignments'); await drawAssignments();
      } catch (e) { toastError(e); }
    }

    swap(assignHost, 
      h('table', { class: 'data bell-grid' }, h('thead', {}, h('tr', {}, h('th'), days.map(d => h('th', {}, nameOf(d))))),
        h('tbody', {}, rows)),
      canEdit() && opts.length ? h('div', { class: 'stat', id: 'bulk', style: { marginTop: '14px' } },
        h('h3', {}, t('تطبيق قالب على عدة أيام وصفوف دفعةً واحدة')),
        h('div', { class: 'toolbar' }, `${t('القالب')}:`, bulkSched),
        h('div', { class: 'toolbar' }, `${t('الأيام')}:`, dayChecks),
        h('div', { class: 'toolbar' }, `${t('الصفوف')}:`, gradeChecks,
          h('span', { class: 'muted' }, t('(عدم الاختيار يعني جميع صفوف المرحلة)'))),
        h('button', { class: 'btn', onclick: applyBulk }, t('تطبيق'))) : null);
  }

  async function setCell(gradeId, day, existing, scheduleId) {
    try {
      if (!scheduleId) {
        if (existing) await api.del(`/api/bell-assignments/${existing.id}`, existing.version);
      } else {
        await api.post('/api/bell-assignments/bulk', { term_id: termId, stage_id: stageId, bell_schedule_id: scheduleId,
                                                       weekday_ids: [day.id], grade_ids: gradeId ? [gradeId] : null });
      }
      invalidate('bell-assignments');
      toast(t('تم الحفظ'), 'ok');
    } catch (e) { toastError(e); }
    await drawAssignments();
  }

  const termSel = h('select', { onchange: e => { termId = e.target.value; sessionStorage.setItem('bells:term', termId); drawAssignments(); } },
    terms.map(x => h('option', { value: x.id, selected: x.id === termId }, nameOf(x))));
  const stageSel = h('select', { onchange: e => { stageId = e.target.value; sessionStorage.setItem('bells:stage', stageId); drawAssignments(); } },
    stages.map(x => h('option', { value: x.id, selected: x.id === stageId }, nameOf(x))));

  put(root, 
    h('h1', { class: 'title' }, t('توقيت الحصص')),
    h('p', { class: 'muted' }, t('أنشئ قوالب التوقيت (مثل: دوام عادي، يوم قصير)، ثم حدِّد القالب لكل يوم ولكل صف. والصف الذي لا يُحدَّد له قالب يأخذ قالب مرحلته. ويُحتسَب تعارض المعلمين على رقم الحصة لا على وقتها.')),
    pageNav([{ id: 'templates', label: t('قوالب التوقيت') }, { id: 'assign', label: t('التوقيت لكل يوم وصف') },
             { id: 'bulk', label: t('تطبيق قالب على عدة أيام وصفوف دفعةً واحدة') }]),
    h('h2', { id: 'templates' }, t('قوالب التوقيت')), schedHost, editorHost,
    h('h2', { id: 'assign', style: { marginTop: '24px' } }, t('التوقيت لكل يوم وصف')),
    h('div', { class: 'toolbar' }, `${t('الفصل')}:`, termSel, `${t('المرحلة')}:`, stageSel),
    assignHost);
  await Promise.all([drawSchedules(), drawAssignments()]);
}
