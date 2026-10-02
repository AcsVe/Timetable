// Study plan (الخطة الدراسية): weekly periods of each subject for each grade, entered as a
// subject × grade matrix; then every section of the current timetable is compared with its plan,
// and missing lessons can be created (or a section's own lesson corrected) in one batch.
import * as api from '../api.js';
import { lang, t } from '../i18n.js';
import { canEdit, currentTimetable, invalidate, isAdmin, list } from '../store.js';
import { allOption, bulkTable, h, nameOf, openForm, put, searchBox, swap, toast, toastError, withCount } from '../ui.js';

const STATUSES = [['missing', 'غير موجود'], ['under', 'أقل من الخطة'], ['over', 'أكثر من الخطة'],
                  ['extra', 'ليس في الخطة'], ['ok', 'مطابق للخطة']];
const STATUS_CLS = { missing: 'err', under: 'warn', over: 'warn', extra: 'warn', ok: 'ok' };

export async function render(root) {
  const tt = currentTimetable();
  const [stages, grades, subjectsAll, plan0] = await Promise.all([
    list('stages'), list('grades'), list('subjects'), api.get('/api/curriculum')]);
  const subjects = subjectsAll.filter(s => s.name_ar !== 'اجتماع').sort((a, b) => nameOf(a).localeCompare(nameOf(b), 'ar'));
  const sortedStages = [...stages].sort((a, b) => (a.sort_order - b.sort_order) || nameOf(a).localeCompare(nameOf(b), 'ar'));
  const gradesOf = sid => grades.filter(g => !sid || g.stage_id === sid)
    .sort((a, b) => (sortedStages.findIndex(s => s.id === a.stage_id) - sortedStages.findIndex(s => s.id === b.stage_id))
      || (a.sort_order - b.sort_order) || nameOf(a).localeCompare(nameOf(b), 'ar'));
  let stageId = sessionStorage.getItem('curriculum:stage') || sortedStages[0]?.id || '';
  let mode = 'periods';          // or 'duration'
  let subjQuery = '';
  let onlyUsed = false;
  // working copy: "grade:subject" -> {periods, duration}; saved copy to know what changed
  const key = (g, s) => `${g}:${s}`;
  let saved = {};
  let work = {};
  const loadPlan = items => {
    saved = {};
    for (const it of items) saved[key(it.grade_id, it.subject_id)] = { periods: it.periods_per_week, duration: it.duration };
    work = JSON.parse(JSON.stringify(saved));
  };
  loadPlan(plan0.items);
  const changed = () => {
    const keys = new Set([...Object.keys(saved), ...Object.keys(work)]);
    return [...keys].filter(k => (saved[k]?.periods || 0) !== (work[k]?.periods || 0)
                                 || (work[k]?.periods && (saved[k]?.duration || 1) !== (work[k]?.duration || 1)));
  };

  const matrixHost = h('div');
  const saveBtn = h('button', { class: 'btn', id: 'plan-save', onclick: savePlan }, t('حفظ الخطة'));
  const checkHost = h('div');
  const statsHost = h('div');
  const capacity = {};    // grade -> periods in its week (from the check)

  const totalCells = {};
  const total = g => subjects.reduce((a, s) => a + (work[key(g.id, s.id)]?.periods || 0), 0);
  // light refresh after typing in a cell: save button and totals only (redrawing would steal the focus)
  function refresh() {
    const n = changed().length;
    saveBtn.textContent = n ? `${t('حفظ الخطة')} (${n})` : t('حفظ الخطة');
    saveBtn.disabled = !n;
    for (const g of gradesOf(stageId)) {
      const el = totalCells[g.id];
      if (!el) continue;
      el.textContent = total(g);
      const cap = capacity[g.id];
      el.classList.toggle('reasons', !!cap && total(g) > cap);
      el.title = cap && total(g) > cap ? t('الخطة أكبر من أسبوع الصف') : '';
    }
  }
  const isDirty = k => (saved[k]?.periods || 0) !== (work[k]?.periods || 0)
    || (!!work[k]?.periods && (saved[k]?.duration || 1) !== (work[k]?.duration || 1));

  function drawMatrix() {
    const gs = gradesOf(stageId);
    const editable = canEdit();
    const rows = subjects.filter(s => (!subjQuery || nameOf(s).includes(subjQuery))
      && (!onlyUsed || gs.some(g => work[key(g.id, s.id)]?.periods)));
    if (!gs.length) { swap(matrixHost, h('p', { class: 'muted' }, t('لا توجد صفوف في هذه المرحلة'))); return; }
    const cell = (g, s) => {
      const k = key(g.id, s.id);
      const v = work[k] || {};
      const dirty = isDirty(k);
      if (mode === 'duration') {
        return h('td', { class: `plan-cell${dirty ? ' dirty' : ''}` }, v.periods
          ? h('select', { 'aria-label': `${nameOf(s)} — ${nameOf(g)}`, disabled: !editable,
                          onchange: e => { work[k] = { ...v, duration: Number(e.target.value) };
                                           e.target.closest('td').classList.toggle('dirty', isDirty(k)); refresh(); } },
            [1, 2, 3].map(d => h('option', { value: d, selected: (v.duration || 1) === d }, d === 1 ? t('مفردة') : d === 2 ? t('مزدوجة') : `${d}`)))
          : h('span', { class: 'muted' }, '—'));
      }
      return h('td', { class: `plan-cell${dirty ? ' dirty' : ''}` }, h('input', {
        type: 'number', min: 0, max: 40, inputmode: 'numeric', value: v.periods || '', placeholder: '—', disabled: !editable,
        'aria-label': `${nameOf(s)} — ${nameOf(g)}`,
        onchange: e => {
          const p = Math.max(0, Math.min(40, Number(e.target.value) || 0));
          if (p) work[k] = { periods: p, duration: work[k]?.duration || 1 }; else delete work[k];
          e.target.closest('td').classList.toggle('dirty', isDirty(k));
          refresh();
        },
      }), v.duration > 1 ? h('span', { class: 'muted small', title: t('حصص مزدوجة') }, ` ×${v.duration}`) : null);
    };
    swap(matrixHost, h('div', { class: 'grid-scroll' }, h('table', { class: 'data plan-matrix' },
      h('thead', {}, h('tr', {}, h('th', {}, t('المبحث')), gs.map(g => h('th', { class: 'num' }, nameOf(g))))),
      h('tbody', {}, rows.map(s => h('tr', {}, h('th', { scope: 'row' }, nameOf(s)), gs.map(g => cell(g, s))))),
      h('tfoot', {},
        h('tr', {}, h('th', {}, t('المجموع')), gs.map(g => { totalCells[g.id] = h('b', {}, total(g)); return h('td', { class: 'num' }, totalCells[g.id]); })),
        Object.keys(capacity).length ? h('tr', {}, h('th', {}, t('حصص الأسبوع في التوقيت')),
          gs.map(g => h('td', { class: 'num' }, capacity[g.id] ?? '—'))) : null))));
    refresh();
  }

  async function savePlan() {
    const keys = changed();
    if (!keys.length) return;
    const items = keys.map(k => { const [g, s] = k.split(':'); const v = work[k]; return { grade_id: g, subject_id: s, periods_per_week: v?.periods || 0, duration: v?.duration || 1 }; });
    try {
      const r = await api.put('/api/curriculum/bulk', { items });
      toast(`${t('تم الحفظ')}: ${r.saved}${r.removed ? ` — ${t('حُذف')}: ${r.removed}` : ''}`, 'ok');
      loadPlan((await api.get('/api/curriculum')).items);
      drawMatrix();
      await loadCheck();
    } catch (e) { toastError(e); }
  }

  function copyPlan() {
    const opts = gradesOf('').map(g => ({ value: g.id, label: `${nameOf(g)} (${subjects.filter(s => work[key(g.id, s.id)]?.periods).length})` }));
    openForm({ title: t('نسخ خطة صف إلى صفوف أخرى'), fields: [
      { name: 'from', label: t('من الصف'), type: 'select', required: true, options: opts },
      { name: 'to', label: t('إلى الصفوف'), type: 'multi', options: opts },
      { name: 'replace', label: t('استبدال خطة الصفوف المختارة بالكامل (وإلا تُضاف المباحث الناقصة فقط)'), type: 'bool' }],
    onSubmit: async v => {
      if (!v.to.length) throw new Error(t('اختر صفاً واحداً على الأقل'));
      if (changed().length) await savePlan();
      const r = await api.post('/api/curriculum/copy', { from_grade_id: v.from, to_grade_ids: v.to, replace: !!v.replace });
      toast(`${t('نُسخ')}: ${r.copied}`, 'ok');
      loadPlan((await api.get('/api/curriculum')).items);
      drawMatrix();
      await loadCheck();
      return true;
    } });
  }

  // ------------------------------------------------------------------ check against the timetable
  let check = null;
  let statusFilter = sessionStorage.getItem('curriculum:status') ?? 'issues';
  let rowQuery = '';
  let table = null;
  const assign = h('input', { type: 'checkbox', id: 'plan-assign' });

  async function loadCheck() {
    if (!tt) { swap(checkHost, h('p', { class: 'muted' }, t('اختر جدولاً من أعلى الصفحة لمطابقة دروسه مع الخطة'))); return; }
    check = await api.get(`/api/timetables/${tt.id}/curriculum/check`);
    for (const k of Object.keys(capacity)) delete capacity[k];
    const secGrade = Object.fromEntries(check.rows.map(r => [r.section_id, r.grade_id]));
    for (const s of check.sections) if (secGrade[s.section_id]) capacity[secGrade[s.section_id]] = s.capacity;
    drawMatrix();
    drawCheck();
  }

  function drawCheck() {
    const rows = check.rows.filter(r => (!stageId || r.stage_id === stageId));
    const counts = Object.fromEntries(STATUSES.map(([k]) => [k, rows.filter(r => r.status === k).length]));
    const issues = rows.filter(r => r.status !== 'ok').length;
    const noTeacher = rows.filter(r => r.no_teacher).length;
    const btn = (k, label, n) => h('button', { type: 'button', class: `stat stat-btn${statusFilter === k ? ' active' : ''}`,
      'aria-pressed': statusFilter === k ? 'true' : 'false',
      onclick: () => { statusFilter = statusFilter === k ? '' : k; sessionStorage.setItem('curriculum:status', statusFilter); drawCheck(); } },
      h('b', {}, n), t(label));
    swap(statsHost, h('div', { class: 'stats' }, btn('issues', 'تحتاج إلى معالجة', issues),
      STATUSES.map(([k, l]) => btn(k, l, counts[k])), btn('no_teacher', 'بلا معلم', noTeacher)));
    const shown = rows.filter(r => !statusFilter || (statusFilter === 'issues' ? r.status !== 'ok'
      : statusFilter === 'no_teacher' ? r.no_teacher : r.status === statusFilter));
    const editable = canEdit() && tt.status !== 'archived';
    table = bulkTable({
      items: shown,
      text: r => [r.section, r.subject, r.subject_en, r.label].join(' '),
      columns: [
        { label: t('الشعبة'), get: r => r.section },
        { label: t('المبحث'), get: r => (lang === 'en' ? r.subject_en : r.subject) },
        { label: t('الخطة'), cls: 'num', get: r => r.plan || '—' },
        { label: t('الدروس'), cls: 'num', get: r => r.actual || '—' },
        { label: t('الفرق'), cls: 'num', get: r => (r.diff ? h('span', { dir: 'ltr' }, r.diff > 0 ? `+${r.diff}` : `−${-r.diff}`) : '') },
        { label: t('الحالة'), get: r => [h('span', { class: `chip ${STATUS_CLS[r.status]}` }, lang === 'en' ? r.label_en : r.label),
          r.no_teacher ? h('span', { class: 'chip warn' }, t('بلا معلم')) : null,
          r.shared ? h('span', { class: 'chip', title: t('درس مشترك أو مقسّم يُعدَّل يدوياً') }, t('مشترك')) : null] },
      ],
      actions: r => (r.lesson_ids.length || r.status === 'missing' ? h('a', { class: 'btn small ghost', href: '#/lessons',
        onclick: () => sessionStorage.setItem('lessons:filter', JSON.stringify({ section: r.section_id, subject: r.subject_id })) },
        t('الدروس')) : null),
      bulkActions: editable ? [{ label: t('إنشاء الناقص وتصحيح الحصص للمحدد'), run: items => apply(items.map(x => x.id)) }] : [],
      emptyText: check.plan_items ? t('لا توجد مباحث بهذه الحالة') : t('لم تُدخَل خطة دراسية بعد. اكتب عدد حصص كل مبحث لكل صف في الجدول أعلاه، أو استوردها من Excel.'),
    });
    table.setQuery(rowQuery);
    const fixable = rows.filter(r => r.fixable).length;
    swap(checkHost,
      check.no_plan_grades.length ? h('p', { class: 'notice warn' }, `${t('صفوف بلا خطة (لا تُفحص)')}: `,
        check.no_plan_grades.map(g => g.name).join('، ')) : null,
      check.sections.filter(s => s.status === 'over_capacity').map(s => h('p', { class: 'notice warn' },
        `${s.section}: ${t('الخطة')} ${s.plan} ${t('حصة، وأسبوع الشعبة')} ${s.capacity} ${t('فقط')}`)),
      h('div', { class: 'toolbar' },
        searchBox(v => { rowQuery = v; table.setQuery(v); }, t('ابحث بالشعبة أو المبحث…')),
        editable && fixable ? h('button', { class: 'btn', id: 'plan-apply-all', onclick: () => apply(null) },
          `${t('إنشاء كل الناقص وتصحيح الحصص')} (${fixable})`) : null,
        editable ? h('label', { class: 'inline' }, assign, t('إسناد المعلم تلقائياً إذا كان للمبحث في المرحلة معلم واحد')) : null),
      table.el);
  }

  async function apply(keys) {
    try {
      const r = await api.post(`/api/timetables/${tt.id}/curriculum/apply`, { keys, assign_teacher: assign.checked });
      const parts = [`${t('دروس جديدة')}: ${r.created}`, `${t('دروس صُحّحت حصصها')}: ${r.adjusted}`];
      if (r.assigned) parts.push(`${t('أُسند لها معلم')}: ${r.assigned}`);
      if (r.skipped.length) parts.push(`${t('تُركت للتعديل اليدوي')}: ${r.skipped.length}`);
      toast(parts.join(' — '), r.skipped.length ? 'err' : 'ok');
      invalidate('lessons');
      await loadCheck();
    } catch (e) { toastError(e); }
  }

  // ------------------------------------------------------------------ page
  const stageSel = h('select', { id: 'plan-stage', 'aria-label': t('المرحلة'), onchange: e => {
    stageId = e.target.value; sessionStorage.setItem('curriculum:stage', stageId); drawMatrix(); if (check) drawCheck();
  } }, allOption(grades.length, t('جميع المراحل')),
    sortedStages.map(s => h('option', { value: s.id, selected: s.id === stageId }, withCount(nameOf(s), grades.filter(g => g.stage_id === s.id).length))));
  const modeSel = h('select', { 'aria-label': t('ما تعدّله'), onchange: e => { mode = e.target.value; drawMatrix(); } },
    h('option', { value: 'periods' }, t('عدد الحصص أسبوعياً')), h('option', { value: 'duration' }, t('مدة الحصة (مفردة / مزدوجة)')));
  put(root, h('h1', { class: 'title' }, t('الخطة الدراسية')),
    h('p', { class: 'muted' }, t('اكتب عدد حصص كل مبحث أسبوعياً لكل صف. ثم يقارن البرنامج دروس كل شعبة بخطة صفها، وينبّهك إلى المبحث الناقص أو الزائد أو الذي بلا معلم، وينشئ الدروس الناقصة دفعة واحدة.')),
    h('div', { class: 'toolbar sticky' },
      canEdit() ? saveBtn : null,
      h('label', { class: 'inline' }, `${t('المرحلة')}:`, stageSel),
      h('label', { class: 'inline' }, `${t('تعديل')}:`, modeSel),
      searchBox(v => { subjQuery = v; drawMatrix(); }, t('ابحث عن مبحث…')),
      h('label', { class: 'inline' }, h('input', { type: 'checkbox', onchange: e => { onlyUsed = e.target.checked; drawMatrix(); } }), t('المباحث المستخدمة فقط'))),
    h('div', { class: 'toolbar' },
      canEdit() ? h('button', { class: 'btn ghost', onclick: copyPlan }, t('نسخ خطة صف إلى صفوف أخرى')) : null,
      isAdmin() ? h('a', { class: 'btn ghost', href: '#/import' }, t('استيراد الخطة من Excel')) : null),
    matrixHost,
    h('h2', { class: 'section-title' }, tt ? `${t('مطابقة الدروس مع الخطة')} — ${tt.name}` : t('مطابقة الدروس مع الخطة')),
    statsHost, checkHost);
  drawMatrix();
  await loadCheck();
}
