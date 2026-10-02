// Plan builder (منشئ الخطط): for a stage and a term, the periods each grade must receive of each subject
// over the whole term, each month, each week or each day — compared with the timetable (after the
// holidays), the absences and every teacher's load.
import * as api from '../api.js';
import { lang, t } from '../i18n.js';
import { canEdit, currentTimetable, isAdmin, list, state } from '../store.js';
import { allOption, bulkTable, confirmBox, h, nameOf, openForm, put, searchBox, swap, toast, toastError, withCount } from '../ui.js';

const TYPES = [['term', 'فصلية (مجموع الفصل)'], ['month', 'شهرية'], ['week', 'أسبوعية'], ['day', 'يومية']];
const TYPE_SHORT = { term: 'فصلية', month: 'شهرية', week: 'أسبوعية', day: 'يومية' };
const STATUS = { ok: ['مكتمل', 'ok'], under: ['نقص', 'err'], over: ['زيادة', 'warn'], extra: ['ليس في الخطة', 'warn'], none: ['—', ''] };

export async function render(root, rest = []) {
  if (rest[0]) return renderPlan(root, rest[0]);
  const [plans, terms, stages] = await Promise.all([api.get('/api/plans'), list('terms'), list('stages')]);
  const term = Object.fromEntries(terms.map(x => [x.id, x]));
  const stage = Object.fromEntries(stages.map(x => [x.id, x]));
  let query = '';
  const table = bulkTable({
    items: plans.items,
    text: p => [p.name, nameOf(term[p.term_id]), nameOf(stage[p.stage_id]), t(TYPE_SHORT[p.period_type])].join(' '),
    columns: [
      { label: t('الخطة'), get: p => h('a', { href: `#/plans/${p.id}` }, h('b', {}, p.name)) },
      { label: t('الفصل'), get: p => nameOf(term[p.term_id]) },
      { label: t('المرحلة'), get: p => nameOf(stage[p.stage_id]) || t('جميع المراحل') },
      { label: t('نوع الفترة'), get: p => t(TYPE_SHORT[p.period_type]) },
      { label: t('الحالة'), get: p => h('span', { class: `chip ${p.status === 'approved' ? 'ok' : ''}` }, p.status === 'approved' ? t('معتمدة') : t('مسودة')) },
      { label: t('عدد البنود'), cls: 'num', get: p => Object.keys(p.targets || {}).length },
    ],
    actions: p => [h('a', { class: 'btn small ghost', href: `#/plans/${p.id}` }, t('فتح')),
      canEdit() ? h('button', { class: 'btn small ghost', onclick: () => copy(p) }, t('نسخ')) : null],
    onBulkDelete: canEdit() ? async items => {
      const r = await api.post('/api/plans/bulk-delete', { items: items.map(x => ({ id: x.id, version: x.version })) });
      toast(`${t('تم الحذف')}: ${r.count}`, 'ok'); swap(root); await render(root);
    } : null,
    emptyText: t('لا توجد خطط بعد. أنشئ خطة لمرحلة وفصل، واختر نوع الفترة.'),
  });
  const termOpts = terms.map(x => ({ value: x.id, label: `${nameOf(x)}${x.start_date ? ` (${x.start_date} — ${x.end_date || '…'})` : ` — ${t('بلا تواريخ')}`}` }));
  const create = () => openForm({ title: t('خطة جديدة'), fields: [
    { name: 'name', label: t('اسم الخطة'), required: true, placeholder: t('مثال: خطة الفصل الأول — الأساسية') },
    { name: 'term_id', label: t('الفصل الدراسي'), type: 'select', required: true, options: termOpts,
      help: t('يجب أن يكون للفصل تاريخ بداية وتاريخ نهاية') },
    { name: 'stage_id', label: t('المرحلة (اتركها فارغة لجميع المراحل)'), type: 'select', options: stages.map(x => ({ value: x.id, label: nameOf(x) })) },
    { name: 'period_type', label: t('نوع الفترة'), type: 'select', required: true, options: TYPES.map(([v, l]) => ({ value: v, label: t(l) })) },
    { name: 'notes', label: t('ملاحظات'), type: 'textarea' }],
    values: { period_type: 'term', term_id: state.timetables.find(x => x.id === state.ttId)?.term_id },
    onSubmit: async v => {
      const p = await api.post('/api/plans', { ...v, stage_id: v.stage_id || null });
      location.hash = `#/plans/${p.id}`;
      return true;
    } });
  const copy = p => openForm({ title: t('نسخ الخطة'), values: { name: `${p.name} (${t('نسخة')})` },
    fields: [{ name: 'name', label: t('اسم الخطة الجديدة'), required: true }],
    onSubmit: async v => {
      const n = await api.post('/api/plans', { name: v.name, term_id: p.term_id, stage_id: p.stage_id, period_type: p.period_type,
                                               targets: p.targets, notes: p.notes });
      location.hash = `#/plans/${n.id}`;
      return true;
    } });
  put(root, h('h1', { class: 'title' }, t('منشئ الخطط')),
    h('p', { class: 'muted' }, t('خطة لكل مرحلة وفصل: عدد الحصص المطلوب تنفيذها من كل مبحث لكل صف، في الفصل كله أو في كل شهر أو أسبوع أو يوم. ثم يقارنها البرنامج بما يعطيه الجدول بعد خصم العطل، وبما نُفِّذ فعلاً بعد الغياب، وبنصاب كل معلم.')),
    h('div', { class: 'toolbar sticky' },
      canEdit() ? h('button', { class: 'btn', id: 'plan-new', onclick: create }, `+ ${t('خطة جديدة')}`) : null,
      searchBox(v => { query = v; table.setQuery(v); }, t('ابحث في الخطط…')),
      h('a', { class: 'btn ghost', href: '#/setup/holidays' }, t('العطل الرسمية')),
      h('a', { class: 'btn ghost', href: '#/curriculum' }, t('الخطة الدراسية الأسبوعية'))),
    table.el);
  table.setQuery(query);
}

