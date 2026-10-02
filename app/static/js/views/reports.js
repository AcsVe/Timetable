// Reports: preview on screen, print, or download as Excel / PDF (same data as the preview).
import * as api from '../api.js';
import { lang, t } from '../i18n.js';
import { byId, currentTimetable, list } from '../store.js';
import { h, nameOf, pageNav, put, swap, toastError } from '../ui.js';
import { noTimetable } from './ctx.js';

const ALL = ['stage_id', 'grade_id', 'section_id', 'teacher_id', 'subject_id'];
// [kind, label, filters, group]
const KINDS = [
  ['section-timetable', 'الجدول الأسبوعي للشعبة', ['stage_id', 'grade_id', 'section_id'], 'الجداول'],
  ['teacher-timetable', 'جدول حصص المعلم', ['stage_id', 'teacher_id', 'subject_id'], 'الجداول'],
  ['subject-timetable', 'جدول حصص المبحث', ['stage_id', 'grade_id', 'section_id', 'subject_id', 'teacher_id'], 'الجداول'],
  ['room-timetable', 'جدول إشغال القاعة', ['room_id'], 'الجداول'],
  ['stage-timetable', 'الجدول العام للمرحلة (الشعب)', ['stage_id', 'grade_id', 'section_id', 'subject_id', 'teacher_id'], 'الجداول'],
  ['teachers-master', 'الجدول العام للمعلمين', ['stage_id', 'grade_id', 'section_id', 'subject_id', 'teacher_id'], 'الجداول'],
  ['free-teachers', 'المعلمون المتاحون في كل حصة (لحصص الإشغال)', ['date', 'stage_id', 'subject_id'], 'الجداول'],
  ['teacher-sections', 'توزيع المعلمين على الشعب', ALL, 'التوزيع والإحصائيات'],
  ['teacher-subjects', 'توزيع المعلمين على المباحث', ALL, 'التوزيع والإحصائيات'],
  ['teacher-daily', 'توزيع حصص المعلم على أيام الأسبوع', ALL, 'التوزيع والإحصائيات'],
  ['stats-teachers', 'إحصائيات المعلمين والنصاب', ALL, 'التوزيع والإحصائيات'],
  ['load-status', 'اكتمال النصاب حسب القواعد', ['stage_id', 'teacher_id', 'subject_id'], 'التوزيع والإحصائيات'],
  ['stats-subjects', 'إحصائيات المباحث', ALL, 'التوزيع والإحصائيات'],
  ['stats-sections', 'تغطية الحصص في الشعب', ALL, 'التوزيع والإحصائيات'],
  ['exam-schedule', 'جدول الامتحانات', ['stage_id', 'grade_id', 'subject_id', 'teacher_id', 'room_id'], 'الامتحانات والمناوبة'],
  ['invigilation', 'جدول المراقبة على الامتحانات', ['stage_id', 'grade_id', 'subject_id', 'teacher_id'], 'الامتحانات والمناوبة'],
  ['duty-roster', 'جدول المناوبة', ['stage_id', 'teacher_id'], 'الامتحانات والمناوبة'],
  ['duty-teachers', 'مناوبات كل معلم', ['stage_id', 'teacher_id'], 'الامتحانات والمناوبة'],
  ['cover-daily', 'حصص الإشغال اليومية', ['date', 'stage_id', 'teacher_id'], 'الغياب والإشغال'],
  ['cover-stats', 'حصص الإشغال والغياب لكل معلم', ['date_from', 'date_to', 'stage_id', 'teacher_id'], 'الغياب والإشغال'],
  ['absence-log', 'سجل غياب المعلمين', ['date_from', 'date_to', 'stage_id', 'teacher_id'], 'الغياب والإشغال'],
];
const GRID_KINDS = new Set(['section-timetable', 'teacher-timetable', 'subject-timetable', 'room-timetable', 'free-teachers']);
const MASTER_KINDS = new Set(['stage-timetable', 'teachers-master']);
const MATRIX_KINDS = new Set(['teacher-sections', 'teacher-daily', 'duty-roster']);
// What a timetable cell may show (all on by default).
const SHOW = [['teacher', 'اسم المعلم'], ['section', 'الشعبة'], ['room', 'القاعة'], ['groups', 'المجموعات'],
              ['times', 'أوقات الحصص'], ['footer', 'المجموع والنصاب أسفل الجدول']];
const FILTER_LABELS = { stage_id: 'المرحلة', grade_id: 'الصف', section_id: 'الشعبة', teacher_id: 'المعلم',
                        subject_id: 'المبحث', room_id: 'القاعة', date: 'التاريخ', date_from: 'من تاريخ', date_to: 'إلى تاريخ' };
