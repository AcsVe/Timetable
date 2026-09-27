// Reports: preview on screen, print, or download as Excel / PDF (same data as the preview).
import * as api from '../api.js';
import { lang, t } from '../i18n.js';
import { byId, currentTimetable, list } from '../store.js';
import { h, nameOf, put, swap, toastError } from '../ui.js';
import { noTimetable } from './ctx.js';

const KINDS = [
  ['section-timetable', 'الجدول الأسبوعي للشعبة', ['stage_id', 'grade_id', 'section_id']],
  ['teacher-timetable', 'جدول حصص المعلم', ['stage_id', 'teacher_id', 'subject_id']],
  ['room-timetable', 'جدول إشغال القاعة', ['room_id']],
  ['teacher-sections', 'توزيع المعلمين على الشعب', ['stage_id', 'grade_id', 'section_id', 'teacher_id', 'subject_id']],
  ['teacher-subjects', 'توزيع المعلمين على المباحث', ['stage_id', 'grade_id', 'section_id', 'teacher_id', 'subject_id']],
  ['stats-teachers', 'إحصائيات المعلمين والنصاب', ['stage_id', 'grade_id', 'section_id', 'teacher_id', 'subject_id']],
  ['stats-subjects', 'إحصائيات المباحث', ['stage_id', 'grade_id', 'section_id', 'teacher_id', 'subject_id']],
  ['stats-sections', 'تغطية الحصص في الشعب', ['stage_id', 'grade_id', 'section_id', 'teacher_id', 'subject_id']],
];
const FILTER_LABELS = { stage_id: 'المرحلة', grade_id: 'الصف', section_id: 'الشعبة', teacher_id: 'المعلم',
                        subject_id: 'المبحث', room_id: 'القاعة' };

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
    const q = new URLSearchParams({ format: fmt, lang: exportLang || lang, layout });
    for (const k of allowed()) if (filters[k]) q.set(k, filters[k]);
    return `/api/timetables/${tt.id}/reports/${kind}?${q}`;
  };
  const persist = () => sessionStorage.setItem('reports', JSON.stringify({ kind, filters, layout }));
  const isGridKind = () => kind.endsWith('-timetable');

  const layoutSel = h('select', { id: 'report-layout', onchange: e => { layout = e.target.value; persist(); load(); } },
    [['rows', t('الأيام صفوفاً')], ['cols', t('الأيام أعمدةً')]].map(([v, l]) => h('option', { value: v, selected: v === layout }, l)));
  const layoutLabel = h('label', { class: 'inline' }, `${t('اتجاه الجدول')}:`, layoutSel);
  function drawFilters() {
    layoutLabel.hidden = !isGridKind();
    for (const k of Object.keys(filters)) if (!allowed().includes(k)) delete filters[k];
    swap(filterHost, allowed().map(k => h('label', { class: 'inline' }, `${t(FILTER_LABELS[k])}:`,
      h('select', { dataset: { filter: k }, onchange: e => {
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
      if (token === loadToken) swap(preview, renderReport(rep));
    } catch (e) { if (token === loadToken) { toastError(e); swap(preview); } }
  }

  const exportLang = h('select', { id: 'export-lang' },
    h('option', { value: 'ar', selected: lang === 'ar' }, 'العربية'), h('option', { value: 'en', selected: lang === 'en' }, 'English'));
  const download = fmt => {
    if (api.isOffline()) { toastError(new api.ApiError(0, { message: t('لا يوجد اتصال، لا يمكن التصدير الآن'), message_en: 'Offline — cannot export now' })); return; }
    const a = h('a', { href: query(fmt, exportLang.value), download: '' });
    document.body.append(a); a.click(); a.remove();
  };

  put(root,
    h('h1', { class: 'title no-print' }, `${t('التقارير')} — ${tt.name}`),
    h('div', { class: 'toolbar no-print' },
      h('label', { class: 'inline' }, `${t('التقرير')}:`, h('select', { id: 'report-kind', onchange: e => { kind = e.target.value; persist(); drawFilters(); load(); } },
        KINDS.map(([v, l]) => h('option', { value: v, selected: v === kind }, t(l)))), layoutLabel)),
    h('div', { class: 'no-print' }, filterHost),
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
  for (const g of rep.grids) {
    const cells = new Map(g.cells.map(c => [`${c.day}|${c.period}`, c.entries]));
    const missing = new Set(g.missing.map(m => `${m.day}|${m.period}`));
    const td = (di, p) => {
      const key = `${di}|${p}`;
      if (missing.has(key)) return h('td', { class: 'none' });
      return h('td', {}, (cells.get(key) || []).map(e => h('div', { class: 'entry' },
        h('b', {}, e[0]), e.slice(1).filter(Boolean).map(x => h('div', {}, x)))));
    };
    const pHead = p => [h('span', { class: 'pnum' }, String(p.no)), p.time ? h('span', { class: 'ptime', dir: 'ltr' }, p.time) : null];
    const table = rep.layout === 'cols'
      ? h('table', { class: 'data report-grid' },
          h('thead', {}, h('tr', {}, h('th', {}, t('الحصة')), g.days.map(d => h('th', {}, d)))),
          h('tbody', {}, g.periods.map(p => h('tr', {}, h('th', {}, pHead(p)), g.days.map((_, di) => td(di, p.no))))))
      : h('table', { class: 'data report-grid days-rows' },
          h('thead', {}, h('tr', {}, h('th', {}, t('اليوم')), g.periods.map(p => h('th', {}, pHead(p))))),
          h('tbody', {}, g.days.map((d, di) => h('tr', {}, h('th', { class: 'dayname' }, d), g.periods.map(p => td(di, p.no))))));
    blocks.push(h('section', { class: 'report-block' }, h('h3', {}, g.title),
      g.subtitle ? h('div', { class: 'muted' }, g.subtitle) : null,
      h('div', { class: 'grid-scroll' }, table),
      g.footer ? h('p', { class: 'legend' }, g.footer) : null));
  }
  for (const tb of rep.tables) {
    const numeric = new Set([...tb.numeric, ...tb.percent]);
    const fmt = (v, j) => (v == null ? '' : tb.percent.includes(j) ? `${Math.round(v * 100)}%` : String(v));
    const rows = tb.rows.map(r => h('tr', {}, r.map((v, j) => h('td', { class: numeric.has(j) ? 'num' : '' }, fmt(v, j)))));
    if (tb.totals) rows.push(h('tr', { class: 'total' }, tb.totals.map((v, j) => h('td', { class: numeric.has(j) ? 'num' : '' }, fmt(v, j)))));
    blocks.push(h('section', { class: 'report-block' }, h('h3', {}, tb.title),
      h('div', { class: 'grid-scroll' }, h('table', { class: 'data report-table' },
        h('thead', {}, h('tr', {}, tb.columns.map(c => h('th', {}, c)))), h('tbody', {}, rows)))));
  }
  if (!blocks.length) blocks.push(h('p', { class: 'muted' }, t('لا توجد بيانات مطابقة')));
  return h('div', {}, head, blocks);
}
