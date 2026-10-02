// Exam timetable (per term): each exam has a date, a session and times, a stage / grades and a subject,
// and is held in one or more rooms — each with its location, sections and invigilating teachers.
import * as api from '../api.js';
import { lang, t } from '../i18n.js';
import { byId, canEdit, currentTimetable, isAdmin, list } from '../store.js';
import { bulkTable, confirmBox, h, multiPicker, nameOf, openForm, put, searchBox, swap, toast, toastError } from '../ui.js';
import { notifyDialog } from './notify.js';
import { collectExtra, editModule, extraFields, extraLabel, extraText, extraValues, label, loadModule, placeSubFields, title } from './modconf.js';

const DAY_NAMES = { ar: ['الأحد', 'الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت'],
                    en: ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'] };
export const dayOfDate = d => (d ? DAY_NAMES[lang === 'en' ? 'en' : 'ar'][new Date(`${d}T12:00:00`).getDay()] : '');
const hm = x => (x ? String(x).slice(0, 5) : '');
const toMin = x => { const [a, b] = hm(x).split(':').map(Number); return a * 60 + b; };

export async function render(root) {
  const [terms, stages, grades, sections, subjects, teachers, rooms] = await Promise.all([
    list('terms'), list('stages'), list('grades'), list('sections'), list('subjects'), list('teachers'), list('rooms')]);
  let mod = await loadModule('exams');
  const tt = currentTimetable();
  let termId = sessionStorage.getItem('exams:term') || tt?.term_id || terms[0]?.id || '';
  const stage = byId(stages), grade = byId(grades), section = byId(sections), subject = byId(subjects),
        teacher = byId(teachers), room = byId(rooms);
  const teacherName = id => nameOf(teacher[id]) || '?';
  const sectionLabel = id => { const s = section[id]; return s ? `${nameOf(grade[s.grade_id])} / ${nameOf(s)}` : '?'; };
  const teacherOpts = () => [...teachers].sort((a, b) => nameOf(a).localeCompare(nameOf(b), 'ar')).map(x => ({ value: x.id, label: nameOf(x) }));
  let sessions = [];
  let query = '';
  let table = null;
  const host = h('div');
  const issuesHost = h('div');

  const examTitle = e => [e.subject_id ? nameOf(subject[e.subject_id]) : '', e.title || ''].filter(Boolean).join(' — ');
  const roomText = r => [r.room_id ? nameOf(room[r.room_id]) : '', r.location || ''].filter(Boolean).join(' — ');
  const overlaps = (a, b) => a.exam_date === b.exam_date && (a.starts_at && a.ends_at && b.starts_at && b.ends_at
    ? toMin(a.starts_at) < toMin(b.ends_at) && toMin(b.starts_at) < toMin(a.ends_at)
    : !!a.session_label && a.session_label === b.session_label);

  async function load() {
    sessions = termId ? (await api.get(`/api/exam-sessions?term_id=${termId}`)).items : [];
    draw();
    checkIssues();
  }
  async function checkIssues() {
    if (!termId) { swap(issuesHost); return; }
    try {
      const r = await api.get(`/api/school-ops/check?term_id=${termId}&what=exams`);
      swap(issuesHost, r.exams.length ? h('details', { class: 'issues notice warn', open: r.exams.length <= 5 },
        h('summary', {}, `${t('تنبيهات جدول الامتحانات')}: ${r.exams.length}`),
        h('ul', {}, r.exams.map(i => h('li', { class: i.code === 'no_invigilator' ? 'warn' : 'err' }, lang === 'en' ? i.message_en : i.message))))
        : h('p', { class: 'notice ok' }, t('لا توجد تعارضات في المراقبة ولا في القاعات')));
    } catch (e) { swap(issuesHost); }
  }

  function draw() {
    const xs = mod.extra_fields.filter(f => (f.level || 'session') === 'session');
    table = bulkTable({
      items: sessions,
      text: e => [e.exam_date, dayOfDate(e.exam_date), e.session_label, examTitle(e), nameOf(stage[e.stage_id]),
                  ...(e.rooms || []).flatMap(r => [roomText(r), ...(r.teacher_ids || []).map(teacherName), ...(r.section_ids || []).map(sectionLabel)])].join(' '),
      columns: [
        { label: label(mod, 'exam_date'), get: e => h('span', {}, h('b', {}, e.exam_date), ' ', h('span', { class: 'muted' }, dayOfDate(e.exam_date))) },
        { label: `${label(mod, 'session_label')} / ${t('الوقت')}`, get: e => [e.session_label || '', e.starts_at ? h('div', { class: 'muted', dir: 'ltr' }, `${hm(e.starts_at)}–${hm(e.ends_at)}`) : null] },
        { label: `${label(mod, 'stage_id')} / ${label(mod, 'grade_ids')}`, get: e => [nameOf(stage[e.stage_id]), (e.grade_ids || []).map(g => h('span', { class: 'chip' }, nameOf(grade[g])))] },
        { label: label(mod, 'subject_id'), get: e => h('b', {}, examTitle(e)) },
        ...xs.map(f => ({ label: extraLabel(f), get: e => extraText(f, (e.extra || {})[f.key], teacherName) })),
        { label: `${label(mod, 'room_id')} — ${label(mod, 'teacher_ids')}`, get: e => (e.rooms || []).map(r => h('div', { class: 'room-line' },
          h('b', {}, roomText(r) || '—'), (r.section_ids || []).length ? h('span', { class: 'muted' }, ` (${r.section_ids.map(sectionLabel).join('، ')})`) : null,
          ': ', (r.teacher_ids || []).length ? r.teacher_ids.map(x => h('span', { class: 'chip' }, teacherName(x))) : h('span', { class: 'reasons' }, t('بلا مراقب')))) },
      ],
      actions: e => (canEdit() ? [h('button', { class: 'btn small ghost', onclick: () => edit(e) }, t('تعديل')), ' ',
                                  h('button', { class: 'btn small ghost', onclick: () => duplicate(e) }, t('نسخ')), ' ',
                                  h('button', { class: 'btn small ghost', onclick: () => remove(e) }, t('حذف'))] : null),
      onBulkDelete: canEdit() ? async items => {
        const r = await api.post('/api/exam-sessions/bulk-delete', { items: items.map(x => ({ id: x.id, version: x.version })) });
        toast(`${t('تم الحذف')}: ${r.count}`, 'ok'); await load();
      } : null,
      emptyText: t('لا توجد امتحانات لهذا الفصل بعد'),
    });
    table.setQuery(query);
    swap(host, table.el);
  }

  // ------------------------------------------------------------------ the form
  function roomsEditor(initial, current) {
    const rows = (initial && initial.length ? initial : [{}]).map(r => ({ ...r, extra: { ...(r.extra || {}) } }));
    const box = h('div', { class: 'rooms-editor full' });
    const xr = mod.extra_fields.filter(f => f.level === 'room');
    const busyIds = () => {
      const v = current();
      const others = sessions.filter(s => s.id !== v.id && overlaps(s, v));
      return new Set(others.flatMap(s => (s.rooms || []).flatMap(r => r.teacher_ids || [])));
    };
    function draw() {
      const busy = busyIds();
      const opts = teacherOpts().map(o => ({ ...o, label: busy.has(o.value) ? `${o.label} — ${t('مراقب في امتحان آخر في الوقت نفسه')}` : o.label }));
      box.replaceChildren(h('h3', {}, `${label(mod, 'room_id')} / ${label(mod, 'location')} / ${label(mod, 'teacher_ids')}`),
        ...rows.map((r, i) => {
          const secPick = multiPicker({ name: `sec${i}`, label: label(mod, 'section_ids'),
            options: [...sections].map(s => ({ value: s.id, label: sectionLabel(s.id) })) }, r.section_ids, `rsec-${i}`);
          const tPick = multiPicker({ name: `inv${i}`, label: label(mod, 'teacher_ids'), options: opts }, r.teacher_ids, `rinv-${i}`);
          r._read = () => {
            r.section_ids = [...secPick.querySelectorAll('.multi-opts input:checked')].map(x => x.value);
            r.teacher_ids = [...tPick.querySelectorAll('.multi-opts input:checked')].map(x => x.value);
          };
          const extraInputs = xr.map(f => {
            const id = `rx-${i}-${f.key}`;
            const v = r.extra[f.key];
            const lab = f.parent ? `${label(mod, f.parent)} › ${extraLabel(f)}` : extraLabel(f);
            if (f.type === 'teachers') {
              const p = multiPicker({ name: id, label: lab, options: teacherOpts() }, v, id);
              const prev = r._read;
              r._read = () => { prev(); r.extra[f.key] = [...p.querySelectorAll('.multi-opts input:checked')].map(x => x.value); };
              return h('div', { class: 'field full sub' }, h('label', {}, lab), p);
            }
            const type = { number: 'number', date: 'date', time: 'time', bool: 'checkbox' }[f.type] || 'text';
            const inp = h('input', { id, type, value: type === 'checkbox' ? null : (v ?? ''), checked: type === 'checkbox' && !!v,
              placeholder: f.placeholder || null, 'aria-label': lab, list: f.type === 'select' ? `${id}-l` : null,
              oninput: e => { r.extra[f.key] = type === 'checkbox' ? e.target.checked : (type === 'number' ? (e.target.value === '' ? null : Number(e.target.value)) : e.target.value); },
              onchange: e => { if (type === 'checkbox') r.extra[f.key] = e.target.checked; } });
            return h('div', { class: `field${f.parent ? ' sub' : ''}` }, h('label', { for: id }, lab), inp,
              f.type === 'select' ? h('datalist', { id: `${id}-l` }, f.options.map(o => h('option', { value: o }))) : null);
          });
          return h('fieldset', { class: 'room-block' },
            h('legend', {}, `${t('القاعة')} ${i + 1}`),
            h('div', { class: 'form-grid' },
              h('div', { class: 'field' }, h('label', { for: `rr-${i}` }, label(mod, 'room_id')),
                h('select', { id: `rr-${i}`, 'aria-label': label(mod, 'room_id'), onchange: e => { r.room_id = e.target.value || null; } },
                  h('option', { value: '' }, '—'), rooms.map(x => h('option', { value: x.id, selected: x.id === r.room_id }, nameOf(x))))),
              h('div', { class: 'field' }, h('label', { for: `rl-${i}` }, label(mod, 'location')),
                h('input', { id: `rl-${i}`, value: r.location || '', list: `rl-${i}-l`, placeholder: t('اختر من القائمة أو اكتب قيمة جديدة'),
                             'aria-label': label(mod, 'location'), oninput: e => { r.location = e.target.value; } }),
                h('datalist', { id: `rl-${i}-l` }, (mod.lists.locations || []).map(o => h('option', { value: o })))),
              extraInputs.filter((_, k) => xr[k].parent === 'room_id' || xr[k].parent === 'location'),
              h('div', { class: 'field full' }, h('label', {}, label(mod, 'section_ids')), secPick),
              extraInputs.filter((_, k) => xr[k].parent === 'section_ids'),
              h('div', { class: 'field full' }, h('label', {}, label(mod, 'teacher_ids')), tPick),
              extraInputs.filter((_, k) => !['room_id', 'location', 'section_ids'].includes(xr[k].parent))),
            rows.length > 1 ? h('button', { type: 'button', class: 'btn small ghost', onclick: () => { rows.forEach(x => x._read && x._read()); rows.splice(i, 1); draw(); } }, t('حذف القاعة')) : null);
        }),
        h('div', { class: 'toolbar' },
          h('button', { type: 'button', class: 'btn small ghost', onclick: () => { rows.forEach(x => x._read && x._read()); rows.push({ extra: {} }); draw(); } }, `+ ${t('إضافة قاعة')}`),
          h('button', { type: 'button', class: 'btn small ghost', onclick: () => { rows.forEach(x => x._read && x._read()); draw(); } }, t('تحديث المراقبين المتاحين'))));
    }
    draw();
    return { el: box, value: () => { rows.forEach(x => x._read && x._read());
      return rows.map(r => ({ room_id: r.room_id || null, location: r.location || null, section_ids: r.section_ids || [],
                              teacher_ids: r.teacher_ids || [], extra: Object.fromEntries(Object.entries(r.extra || {}).filter(([, v]) => v !== '' && v != null)) }))
        .filter(r => r.room_id || r.location || r.teacher_ids.length || r.section_ids.length); } };
  }

  function formFields() {
    const base = [
      { name: 'exam_date', label: label(mod, 'exam_date'), type: 'date', required: true },
      { name: 'session_label', label: label(mod, 'session_label'), type: 'list', options: mod.lists.session_labels },
      { name: 'starts_at', label: label(mod, 'starts_at'), type: 'time' },
      { name: 'ends_at', label: label(mod, 'ends_at'), type: 'time' },
      { name: 'stage_id', label: label(mod, 'stage_id'), type: 'select', options: stages.map(s => ({ value: s.id, label: nameOf(s) })) },
      { name: 'subject_id', label: label(mod, 'subject_id'), type: 'select', options: subjects.map(s => ({ value: s.id, label: nameOf(s) })) },
      { name: 'title', label: label(mod, 'title'), placeholder: t('مثال: الامتحان الشهري الأول') },
      { name: 'grade_ids', label: label(mod, 'grade_ids'), type: 'multi',
        options: grades.map(g => ({ value: g.id, label: `${nameOf(stage[g.stage_id])} / ${nameOf(g)}` })) },
      { name: 'notes', label: label(mod, 'notes'), type: 'textarea', placeholder: t('ملاحظات تظهر في التقرير') },
    ];
    return placeSubFields(base, extraFields(mod, 'session', teacherOpts()));
  }

  function openExam(values, onSave) {
    const form = document.getElementById('modal-form');
    const current = () => ({ id: values.id, exam_date: form.querySelector('#f-exam_date')?.value, session_label: form.querySelector('#f-session_label')?.value,
                             starts_at: form.querySelector('#f-starts_at')?.value, ends_at: form.querySelector('#f-ends_at')?.value });
    const re = roomsEditor(values.rooms, current);
    return openForm({ title: values.id ? `${t('تعديل الامتحان')}` : t('امتحان جديد'), fields: formFields(),
      values: { ...values, ...extraValues(mod, 'session', values.extra) }, extra: re.el,
      onSubmit: async v => {
        const body = { term_id: termId, exam_date: v.exam_date, session_label: v.session_label, starts_at: v.starts_at,
                       ends_at: v.ends_at, stage_id: v.stage_id, subject_id: v.subject_id, title: v.title,
                       grade_ids: v.grade_ids, notes: v.notes, extra: collectExtra(mod, 'session', v), rooms: re.value() };
        await onSave(body);
        toast(t('تم الحفظ'), 'ok');
        await load();
      } });
  }
  const add = () => openExam({ rooms: [{}], exam_date: sessions.at(-1)?.exam_date }, b => api.post('/api/exam-sessions', b));
  const edit = e => openExam(e, b => api.patch(`/api/exam-sessions/${e.id}`, { ...b, version: e.version }));
  const duplicate = e => openExam({ ...e, id: undefined, rooms: (e.rooms || []).map(r => ({ ...r, teacher_ids: [] })) },
    b => api.post('/api/exam-sessions', b));
  async function remove(e) {
    if (!(await confirmBox(t('أتريد حذف هذا السجل؟')))) return;
    try { await api.del(`/api/exam-sessions/${e.id}`, e.version); toast(t('تم الحذف'), 'ok'); await load(); } catch (err) { toastError(err); }
  }
  const copyFrom = () => openForm({ title: t('نسخ امتحانات فصل آخر إلى هذا الفصل'), fields: [
      { name: 'from', label: t('انسخ من الفصل الدراسي'), type: 'select', required: true,
        options: terms.filter(x => x.id !== termId).map(x => ({ value: x.id, label: nameOf(x) })) },
      { name: 'shift', label: t('تحريك التواريخ بعدد من الأيام'), type: 'number', placeholder: '0', help: t('مثال: 120 لتنقل المواعيد أربعة أشهر تقريباً') }],
    onSubmit: async v => {
      const r = await api.post('/api/exam-sessions/copy', { from_term_id: v.from, to_term_id: termId, shift_days: v.shift || 0 });
      toast(`${t('تم النسخ')}: ${r.copied}`, 'ok'); await load();
    } });

  const report = (kind, fmt) => {
    if (!tt) { toastError(new api.ApiError(0, { message: t('اختر جدولاً من أعلى الصفحة أولاً') })); return; }
    const style = localStorage.getItem('report:style') || 'plain';
    window.open(`/api/timetables/${tt.id}/reports/${kind}?format=${fmt}&lang=${lang}&style=${style}`, '_blank');
  };
  const termSel = h('select', { id: 'exam-term', 'aria-label': t('الفصل الدراسي'), onchange: e => { termId = e.target.value; sessionStorage.setItem('exams:term', termId); load(); } },
    terms.map(x => h('option', { value: x.id, selected: x.id === termId }, nameOf(x))));

  put(root, h('h1', { class: 'title' }, title(mod)),
    h('p', { class: 'muted' }, t('يُبنى جدول الامتحانات لكل فصل دراسي. أضف لكل امتحان قاعاته ومواقعها والمعلمين المراقبين، ويُنبَّه إلى المراقب أو القاعة المحجوزة مرتين في الوقت نفسه.')),
    h('div', { class: 'toolbar sticky' },
      h('label', { class: 'inline' }, `${t('الفصل الدراسي')}:`, termSel),
      canEdit() && termId ? h('button', { class: 'btn', onclick: add }, `+ ${t('امتحان جديد')}`) : null,
      searchBox(v => { query = v; table && table.setQuery(v); }, t('ابحث بالتاريخ أو المبحث أو المعلم…'))),
    h('div', { class: 'toolbar' },
      h('button', { class: 'btn ghost', onclick: () => report('exam-schedule', 'pdf') }, t('طباعة جدول الامتحانات PDF')),
      h('button', { class: 'btn ghost', onclick: () => report('exam-schedule', 'xlsx') }, t('تصدير Excel')),
      h('button', { class: 'btn ghost', onclick: () => report('invigilation', 'pdf') }, t('جدول المراقبة لكل معلم')),
      termId ? h('button', { class: 'btn ghost', id: 'notify-invigilators', onclick: async () => {
        try {
          const r = await api.get(`/api/school-ops/messages?what=exams&term_id=${termId}`);
          await notifyDialog({ title: t('إبلاغ المعلمين المراقبين'), messages: r.messages, canSend: canEdit(),
                               send: body => api.post('/api/exam-sessions/notify', { term_id: termId, ...body }) });
        } catch (e) { toastError(e); }
      } }, t('إبلاغ المراقبين')) : null,
      canEdit() && terms.length > 1 ? h('button', { class: 'btn ghost', onclick: copyFrom }, t('نسخ من فصل آخر')) : null,
      isAdmin() ? h('button', { class: 'btn ghost', onclick: async () => {
        if (await editModule(mod, { lists: [
          ['session_labels', 'قائمة الجلسات (عنصر في كل سطر)', 'مثل: الجلسة الأولى، الجلسة الثانية'],
          ['locations', 'قائمة المواقع (عنصر في كل سطر، والعنصر الفرعي يبدأ بشرطة -)', 'مثال: المبنى الرئيسي ثم في السطر التالي: - الطابق الأول'],
        ] })) { mod = await loadModule('exams'); swap(root); render(root); }
      } }, t('تخصيص الحقول والقوائم')) : null),
    issuesHost, host);
  await load();
}