// ---------------------------------------------------------------------------- one plan
async function renderPlan(root, id) {
  let plan = await api.get(`/api/plans/${id}`);
  const [subjectsAll, stages, terms, curriculum] = await Promise.all([list('subjects'), list('stages'), list('terms'), api.get('/api/curriculum')]);
  let meta;
  try { meta = await api.get(`/api/plans/${id}/periods?lang=${lang}`); } catch (e) {
    put(root, h('h1', { class: 'title' }, plan.name), h('p', { class: 'notice warn' }, e.message),
      h('a', { class: 'btn', href: '#/setup/terms' }, t('الفصول الدراسية')));
    return;
  }
  const subjects = subjectsAll.filter(s => s.name_ar !== 'اجتماع').sort((a, b) => nameOf(a).localeCompare(nameOf(b), 'ar'));
  const term = terms.find(x => x.id === plan.term_id);
  const stage = stages.find(x => x.id === plan.stage_id);
  const grades = meta.grades;
  const editable = canEdit();
  let gradeId = sessionStorage.getItem(`plan:${id}:grade`) || grades[0]?.id;
  let month = '';                 // day / week plans: one month at a time keeps the table readable
  let allSubjects = false;
  let tab = sessionStorage.getItem('plan:tab') || 'targets';
  let work = JSON.parse(JSON.stringify(plan.targets || {}));
  const dirty = () => JSON.stringify(work) !== JSON.stringify(plan.targets || {});
  const host = h('div');
  const headHost = h('div');
  const saveBtn = h('button', { class: 'btn', id: 'plan-save', onclick: save }, t('حفظ'));

  const months = [...new Set(meta.periods.map(p => p.start.slice(0, 7)))];
  const shownPeriods = () => (plan.period_type === 'day' || plan.period_type === 'week') && month
    ? meta.periods.filter(p => p.start.slice(0, 7) === month) : meta.periods;

  function drawHead() {
    swap(headHost,
      h('h1', { class: 'title' }, plan.name, ' ', h('span', { class: `chip ${plan.status === 'approved' ? 'ok' : ''}` },
        plan.status === 'approved' ? t('معتمدة') : t('مسودة'))),
      h('p', { class: 'muted' }, [nameOf(term), nameOf(stage) || t('جميع المراحل'), t(TYPE_SHORT[plan.period_type]),
        `${t('أيام الدراسة')}: ${meta.school_days} ${t('من')} ${meta.all_days} (${t('بعد خصم العطل')})`].join(' — ')),
      h('div', { class: 'toolbar' },
        h('a', { class: 'btn ghost', href: '#/plans' }, `→ ${t('كل الخطط')}`),
        h('button', { class: `btn ${tab === 'targets' ? '' : 'ghost'}`, onclick: () => { tab = 'targets'; sessionStorage.setItem('plan:tab', tab); draw(); } }, t('النصاب المطلوب')),
        h('button', { class: `btn ${tab === 'analysis' ? '' : 'ghost'}`, id: 'plan-tab-analysis',
          onclick: () => { tab = 'analysis'; sessionStorage.setItem('plan:tab', tab); draw(); } }, t('المطابقة والتنفيذ')),
        isAdmin() ? h('button', { class: 'btn ghost', id: 'plan-approve', onclick: approve },
          plan.status === 'approved' ? t('إلغاء الاعتماد') : t('اعتماد الخطة')) : null,
        editable ? h('button', { class: 'btn ghost', onclick: rename }, t('تعديل الاسم والملاحظات')) : null));
  }

  // ------------------------------------------------------------------ targets editor
  function drawTargets() {
    const ps = shownPeriods();
    const k = s => `${gradeId}:${s.id}`;
    const inWeekly = new Set(curriculum.items.filter(x => x.grade_id === gradeId).map(x => x.subject_id));
    const rows = subjects.filter(s => allSubjects || inWeekly.has(s.id) || work[k(s)]);
    saveBtn.disabled = !dirty();
    const rowTotal = s => Object.values(work[k(s)] || {}).reduce((a, b) => a + (b || 0), 0);
    const totals = {};
    const totalEls = {};
    const refreshTotals = () => {
      saveBtn.disabled = !dirty();
      for (const p of ps) totalEls[p.key].textContent = rows.reduce((a, s) => a + ((work[k(s)] || {})[p.key] || 0), 0);
      for (const s of rows) totals[s.id].textContent = rowTotal(s);
    };
    const gradeSel = h('select', { 'aria-label': t('الصف'), onchange: e => { gradeId = e.target.value; sessionStorage.setItem(`plan:${id}:grade`, gradeId); draw(); } },
      grades.map(g => h('option', { value: g.id, selected: g.id === gradeId },
        withCount(lang === 'en' && g.name_en ? g.name_en : g.name_ar, Object.keys(work).filter(x => x.startsWith(`${g.id}:`)).length))));
    const monthSel = months.length > 1 && (plan.period_type === 'day' || plan.period_type === 'week')
      ? h('select', { 'aria-label': t('الشهر'), onchange: e => { month = e.target.value; draw(); } },
          allOption(meta.periods.length, t('كل الأشهر')), months.map(m => h('option', { value: m, selected: m === month },
            withCount(m, meta.periods.filter(p => p.start.startsWith(m)).length)))) : null;
    const table = rows.length ? h('div', { class: 'grid-scroll' }, h('table', { class: 'data plan-matrix' },
      h('thead', {}, h('tr', {}, h('th', {}, t('المبحث')),
        ps.map(p => h('th', { class: 'num', title: `${p.start} — ${p.end}` }, p.label, h('div', { class: 'muted small' }, `${p.school_days} ${t('يوم')}`))),
        h('th', { class: 'num' }, t('المجموع')))),
      h('tbody', {}, rows.map(s => {
        totals[s.id] = h('b', {}, rowTotal(s));
        return h('tr', {}, h('th', { scope: 'row' }, nameOf(s)),
          ps.map(p => h('td', { class: 'plan-cell' }, h('input', {
            type: 'number', min: 0, inputmode: 'numeric', value: (work[k(s)] || {})[p.key] || '', placeholder: '—', disabled: !editable || !p.school_days,
            'aria-label': `${nameOf(s)} — ${p.label}`,
            onchange: e => {
              const v = Math.max(0, Number(e.target.value) || 0);
              const row = { ...(work[k(s)] || {}) };
              if (v) row[p.key] = v; else delete row[p.key];
              if (Object.keys(row).length) work[k(s)] = row; else delete work[k(s)];
              e.target.closest('td').classList.toggle('dirty', ((plan.targets[k(s)] || {})[p.key] || 0) !== v);
              refreshTotals();
            } }))),
          h('td', { class: 'num' }, totals[s.id]));
      })),
      h('tfoot', {}, h('tr', {}, h('th', {}, t('المجموع')), ps.map(p => { totalEls[p.key] = h('b'); return h('td', { class: 'num' }, totalEls[p.key]); }), h('td')))))
      : h('p', { class: 'muted' }, t('لا توجد مباحث في الخطة الأسبوعية لهذا الصف. اختر «كل المباحث» أو املأ الخطة الأسبوعية أولاً.'));
    swap(host,
      h('div', { class: 'toolbar sticky' }, editable ? saveBtn : null,
        h('label', { class: 'inline' }, `${t('الصف')}:`, gradeSel), monthSel ? h('label', { class: 'inline' }, `${t('الشهر')}:`, monthSel) : null,
        h('label', { class: 'inline' }, h('input', { type: 'checkbox', checked: allSubjects, onchange: e => { allSubjects = e.target.checked; draw(); } }), t('كل المباحث'))),
      editable ? h('div', { class: 'toolbar' },
        h('button', { class: 'btn ghost', id: 'plan-fill', onclick: () => fill([gradeId]) }, t('تعبئة هذا الصف من الخطة الأسبوعية')),
        h('button', { class: 'btn ghost', onclick: () => fill(null) }, t('تعبئة كل الصفوف من الخطة الأسبوعية')),
        h('span', { class: 'muted small' }, t('الحصص الأسبوعية × أيام الدراسة في الفترة ÷ أيام الأسبوع، بعد خصم العطل'))) : null,
      table);
    if (rows.length) refreshTotals();
  }

  async function save() {
    try {
      plan = await api.patch(`/api/plans/${id}`, { version: plan.version, targets: work });
      work = JSON.parse(JSON.stringify(plan.targets || {}));
      toast(t('تم الحفظ'), 'ok');
      draw();
    } catch (e) { toastError(e); }
  }
  async function fill(gradeIds) {
    if (dirty()) await save();
    const overwrite = Object.keys(work).some(x => !gradeIds || gradeIds.some(g => x.startsWith(`${g}:`)))
      ? await confirmBox(t('في الخطة أرقام مُدخَلة. أتريد استبدالها بالأرقام المحسوبة من الخطة الأسبوعية؟ (اختر «إلغاء» لتعبئة الخانات الفارغة فقط)'))
      : false;
    try {
      const r = await api.post(`/api/plans/${id}/fill-weekly`, { grade_ids: gradeIds, overwrite });
      plan = await api.get(`/api/plans/${id}`);
      work = JSON.parse(JSON.stringify(plan.targets || {}));
      toast(`${t('عُبِّئت')}: ${r.filled}`, 'ok');
      draw();
    } catch (e) { toastError(e); }
  }
  async function approve() {
    if (dirty()) await save();
    try {
      plan = await api.post(`/api/plans/${id}/approve`, { approve: plan.status !== 'approved' });
      toast(plan.status === 'approved' ? t('اعتُمدت الخطة') : t('أُعيدت الخطة إلى مسودة'), 'ok');
      draw();
    } catch (e) { toastError(e); }
  }
  const rename = () => openForm({ title: t('تعديل'), values: plan, fields: [
    { name: 'name', label: t('اسم الخطة'), required: true }, { name: 'notes', label: t('ملاحظات'), type: 'textarea' }],
    onSubmit: async v => { plan = await api.patch(`/api/plans/${id}`, { version: plan.version, name: v.name, notes: v.notes }); draw(); return true; } });

  // ------------------------------------------------------------------ analysis
  let period = '';
  let statusFilter = '';
  let view = 'sections';
  let q = '';
  async function drawAnalysis() {
    const tt = currentTimetable();
    if (!tt) { swap(host, h('p', { class: 'muted' }, t('اختر جدولاً من أعلى الصفحة'))); return; }
    swap(host, h('p', { class: 'muted' }, t('جارٍ الحساب…')));
    let rep;
    try { rep = await api.get(`/api/plans/${id}/analysis?timetable_id=${tt.id}${period ? `&period=${period}` : ''}`); } catch (e) { swap(host, h('p', { class: 'reasons' }, e.message)); return; }
    const periodSel = meta.periods.length > 1 ? h('select', { 'aria-label': t('الفترة'), onchange: e => { period = e.target.value; drawAnalysis(); } },
      allOption(meta.periods.length, t('الفترات كلها')), meta.periods.map(p => h('option', { value: p.key, selected: p.key === period }, p.label))) : null;
    const items = view === 'sections' ? rep.rows : rep.teachers;
    const count = k => items.filter(r => r.status === k).length;
    const stat = (k, label) => h('button', { type: 'button', class: `stat stat-btn${statusFilter === k ? ' active' : ''}`, 'aria-pressed': statusFilter === k ? 'true' : 'false',
      onclick: () => { statusFilter = statusFilter === k ? '' : k; drawAnalysis(); } }, h('b', {}, count(k)), t(label));
    const shown = items.filter(r => !statusFilter || r.status === statusFilter);
    const badge = r => { const [l, c] = STATUS[r.status]; return h('span', { class: `chip ${c}` }, t(l)); };
    const pct = (a, b) => (b ? `${Math.round((a / b) * 100)}%` : '—');
    const tb = view === 'sections' ? bulkTable({
      items: shown, text: r => [r.section, r.subject, r.subject_en].join(' '),
      columns: [
        { label: t('الشعبة'), get: r => r.section },
        { label: t('المبحث'), get: r => (lang === 'en' ? r.subject_en : r.subject) },
        { label: t('المطلوب في الخطة'), cls: 'num', get: r => r.required },
        { label: t('المتاح في الجدول'), cls: 'num', get: r => r.scheduled },
        { label: t('الفرق'), cls: 'num', get: r => (r.diff ? h('span', { dir: 'ltr' }, r.diff > 0 ? `+${r.diff}` : `−${-r.diff}`) : '') },
        { label: t('ضائع بالغياب'), cls: 'num', get: r => (r.lost ? `${r.lost}${r.covered ? ` (${t('إشغال')} ${r.covered})` : ''}` : '') },
        { label: t('المنفَّذ حتى اليوم'), cls: 'num', get: r => `${r.delivered} / ${r.required_due || r.due}` },
        { label: t('نسبة التنفيذ'), cls: 'num', get: r => pct(r.delivered, r.required_due || r.due) },
        { label: t('الحالة'), get: badge },
      ],
      emptyText: t('لا توجد بيانات بهذه الحالة'),
    }) : bulkTable({
      items: shown, text: r => [r.name, r.name_en].join(' '),
      columns: [
        { label: t('المعلم'), get: r => (lang === 'en' ? r.name_en : r.name) },
        { label: t('مطلوب الخطة لدروسه'), cls: 'num', get: r => r.required },
        { label: t('المتاح في الجدول'), cls: 'num', get: r => r.scheduled },
        { label: t('النصاب للفترة'), cls: 'num', get: r => (r.quota ?? '—') },
        { label: t('الفرق عن النصاب'), cls: 'num', get: r => (r.quota != null && r.scheduled !== r.quota ? h('span', { dir: 'ltr' }, r.scheduled > r.quota ? `+${r.scheduled - r.quota}` : `−${r.quota - r.scheduled}`) : '') },
        { label: t('ضائع بالغياب'), cls: 'num', get: r => (r.lost ? `${r.lost}${r.covered ? ` (${t('إشغال')} ${r.covered})` : ''}` : '') },
        { label: t('المنفَّذ حتى اليوم'), cls: 'num', get: r => `${r.delivered} / ${r.due}` },
        { label: t('حالة النصاب'), get: badge },
      ],
      emptyText: t('لا توجد بيانات بهذه الحالة'),
    });
    tb.setQuery(q);
    const report = (kind, fmt) => window.open(`/api/timetables/${tt.id}/reports/${kind}?plan_id=${id}${period ? `&period=${period}` : ''}&format=${fmt}&lang=${lang}`, '_blank');
    const kind = view === 'sections' ? 'plan-sections' : 'plan-teachers';
    swap(host,
      h('div', { class: 'toolbar sticky' },
        h('label', { class: 'inline' }, `${t('العرض')}:`, h('select', { id: 'plan-view', 'aria-label': t('العرض'), onchange: e => { view = e.target.value; statusFilter = ''; drawAnalysis(); } },
          h('option', { value: 'sections', selected: view === 'sections' }, withCount(t('الشعب والمباحث'), rep.rows.length)),
          h('option', { value: 'teachers', selected: view === 'teachers' }, withCount(t('المعلمون والنصاب'), rep.teachers.length)))),
        periodSel ? h('label', { class: 'inline' }, `${t('الفترة')}:`, periodSel) : null,
        searchBox(v => { q = v; tb.setQuery(v); }, view === 'sections' ? t('ابحث بالشعبة أو المبحث…') : t('ابحث عن معلم…'))),
      h('p', { class: 'muted small' }, `${t('الجدول')}: ${tt.name} — ${t('أيام الدراسة')}: ${rep.school_days} (${rep.weeks} ${t('أسبوع')}) — ${t('حتى تاريخ')} ${rep.today}`,
        view === 'teachers' ? ` — ${t('النصاب للفترة = النصاب الأسبوعي × عدد أسابيع الدراسة')}` : ''),
      h('div', { class: 'stats' }, stat('under', 'نقص'), stat('ok', 'مكتمل'), stat('over', 'زيادة'),
        view === 'sections' ? stat('extra', 'ليس في الخطة') : stat('none', 'بلا نصاب محدد')),
      h('div', { class: 'toolbar' },
        h('button', { class: 'btn ghost', onclick: () => report(kind, 'pdf') }, t('طباعة PDF')),
        h('button', { class: 'btn ghost', onclick: () => report(kind, 'xlsx') }, t('تصدير Excel'))),
      tb.el);
  }

  function draw() {
    drawHead();
    if (tab === 'analysis') drawAnalysis(); else drawTargets();
  }
  put(root, headHost, host);
  draw();
}