const DATE_FILTERS = new Set(['date', 'date_from', 'date_to']);

export async function render(root) {
  const tt = currentTimetable();
  if (!tt) return noTimetable(root);
  const [stages, grades, sections, teachers, subjects, rooms] = await Promise.all([
    list('stages'), list('grades'), list('sections'), list('teachers'), list('subjects'), list('rooms')]);
  const gradeById = byId(grades);
  const saved = JSON.parse(sessionStorage.getItem('reports') || '{}');
  let kind = saved.kind || KINDS[0][0];
  let layout = saved.layout || 'rows';
  const filters = saved.filters || {};
  if (!KINDS.some(k => k[0] === kind)) kind = KINDS[0][0];
  let style = localStorage.getItem('report:style') || 'plain';
  let show = new Set(JSON.parse(localStorage.getItem('report:show') || 'null') || SHOW.map(x => x[0]));
  let signature = localStorage.getItem('report:signature') || '';
  const preview = h('div', { class: 'report-preview' });
  const filterHost = h('div', { class: 'toolbar' });

  const options = {
    stage_id: () => stages.map(s => ({ value: s.id, label: nameOf(s) })),
    grade_id: () => grades.filter(g => !filters.stage_id || g.stage_id === filters.stage_id)
      .map(g => ({ value: g.id, label: nameOf(g) })),
    section_id: () => sections.filter(s => {
      const g = gradeById[s.grade_id];
      return (!filters.grade_id || s.grade_id === filters.grade_id) && (!filters.stage_id || g?.stage_id === filters.stage_id);
    }).map(s => ({ value: s.id, label: `${nameOf(gradeById[s.grade_id])} / ${nameOf(s)}` })),
    teacher_id: () => [...teachers].sort((a, b) => nameOf(a).localeCompare(nameOf(b), 'ar')).map(x => ({ value: x.id, label: nameOf(x) })),
    subject_id: () => subjects.map(x => ({ value: x.id, label: nameOf(x) })),
    room_id: () => rooms.map(x => ({ value: x.id, label: nameOf(x) })),
  };
  const allowed = () => KINDS.find(k => k[0] === kind)[2];
  const query = (fmt, exportLang) => {
    const q = new URLSearchParams({ format: fmt, lang: exportLang || lang, layout, style });
    if (GRID_KINDS.has(kind) || MASTER_KINDS.has(kind)) q.set('show', [...show].join(','));
    if (signature.trim()) q.set('signature', signature);
    for (const k of allowed()) if (filters[k]) q.set(k, filters[k]);
    return `/api/timetables/${tt.id}/reports/${kind}?${q}`;
  };
  const persist = () => sessionStorage.setItem('reports', JSON.stringify({ kind, filters, layout }));
  const layoutOptions = () => (GRID_KINDS.has(kind) ? [['rows', t('الأيام صفوفاً')], ['cols', t('الأيام أعمدةً')]]
    : MASTER_KINDS.has(kind) ? [['rows', kind === 'stage-timetable' ? t('الشعب صفوفاً والحصص أعمدةً') : t('المعلمون صفوفاً والحصص أعمدةً')],
                                ['cols', kind === 'stage-timetable' ? t('الشعب أعمدةً والحصص صفوفاً') : t('المعلمون أعمدةً والحصص صفوفاً')]]
      : [['rows', t('الوضع المعتاد')], ['cols', t('تبديل الصفوف والأعمدة')]]);
  const layoutSel = h('select', { id: 'report-layout', 'aria-label': t('اتجاه الجدول'), onchange: e => { layout = e.target.value; persist(); load(); } });
  const layoutLabel = h('label', { class: 'inline' }, `${t('اتجاه الجدول')}:`, layoutSel);
  const showHost = h('fieldset', { class: 'plain no-print' });
  function drawShow() {
    showHost.hidden = !(GRID_KINDS.has(kind) || MASTER_KINDS.has(kind));
    swap(showHost, h('legend', {}, t('محتوى الخانة')), SHOW.map(([k, l]) => h('label', { class: 'inline' },
      h('input', { type: 'checkbox', checked: show.has(k), onchange: e => {
        e.target.checked ? show.add(k) : show.delete(k);
        localStorage.setItem('report:show', JSON.stringify([...show])); load();
      } }), t(l))));
  }
  function drawFilters() {
    const orientable = GRID_KINDS.has(kind) || MASTER_KINDS.has(kind) || MATRIX_KINDS.has(kind);
    layoutLabel.hidden = !orientable;
    swap(layoutSel, layoutOptions().map(([v, l]) => h('option', { value: v, selected: v === layout }, l)));
    drawShow();
    for (const k of Object.keys(filters)) if (!allowed().includes(k)) delete filters[k];
    swap(filterHost, allowed().map(k => DATE_FILTERS.has(k)
      ? h('label', { class: 'inline' }, `${t(FILTER_LABELS[k])}:`, h('input', { type: 'date', value: filters[k] || '', dataset: { filter: k },
          'aria-label': t(FILTER_LABELS[k]), onchange: e => { filters[k] = e.target.value || undefined; persist(); load(); } }))
      : h('label', { class: 'inline' }, `${t(FILTER_LABELS[k])}:`,
      h('select', { dataset: { filter: k }, 'aria-label': t(FILTER_LABELS[k]), onchange: e => {
        filters[k] = e.target.value || undefined;
        if (k === 'stage_id') { delete filters.grade_id; delete filters.section_id; }
        if (k === 'grade_id') delete filters.section_id;
        persist(); drawFilters(); load();
      } }, h('option', { value: '' }, t('الكل')),
        options[k]().map(o => h('option', { value: o.value, selected: o.value === filters[k] }, o.label))))));
  }

  let loadToken = 0;
  async function load() {
    const token = ++loadToken;   // ignore responses that arrive after a newer request
    swap(preview, h('p', { class: 'muted' }, t('جارٍ التحميل…')));
    try {
      const rep = await api.get(query('json'));
      preview.classList.toggle('plain', style !== 'color');
      if (token === loadToken) swap(preview, renderReport(rep));
    } catch (e) { if (token === loadToken) { toastError(e); swap(preview); } }
  }

  const styleSel = h('select', { id: 'report-style', 'aria-label': t('نمط الطباعة'), onchange: e => {
    style = e.target.value; localStorage.setItem('report:style', style); load(); } },
    [['plain', t('أبيض وأسود بلا خلفيات (للطباعة)')], ['color', t('ملوّن')]].map(([v, l]) => h('option', { value: v, selected: v === style }, l)));
  const signInput = h('input', { id: 'report-signature', value: signature, 'aria-label': t('خانات التوقيع'),
    placeholder: t('مثال: مدير المدرسة | المرشد التربوي | الختم'),
    onchange: e => { signature = e.target.value; localStorage.setItem('report:signature', signature); load(); } });
  const exportLang = h('select', { id: 'export-lang', 'aria-label': t('لغة الملف') },
    h('option', { value: 'ar', selected: lang === 'ar' }, 'العربية'), h('option', { value: 'en', selected: lang === 'en' }, 'English'));
  const download = fmt => {
    if (api.isOffline()) { toastError(new api.ApiError(0, { message: t('لا يوجد اتصال، لا يمكن التصدير الآن'), message_en: 'Offline — cannot export now' })); return; }
    const a = h('a', { href: query(fmt, exportLang.value), download: '' });
    document.body.append(a); a.click(); a.remove();
  };

  put(root,
    h('h1', { class: 'title no-print' }, `${t('التقارير')} — ${tt.name}`),
    h('div', { class: 'toolbar sticky no-print' },
      h('label', { class: 'inline' }, `${t('التقرير')}:`, h('select', { id: 'report-kind', 'aria-label': t('التقرير'), onchange: e => { kind = e.target.value; persist(); drawFilters(); load(); } },
        [...new Set(KINDS.map(k => k[3]))].map(g => h('optgroup', { label: t(g) },
          KINDS.filter(k => k[3] === g).map(([v, l]) => h('option', { value: v, selected: v === kind }, t(l))))))), layoutLabel,
      h('label', { class: 'inline' }, `${t('نمط الطباعة')}:`, styleSel)),
    h('div', { class: 'no-print' }, filterHost),
    showHost,
    h('div', { class: 'toolbar no-print' }, h('label', { class: 'inline grow' }, `${t('خانات التوقيع أسفل التقرير')}:`, signInput)),
    h('div', { class: 'toolbar no-print' },
      h('button', { class: 'btn', id: 'export-xlsx', onclick: () => download('xlsx') }, t('تصدير Excel')),
      h('button', { class: 'btn', id: 'export-pdf', onclick: () => download('pdf') }, t('تصدير PDF')),
      h('label', { class: 'inline' }, `${t('لغة الملف')}:`, exportLang),
      h('button', { class: 'btn ghost', onclick: () => window.print() }, t('طباعة'))),
    preview);
  drawFilters();
  await load();
}

