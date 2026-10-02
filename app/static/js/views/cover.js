// Absences and cover (الغياب وحصص الإشغال) for one day: record absences (several teachers at once),
// see every lesson period that lost its teacher, pick a substitute from a ranked list (with the reasons),
// or let the system assign everyone fairly in one go; then print the day's sheet and message the substitutes.
import * as api from '../api.js';
import { lang, t } from '../i18n.js';
import { byId, canEdit, currentTimetable, isAdmin, list } from '../store.js';
import { bulkTable, confirmBox, h, nameOf, openForm, put, searchBox, swap, toast, toastError } from '../ui.js';
import { noTimetable } from './ctx.js';
import { notifyDialog } from './notify.js';
import { collectExtra, editLists, editModule, extraFields, extraValues, label, loadModule, placeSubFields, title } from './modconf.js';

const COVER_LISTS = [
  ['reasons', 'أسباب الغياب', 'مثل: إجازة مرضية، مهمة رسمية، دورة تدريبية', { nested: false, itemLabel: 'سبب' }],
];

const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const addDays = (s, n) => { const d = new Date(`${s}T12:00:00`); d.setDate(d.getDate() + n); return iso(d); };
const KIND_ORDER = ['cover', 'merge', 'cancel', 'none'];

export async function render(root, _rest, params) {
  const tt = currentTimetable();
  if (!tt) return noTimetable(root);
  const [teachers, rooms, weekdays] = await Promise.all([list('teachers'), list('rooms'), list('weekdays')]);
  let mod = await loadModule('cover');
  const teacher = byId(teachers), room = byId(rooms);
  const schoolDows = new Set(weekdays.filter(d => d.is_school_day).map(d => d.iso_dow));
  const tName = id => nameOf(teacher[id]) || '?';
  const teacherOpts = () => [...teachers].sort((a, b) => nameOf(a).localeCompare(nameOf(b), 'ar')).map(x => ({ value: x.id, label: nameOf(x) }));
  let date = (params && params.get('date')) || sessionStorage.getItem('cover:date') || iso(new Date());
  let data = null;
  let qAbs = '', qNeeds = '';
  let absTable = null, needTable = null;
  const editable = canEdit() && tt.status !== 'archived';
  const statsHost = h('div'), absHost = h('div'), needsHost = h('div');
  const cands = new Map();   // need key -> ranked candidates (loaded on demand)

  const kindLabel = k => (data?.kinds?.[k] ? (lang === 'en' ? data.kinds[k].en : data.kinds[k].ar) : k);
  const span = a => (a.period_from == null ? t('اليوم كاملاً') : `${t('من الحصة')} ${a.period_from} ${t('إلى الحصة')} ${a.period_to}`);
  const dates = a => (a.date_from === a.date_to ? a.date_from : `${a.date_from} — ${a.date_to}`);

  async function load() {
    sessionStorage.setItem('cover:date', date);
    dateInput.value = date;
    cands.clear();
    data = await api.get(`/api/timetables/${tt.id}/cover?date=${date}`);
    draw();
  }

  // ------------------------------------------------------------------ drawing
  function draw() {
    const s = data.summary;
    swap(statsHost, !data.weekday
      ? h('p', { class: 'notice warn' }, t('هذا التاريخ ليس يوم دوام'))
      : h('div', { class: 'stats' },
          h('div', { class: 'stat' }, h('b', {}, nameOf(data.weekday)), date),
          h('div', { class: 'stat' }, h('b', {}, s.absent_teachers), t('المعلمون الغائبون')),
          h('div', { class: 'stat' }, h('b', {}, s.needs), t('حصص تحتاج إلى قرار')),
          h('div', { class: `stat${s.open ? ' warn' : ''}` }, h('b', {}, s.open), t('لم تُحسَم بعد')),
          h('div', { class: 'stat' }, h('b', {}, s.covered), t('بمعلم بديل'))));
    drawAbsences();
    drawNeeds();
  }

  function drawAbsences() {
    absTable = bulkTable({
      items: data.absences, text: a => [tName(a.teacher_id), a.reason, a.note].join(' '),
      columns: [
        { label: label(mod, 'teacher_id'), get: a => h('b', {}, tName(a.teacher_id)) },
        { label: t('الحصص'), get: a => span(a) },
        { label: t('المدة'), get: a => h('span', { dir: 'ltr' }, dates(a)) },
        { label: label(mod, 'reason'), get: a => a.reason || '' },
        { label: label(mod, 'note'), get: a => a.note || '' },
      ],
      actions: a => (editable ? [h('button', { class: 'btn small ghost', onclick: () => editAbsence(a) }, t('تعديل')), ' ',
                                 h('button', { class: 'btn small ghost', onclick: () => removeAbsence(a) }, t('حذف'))] : null),
      onBulkDelete: editable ? async items => {
        const r = await api.post('/api/absences/bulk-delete', { items: items.map(x => ({ id: x.id, version: x.version })) });
        toast(`${t('تم الحذف')}: ${r.count}`, 'ok'); await load();
      } : null,
      emptyText: t('لا يوجد غياب مسجّل في هذا اليوم'),
    });
    absTable.setQuery(qAbs);
    swap(absHost, absTable.el);
  }

  function decisionCell(n) {
    const s = n.substitution;
    if (!editable) {
      if (!s) return h('span', { class: 'reasons' }, t('لم يُحدَّد بعد'));
      return s.kind === 'cover' ? h('b', {}, tName(s.substitute_teacher_id)) : kindLabel(s.kind);
    }
    const value = !s ? '' : s.kind === 'cover' ? `t:${s.substitute_teacher_id}` : `k:${s.kind}`;
    const sel = h('select', { class: 'decision', 'aria-label': `${t('القرار')} — ${t('الحصة')} ${n.period_no}`, dataset: { key: n.key } });
    const fill = list => {
      const current = s && s.kind === 'cover' ? s.substitute_teacher_id : null;
      const opts = list || (current ? [{ teacher_id: current, name: tName(current), reasons: [], warnings: [] }] : []);
      if (current && !opts.some(c => c.teacher_id === current)) opts.unshift({ teacher_id: current, name: tName(current), reasons: [], warnings: [] });
      const teacherOptions = opts.map((c, i) => h('option', { value: `t:${c.teacher_id}`, selected: value === `t:${c.teacher_id}` },
        `${list && i === 0 ? '★ ' : ''}${lang === 'en' && c.name_en ? c.name_en : c.name}${c.warnings && c.warnings.length ? ` ⚠ ${c.warnings.join('، ')}` : ''}`));
      const loading = list ? null : h('option', { value: '__load', disabled: true }, t('جارٍ تحميل المعلمين المتاحين…'));
      const otherOptions = KIND_ORDER.filter(k => k !== 'cover').map(k => h('option', { value: `k:${k}`, selected: value === `k:${k}` }, kindLabel(k)));
      swap(sel, h('option', { value: '' }, `— ${t('لم يُحدَّد بعد')} —`),
        h('optgroup', { label: t('معلم بديل (الأنسب أولاً)') }, teacherOptions, loading),
        h('optgroup', { label: t('إجراء آخر') }, otherOptions));
    };
    fill(cands.get(n.key));
    const ensure = async () => {
      if (cands.has(n.key)) return;
      try {
        const r = await api.get(`/api/timetables/${tt.id}/cover/candidates?date=${date}&key=${encodeURIComponent(n.key)}`);
        cands.set(n.key, r.candidates);
        const keep = sel.value;
        fill(r.candidates);
        sel.value = keep;
      } catch (e) { toastError(e); }
    };
    sel.addEventListener('focus', ensure);
    sel.addEventListener('pointerdown', ensure);
    sel.addEventListener('change', () => decide(n, sel.value));
    return sel;
  }

  function drawNeeds() {
    needTable = bulkTable({
      items: data.needs.map(n => ({ ...n, id: n.key })),
      text: n => [n.period_no, n.sections, n.subject, tName(n.teacher_id), n.substitution ? tName(n.substitution.substitute_teacher_id) : ''].join(' '),
      rowClass: n => (n.stale ? 'stale' : !n.substitution ? 'open' : ''),
      columns: [
        { label: t('الحصة'), get: n => h('span', {}, h('b', {}, n.period_no), n.starts_at ? h('div', { class: 'muted small', dir: 'ltr' }, `${n.starts_at}–${n.ends_at}`) : null) },
        { label: t('الشعبة'), get: n => n.sections },
        { label: t('المبحث'), get: n => n.subject },
        { label: t('المعلم الغائب'), get: n => [h('span', {}, tName(n.teacher_id)), n.reason ? h('div', { class: 'muted small' }, n.reason) : null,
          n.co_present.length ? h('div', { class: 'muted small' }, `${t('المعلم المشارك حاضر')}: ${n.co_present.map(tName).join('، ')}`) : null] },
        { label: t('القرار'), get: n => (n.stale ? h('span', { class: 'reasons' }, t('لم يعد الغياب يشمل هذه الحصة')) : decisionCell(n)) },
        { label: t('الحالة'), get: n => [
          n.substitution?.auto ? h('span', { class: 'chip' }, t('تلقائي')) : null,
          n.substitution?.notified_at ? h('span', { class: 'chip ok' }, t('أُبلغ')) : null,
          n.substitution?.note ? h('div', { class: 'muted small' }, n.substitution.note) : null,
          (n.substitution?.room_id && n.substitution.room_id !== n.room_id) ? h('div', { class: 'muted small' }, `${t('القاعة')}: ${nameOf(room[n.substitution.room_id])}`) : null] },
      ],
      actions: n => (editable ? [
        n.stale ? null : h('button', { class: 'btn small ghost', onclick: () => suggest(n) }, t('الاقتراحات')), ' ',
        n.substitution && !n.stale ? h('button', { class: 'btn small ghost', onclick: () => details(n) }, t('تفاصيل')) : null, ' ',
        n.substitution ? h('button', { class: 'btn small ghost', onclick: () => clearOne(n) }, t('إلغاء القرار')) : null] : null),
      bulkActions: editable ? [
        { label: t('توزيع تلقائي للمحدد'), run: items => auto(items.filter(n => !n.substitution).map(n => n.key)) },
        { label: t('إلغاء الحصص المحددة'), run: items => setKind(items, 'cancel') },
        { label: t('لا تحتاج إلى بديل'), run: items => setKind(items, 'none') },
      ] : [],
      onBulkDelete: editable ? async items => {
        const ids = items.filter(n => n.substitution).map(n => n.substitution.id);
        if (ids.length) await api.post(`/api/timetables/${tt.id}/cover/clear`, { date, ids });
        toast(t('أُلغيت القرارات المحددة'), 'ok'); await load();
      } : null,
      deleteLabel: t('إلغاء القرارات المحددة'),
      emptyText: data.absences.length ? t('لا توجد حصص للغائبين في هذا اليوم') : t('سجِّل غياب معلم لتظهر حصصه هنا'),
    });
    needTable.setQuery(qNeeds);
    swap(needsHost, needTable.el);
  }

  // ------------------------------------------------------------------ actions
  async function save(n, body) {
    const s = n.substitution;
    if (s) return api.patch(`/api/substitutions/${s.id}`, { ...body, version: s.version });
    const [cardId, period, orig] = n.key.split(':');
    return api.post('/api/substitutions', { timetable_id: tt.id, date, card_id: cardId, period_no: Number(period),
                                            original_teacher_id: orig, ...body });
  }
  async function decide(n, value) {
    try {
      if (!value) { if (n.substitution) await api.post(`/api/timetables/${tt.id}/cover/clear`, { date, ids: [n.substitution.id] }); }
      else if (value.startsWith('t:')) await save(n, { kind: 'cover', substitute_teacher_id: value.slice(2) });
      else await save(n, { kind: value.slice(2), substitute_teacher_id: null });
      toast(t('تم الحفظ'), 'ok');
    } catch (e) { toastError(e); }
    await load();
  }
  async function setKind(items, kind) {
    let n = 0;
    for (const x of items) { if (x.stale) continue; await save(x, { kind, substitute_teacher_id: null }); n++; }
    toast(`${t('تم الحفظ')}: ${n}`, 'ok'); await load();
  }
  async function clearOne(n) {
    try { await api.post(`/api/timetables/${tt.id}/cover/clear`, { date, ids: [n.substitution.id] }); toast(t('أُلغي القرار'), 'ok'); }
    catch (e) { toastError(e); }
    await load();
  }
  async function auto(keys) {
    try {
      const r = await api.post(`/api/timetables/${tt.id}/cover/auto`, { date, keys: keys || [] });
      toast(r.unassigned.length ? `${t('وُزِّعت')}: ${r.created} — ${t('بقيت بلا بديل متاح')}: ${r.unassigned.length}` : `${t('وُزِّعت')}: ${r.created}`,
            r.unassigned.length ? 'err' : 'ok');
    } catch (e) { toastError(e); }
    await load();
  }

  async function suggest(n) {
    let list_ = cands.get(n.key);
    if (!list_) {
      try { list_ = (await api.get(`/api/timetables/${tt.id}/cover/candidates?date=${date}&key=${encodeURIComponent(n.key)}`)).candidates; cands.set(n.key, list_); }
      catch (e) { toastError(e); return; }
    }
    const dlg = document.getElementById('modal');
    const form = document.getElementById('modal-form');
    form.innerHTML = '';
    put(form, h('h2', {}, `${t('المعلمون المتاحون')} — ${t('الحصة')} ${n.period_no}: ${n.subject} (${n.sections})`),
      h('p', { class: 'muted small' }, t('الترتيب حسب: الحضور في المدرسة ذلك اليوم، وتدريس المبحث أو الشعبة نفسها، والمرحلة، وقلة الحصص في اليوم، وعدالة توزيع الإشغال خلال الأسبوع والفصل.')),
      list_.length ? h('div', { class: 'grid-scroll' }, h('table', { class: 'data cand-table' },
        h('thead', {}, h('tr', {}, [t('المعلم'), t('النقاط'), t('لماذا'), t('تنبيهات'), t('حصصه اليوم'), t('إشغال هذا الأسبوع'), t('إشغال الفصل'), ''].map(x => h('th', {}, x)))),
        h('tbody', {}, list_.slice(0, 25).map((c, i) => h('tr', { class: i === 0 ? 'best' : null },
          h('td', {}, h('b', {}, lang === 'en' && c.name_en ? c.name_en : c.name)), h('td', { class: 'num' }, c.score),
          h('td', { class: 'small' }, c.reasons.join('، ')), h('td', { class: 'small reasons' }, c.warnings.join('، ')),
          h('td', { class: 'num' }, c.periods_today), h('td', { class: 'num' }, c.covers_week), h('td', { class: 'num' }, c.covers_term),
          h('td', {}, h('button', { type: 'button', class: 'btn small', onclick: async () => { dlg.close(); await decide(n, `t:${c.teacher_id}`); } }, t('اختيار'))))))))
        : h('p', { class: 'reasons' }, t('لا يوجد معلم متاح في هذه الحصة. اختر الدمج أو الإلغاء.')),
      h('div', { class: 'modal-actions' }, h('button', { class: 'btn ghost', type: 'button', onclick: () => dlg.close() }, t('إغلاق'))));
    dlg.onclose = null;
    dlg.showModal();
  }

  async function details(n) {
    const s = n.substitution;
    const list_ = cands.get(n.key) || (await api.get(`/api/timetables/${tt.id}/cover/candidates?date=${date}&key=${encodeURIComponent(n.key)}`).catch(() => ({ candidates: [] }))).candidates;
    const opts = list_.map(c => ({ value: c.teacher_id, label: c.name }));
    if (s.substitute_teacher_id && !opts.some(o => o.value === s.substitute_teacher_id)) opts.unshift({ value: s.substitute_teacher_id, label: tName(s.substitute_teacher_id) });
    await openForm({ title: `${t('تفاصيل القرار')} — ${t('الحصة')} ${n.period_no}: ${n.subject}`, values: s, fields: [
      { name: 'kind', label: t('الإجراء'), type: 'select', required: true, options: KIND_ORDER.map(k => ({ value: k, label: kindLabel(k) })) },
      { name: 'substitute_teacher_id', label: t('المعلم البديل (أو معلم الشعبة المدموجة)'), type: 'select', options: opts },
      { name: 'room_id', label: t('القاعة (إن تغيّرت)'), type: 'select', options: rooms.map(r => ({ value: r.id, label: nameOf(r) })) },
      { name: 'note', label: t('ملاحظات'), type: 'textarea', placeholder: t('مثال: تُعطى ورقة عمل من معلم المبحث') }],
      onSubmit: async v => { await save(n, v); toast(t('تم الحفظ'), 'ok'); await load(); } });
  }

  // ------------------------------------------------------------------ absences
  function absenceFields(creating) {
    const base = [
      creating ? { name: 'teacher_ids', label: `${label(mod, 'teacher_id')} (${t('يمكن اختيار أكثر من معلم')})`, type: 'multi', options: teacherOpts() }
               : { name: 'teacher_id', label: label(mod, 'teacher_id'), type: 'select', required: true, options: teacherOpts() },
      { name: 'date_from', label: label(mod, 'date_from'), type: 'date', required: true },
      { name: 'date_to', label: label(mod, 'date_to'), type: 'date', required: true },
      { name: 'whole_day', label: t('اليوم كاملاً'), type: 'bool' },
      { name: 'period_from', label: label(mod, 'period_from'), type: 'number', min: 1, placeholder: '1', help: t('لغياب جزئي: أزل علامة «اليوم كاملاً»') },
      { name: 'period_to', label: label(mod, 'period_to'), type: 'number', min: 1, placeholder: '3' },
      { name: 'reason', label: label(mod, 'reason'), type: 'list', options: mod.lists.reasons },
      { name: 'note', label: label(mod, 'note'), type: 'textarea', placeholder: t('ملاحظات تظهر في التقرير') },
    ];
    return placeSubFields(base, extraFields(mod, 'session', teacherOpts()));
  }
  const absenceBody = v => ({ date_from: v.date_from, date_to: v.date_to,
    period_from: v.whole_day ? null : v.period_from, period_to: v.whole_day ? null : v.period_to,
    reason: v.reason, note: v.note, extra: collectExtra(mod, 'session', v) });
  const addAbsence = () => openForm({ title: t('تسجيل غياب'), fields: absenceFields(true),
    values: { date_from: date, date_to: date, whole_day: true },
    onSubmit: async v => {
      if (!v.teacher_ids.length) throw new api.ApiError(400, { message: t('اختر معلماً واحداً على الأقل'), message_en: 'Choose at least one teacher' });
      for (const id of v.teacher_ids) await api.post('/api/absences', { ...absenceBody(v), teacher_id: id });
      toast(`${t('تم الحفظ')}: ${v.teacher_ids.length}`, 'ok');
      await load();
    } });
  const editAbsence = a => openForm({ title: t('تعديل الغياب'), fields: absenceFields(false),
    values: { ...a, whole_day: a.period_from == null, ...extraValues(mod, 'session', a.extra) },
    onSubmit: async v => {
      await api.patch(`/api/absences/${a.id}`, { ...absenceBody(v), teacher_id: v.teacher_id, version: a.version });
      toast(t('تم الحفظ'), 'ok'); await load();
    } });
  async function removeAbsence(a) {
    if (!(await confirmBox(t('أتريد حذف هذا الغياب؟ وتُلغى معه قرارات الإشغال الخاصة بحصصه.')))) return;
    try { await api.del(`/api/absences/${a.id}`, a.version); toast(t('تم الحذف'), 'ok'); await load(); } catch (e) { toastError(e); }
  }

  // ------------------------------------------------------------------ messages
  async function messages() {
    let r;
    try { r = await api.get(`/api/timetables/${tt.id}/cover/messages?date=${date}`); } catch (e) { toastError(e); return; }
    await notifyDialog({ title: `${t('رسائل المعلمين البدلاء')} — \u2066${date}\u2069`, messages: r.messages, canSend: editable,
      send: async body => { const res = await api.post(`/api/timetables/${tt.id}/cover/notify`, { date, ...body }); load(); return res; } });
  }

  const report = (kind, fmt, extra = '') => {
    const style = localStorage.getItem('report:style') || 'plain';
    const sig = localStorage.getItem('report:signature');
    window.open(`/api/timetables/${tt.id}/reports/${kind}?format=${fmt}&lang=${lang}&style=${style}&date=${date}${extra}${sig ? `&signature=${encodeURIComponent(sig)}` : ''}`, '_blank');
  };

  // ------------------------------------------------------------------ page
  const dateInput = h('input', { type: 'date', id: 'cover-date', value: date, 'aria-label': t('التاريخ'),
                                 onchange: e => { if (e.target.value) { date = e.target.value; load(); } } });
  const step = n => { let d = addDays(date, n); for (let i = 0; i < 7 && !schoolDows.has(((new Date(`${d}T12:00:00`).getDay() + 6) % 7) + 1); i++) d = addDays(d, n); date = d; load(); };
  put(root, h('h1', { class: 'title' }, `${title(mod)} — ${tt.name}`),
    h('p', { class: 'muted' }, t('سجِّل غياب المعلمين، فتظهر حصصهم في ذلك اليوم. اختر لكل حصة معلماً بديلاً من قائمة مرتبة حسب الأنسب، أو اترك النظام يوزّعها بعدالة دفعة واحدة، ثم اطبع ورقة اليوم وأبلغ البدلاء.')),
    h('div', { class: 'toolbar sticky' },
      h('button', { class: 'btn ghost', type: 'button', 'aria-label': t('يوم الدوام السابق'), title: t('يوم الدوام السابق'), onclick: () => step(-1) }, lang === 'en' ? '‹' : '›'),
      dateInput,
      h('button', { class: 'btn ghost', type: 'button', 'aria-label': t('يوم الدوام التالي'), title: t('يوم الدوام التالي'), onclick: () => step(1) }, lang === 'en' ? '›' : '‹'),
      h('button', { class: 'btn ghost', type: 'button', onclick: () => { date = iso(new Date()); load(); } }, t('اليوم')),
      editable ? h('button', { class: 'btn', id: 'add-absence', onclick: addAbsence }, `+ ${t('تسجيل غياب')}`) : null,
      searchBox(v => { qAbs = v; qNeeds = v; absTable && absTable.setQuery(v); needTable && needTable.setQuery(v); }, t('ابحث بالمعلم أو الشعبة أو المبحث…'))),
    h('div', { class: 'toolbar' },
      editable ? h('button', { class: 'btn', id: 'cover-auto', onclick: () => auto(null) }, t('توزيع تلقائي عادل للحصص المفتوحة')) : null,
      editable ? h('button', { class: 'btn ghost', onclick: async () => {
        if (!(await confirmBox(t('أتريد إلغاء القرارات التلقائية لهذا اليوم؟')))) return;
        try { const r = await api.post(`/api/timetables/${tt.id}/cover/clear`, { date, only_auto: true }); toast(`${t('أُلغيت')}: ${r.deleted}`, 'ok'); } catch (e) { toastError(e); }
        await load();
      } }, t('إلغاء التوزيع التلقائي')) : null,
      h('button', { class: 'btn ghost', onclick: messages }, t('رسائل البدلاء')),
      h('button', { class: 'btn ghost', onclick: () => report('cover-daily', 'pdf') }, t('طباعة ورقة اليوم PDF')),
      h('button', { class: 'btn ghost', onclick: () => report('cover-daily', 'xlsx') }, t('تصدير Excel')),
      h('button', { class: 'btn ghost', onclick: () => report('free-teachers', 'pdf') }, t('المتاحون في كل حصة')),
      isAdmin() ? h('button', { class: 'btn ghost', id: 'edit-lists', onclick: async () => {
        if (await editLists(mod, COVER_LISTS)) { mod = await loadModule('cover'); swap(root); render(root, _rest, params); }
      } }, t('تعديل قائمة أسباب الغياب')) : null,
      isAdmin() ? h('button', { class: 'btn ghost', onclick: async () => {
        if (await editModule(mod)) { mod = await loadModule('cover'); swap(root); render(root, _rest, params); }
      } }, t('تسميات الحقول والحقول الإضافية')) : null),
    statsHost,
    h('h2', { class: 'section-title' }, t('المعلمون الغائبون')), absHost,
    h('h2', { class: 'section-title' }, t('الحصص التي تحتاج إلى قرار')), needsHost,
    h('p', { class: 'muted small' }, h('a', { href: '#/reports', onclick: () => sessionStorage.setItem('reports', JSON.stringify({ kind: 'cover-stats' })) },
      t('عدد حصص الإشغال والغياب لكل معلم')), ' · ',
    h('a', { href: '#/reports', onclick: () => sessionStorage.setItem('reports', JSON.stringify({ kind: 'absence-log' })) }, t('سجل غياب المعلمين'))));
  await load();
}