function renderReport(rep) {
  const head = h('div', { class: 'report-head' },
    h('div', { class: 'report-school' }, rep.school_name), h('div', { class: 'report-title' }, rep.title),
    h('div', { class: 'muted' }, [rep.timetable_name, rep.filters, rep.generated_at].filter(Boolean).join(' — ')));
  const blocks = [];
  const links = [];
  const blockId = title => { const id = `r-${links.length + 1}`; links.push({ id, label: title }); return id; };
  for (const g of rep.grids) {
    const cells = new Map(g.cells.map(c => [`${c.day}|${c.period}`, c.entries]));
    const missing = new Set(g.missing.map(m => `${m.day}|${m.period}`));
    const td = (di, p) => {
      const key = `${di}|${p}`;
      if (missing.has(key)) return h('td', { class: 'none' });
      return h('td', {}, (cells.get(key) || []).map(e => h('div', { class: 'entry' },
        h('b', {}, e[0]), e.slice(1).filter(Boolean).map(x => h('div', {}, x)))));
    };
    const note = di => (g.day_notes && g.day_notes[di] ? h('span', { class: 'ptime', dir: 'ltr' }, g.day_notes[di]) : null);
    const pHead = p => [h('span', { class: 'pnum' }, String(p.no)), p.time ? h('span', { class: 'ptime', dir: 'ltr' }, p.time) : null];
    const table = rep.layout === 'cols'
      ? h('table', { class: 'data report-grid' },
          h('thead', {}, h('tr', {}, h('th', {}, t('الحصة')), g.days.map((d, di) => h('th', {}, d, note(di))))),
          h('tbody', {}, g.periods.map(p => h('tr', {}, h('th', {}, pHead(p)), g.days.map((_, di) => td(di, p.no))))))
      : h('table', { class: 'data report-grid days-rows' },
          h('thead', {}, h('tr', {}, h('th', {}, t('اليوم')), g.periods.map(p => h('th', {}, pHead(p))))),
          h('tbody', {}, g.days.map((d, di) => h('tr', {}, h('th', { class: 'dayname' }, d, note(di)), g.periods.map(p => td(di, p.no))))));
    blocks.push(h('section', { class: 'report-block', id: blockId(g.title) }, h('h3', {}, g.title),
      g.subtitle ? h('div', { class: 'muted' }, g.subtitle) : null,
      h('div', { class: 'grid-scroll' }, table),
      g.footer ? h('p', { class: 'legend' }, g.footer) : null));
  }
  for (const tb of rep.tables) {
    const numeric = new Set([...tb.numeric, ...tb.percent]);
    const colors = new Map((tb.cell_colors || []).map(c => [`${c.row}|${c.col}`, c.color]));
    const groupStarts = new Set(tb.row_groups || []);
    const fmt = (v, j) => (v == null ? '' : tb.percent.includes(j) ? `${Math.round(v * 100)}%` : String(v));
    const rows = tb.rows.map((r, i) => h('tr', { class: groupStarts.has(i) && i ? 'group-start' : null }, r.map((v, j) => {
      const c = colors.get(`${i}|${j}`);
      return h('td', { class: numeric.has(j) ? 'num' : '', style: c ? { '--c': c } : null, dataset: c ? { tint: '1' } : {} }, fmt(v, j));
    })));
    if (tb.totals) rows.push(h('tr', { class: 'total' }, tb.totals.map((v, j) => h('td', { class: numeric.has(j) ? 'num' : '' }, fmt(v, j)))));
    const thead = h('thead', {},
      tb.group_header ? h('tr', { class: 'group-head' }, tb.group_header.map(g => h('th', { colspan: g.span, class: 'daygroup' }, g.label))) : null,
      h('tr', {}, tb.columns.map(c => h('th', {}, c))));
    const titleText = tb.title && tb.title !== rep.title ? tb.title : '';
    blocks.push(h('section', { class: 'report-block', id: blockId(tb.title || rep.title) }, titleText ? h('h3', {}, titleText) : null,
      tb.subtitle ? h('div', { class: 'muted' }, tb.subtitle) : null,
      h('div', { class: 'grid-scroll' }, h('table', { class: `data report-table${tb.compact ? ' compact' : ''}` }, thead, h('tbody', {}, rows)))));
  }
  for (const n of rep.notes || []) blocks.push(h('p', { class: 'legend' }, n));
  if (rep.signature && rep.signature.length && blocks.length) {
    blocks.push(h('div', { class: 'signature-row' }, rep.signature.map(x => h('div', {}, h('b', {}, x), h('div', { class: 'sign-line' })))));
  }
  if (!blocks.length) blocks.push(h('p', { class: 'muted' }, t('لا توجد بيانات مطابقة')));
  return h('div', {}, links.length > 1 ? pageNav(links) : null, head, blocks);
}
