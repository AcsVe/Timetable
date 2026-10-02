// Automatic generator: feasibility check, options, live progress, before/after quality, explanations, history.
import * as api from '../api.js';
import { loadTimetables } from '../app.js';
import { lang, t } from '../i18n.js';
import { currentTimetable, isAdmin, state } from '../store.js';
import { bulkTable, h, put, swap, toast, toastError } from '../ui.js';
import { noTimetable } from './ctx.js';

const MODES = [
  ['full', 'توليد كامل', 'يعيد توزيع كل الحصص غير المقفلة لأفضل جدول ممكن، وتبقى الحصص المقفلة في أماكنها.'],
  ['repair', 'إصلاح بأقل تغيير', 'يحسّن الجدول الحالي ويحل مشكلاته مع نقل أقل عدد ممكن من الحصص (مناسب منتصف الفصل).'],
  ['fill', 'إكمال غير الموضوعة فقط', 'لا يحرّك أي حصة موضوعة؛ يضع الحصص غير الموضوعة فقط.'],
];
const ROWS = [
  ['periods_placed', 'الحصص الموضوعة', (m) => `${m.periods_placed} / ${m.periods_total}`],
  ['teacher_gaps', 'مجموع فراغات المعلمين'],
  ['max_gaps_in_a_day', 'أكبر عدد فراغات لمعلم في يوم'],
  ['class_idle_periods', 'حصص فارغة للشعب قبل آخر حصة في اليوم'],
  ['same_day_repeats', 'تكرار حصص الدرس نفسه في اليوم الواحد'],
  ['days_over_teacher_max', 'أيام تتجاوز الحد اليومي للمعلم'],
  ['moved_cards', 'الحصص التي نُقلت من مكانها'],
];

export async function render(root) {
  const tt = currentTimetable();
  if (!tt) return noTimetable(root);
  if (!isAdmin()) { put(root, h('p', {}, t('هذه الصفحة لمدير النظام فقط'))); return; }
  const feasHost = h('div'), runHost = h('div'), histHost = h('div');
  let mode = 'full';
  let timer = null;
  let force = false;
  const ui = {};
  const num = (name, value, min, max) => h('input', { type: 'number', id: `gen-${name}`, value, min, max, class: 'narrow', 'aria-label': name });

  // ------------------------------------------------------------------ feasibility
  async function loadFeasibility() {
    swap(feasHost, h('p', { class: 'muted' }, t('جارٍ فحص الجدوى…')));
    try {
      const f = await api.get(`/api/timetables/${tt.id}/generator/feasibility`);
      swap(feasHost, h('div', { class: 'stats' },
          h('div', { class: 'stat' }, h('b', {}, f.cards), t('بطاقات')),
          h('div', { class: 'stat' }, h('b', {}, f.periods), t('حصص أسبوعياً')),
          h('div', { class: 'stat' }, h('b', {}, `${f.placed} / ${f.periods}`), t('موضوعة الآن')),
          h('div', { class: 'stat' }, h('b', {}, f.locked), t('بطاقات مقفلة'))),
        f.ok ? h('p', { class: 'notice ok' }, t('فحص الجدوى: لا يوجد ما يجعل الحل مستحيلاً حسابياً.'))
          : h('div', { class: 'notice warn' }, h('b', {}, `${t('فحص الجدوى')}: ${f.issues.length}`),
              h('ul', {}, f.issues.map(i => h('li', { class: 'err' }, lang === 'en' && i.message_en ? i.message_en : i.message))),
              h('label', { class: 'inline' }, h('input', { type: 'checkbox', id: 'gen-force', onchange: e => { force = e.target.checked; } }),
                t('تجاهل فحص الجدوى والتشغيل على أي حال (يضع أكبر عدد ممكن ويشرح الباقي)'))));
    } catch (e) { toastError(e); swap(feasHost); }
  }

  // ------------------------------------------------------------------ options
  const modeBox = h('fieldset', { class: 'plain gen-modes' }, h('legend', {}, t('طريقة التوليد')),
    MODES.map(([v, l, help]) => h('label', { class: 'mode-card' },
      h('input', { type: 'radio', name: 'gen-mode', value: v, checked: v === mode, onchange: () => { mode = v; } }),
      h('span', {}, h('b', {}, t(l)), h('span', { class: 'muted small' }, t(help))))));
  ui.target = h('select', { id: 'gen-target', 'aria-label': t('أين يُكتب الناتج') },
    h('option', { value: 'new' }, t('في مسودة جديدة (يبقى الجدول الحالي كما هو)')),
    tt.status === 'draft' ? h('option', { value: 'same' }, t('في هذه المسودة نفسها')) : null);
  ui.name = h('input', { id: 'gen-name', placeholder: `${tt.name} — ${t('مولَّد')}`, 'aria-label': t('اسم المسودة الجديدة') });
  ui.time = h('select', { id: 'gen-time', 'aria-label': t('المهلة') },
    [[30, '30 ثانية'], [60, 'دقيقة'], [120, 'دقيقتان'], [300, '5 دقائق'], [600, '10 دقائق']].map(([v, l]) => h('option', { value: v, selected: v === 60 }, t(l))));
  ui.unplaced = h('input', { type: 'checkbox', id: 'gen-allow-unplaced', checked: true });
  ui.explain = h('input', { type: 'checkbox', id: 'gen-explain', checked: true });
  ui.w = { w_gaps: num('w_gaps', 6, 0, 100), w_class_gaps: num('w_class_gaps', 8, 0, 100), w_spread: num('w_spread', 25, 0, 100), w_consecutive: num('w_consecutive', 12, 0, 100),
           w_move: num('w_move', 40, 0, 500), seed: num('seed', 1, 0, 99999), workers: num('workers', 0, 0, 16) };
  const options = h('section', { class: 'stat gen-options' }, modeBox,
    h('div', { class: 'toolbar' }, h('label', { class: 'inline' }, `${t('الناتج')}:`, ui.target), ui.name),
    h('div', { class: 'toolbar' }, h('label', { class: 'inline' }, `${t('المهلة')}:`, ui.time),
      h('label', { class: 'inline' }, ui.unplaced, t('إن تعذّر وضع كل الحصص: ضع أكبر عدد ممكن')),
      h('label', { class: 'inline' }, ui.explain, t('اشرح سبب الحصص غير الموضوعة'))),
    h('details', { class: 'more' }, h('summary', {}, t('أوزان الجودة (متقدم)')),
      h('div', { class: 'toolbar' },
        h('label', { class: 'inline' }, `${t('فراغات المعلمين')}:`, ui.w.w_gaps),
        h('label', { class: 'inline' }, `${t('فراغات الشعب (حصص فارغة وسط اليوم)')}:`, ui.w.w_class_gaps),
        h('label', { class: 'inline' }, `${t('توزيع حصص الدرس على أيام مختلفة')}:`, ui.w.w_spread),
        h('label', { class: 'inline' }, `${t('تجاوز الحصص المتتالية')}:`, ui.w.w_consecutive),
        h('label', { class: 'inline' }, `${t('نقل حصة (في الإصلاح)')}:`, ui.w.w_move),
        h('label', { class: 'inline' }, `${t('البذرة')}:`, ui.w.seed),
        h('label', { class: 'inline' }, `${t('أنوية المعالج (0 = تلقائي)')}:`, ui.w.workers)),
      h('p', { class: 'muted small' }, t('كلما زاد الوزن زادت أهمية الهدف. والبذرة نفسها مع البيانات نفسها تعطي النتيجة نفسها.'))),
    h('div', { class: 'toolbar' }, h('button', { class: 'btn big', id: 'gen-start', onclick: start }, t('تشغيل المولّد'))));

  async function start() {
    const params = { time_limit: Number(ui.time.value), allow_unplaced: ui.unplaced.checked, explain: ui.explain.checked };
    for (const [k, el] of Object.entries(ui.w)) params[k] = Number(el.value || 0);
    try {
      const r = await api.post(`/api/timetables/${tt.id}/generator/runs`, { mode, target: ui.target.value, name: ui.name.value, params, force });
      showRun(r);
      loadHistory();
    } catch (e) { toastError(e); }
  }

  // ------------------------------------------------------------------ a run
  async function openResult(id) {
    localStorage.setItem('ttId', id);
    await loadTimetables();
    state.ttId = id;
    document.getElementById('tt-select').value = id;
    location.hash = '#/grid';
  }
  function metricsTable(m) {
    const b = m.before || {}, a = m.after;
    return h('div', { class: 'grid-scroll' }, h('table', { class: 'data gen-metrics' },
      h('thead', {}, h('tr', {}, h('th', {}, t('المقياس')), h('th', {}, t('قبل')), a ? h('th', {}, t('بعد')) : null)),
      h('tbody', {}, ROWS.filter(([k]) => k in b || (a && k in a)).map(([k, l, f]) => h('tr', {},
        h('td', {}, t(l)), h('td', { class: 'num' }, k in b ? (f ? f(b) : b[k]) : '—'),
        a ? h('td', { class: `num${a[k] < (b[k] ?? Infinity) ? ' better' : ''}` }, f ? f(a) : a[k]) : null)))));
  }
  function showRun(r) {
    clearTimeout(timer);
    const p = r.progress || {};
    const limit = (r.params && r.params.time_limit) || 60;
    const running = r.status === 'queued' || r.status === 'running';
    const a = r.metrics && r.metrics.after;
    swap(runHost, h('section', { class: 'stat gen-run', id: 'gen-run' },
      h('div', { class: 'toolbar' }, h('h3', {}, r.label), running ? h('span', { class: 'spinner', 'aria-hidden': 'true' }) : null,
        running ? h('button', { class: 'btn ghost small', id: 'gen-stop', onclick: async () => {
          try { showRun(await api.post(`/api/generator/runs/${r.id}/stop`, {})); } catch (e) { toastError(e); }
        } }, t('إيقاف')) : null),
      running ? h('div', {}, h('progress', { max: limit, value: Math.min(p.elapsed || 0, limit), 'aria-label': t('التقدّم') }),
        h('p', { class: 'muted small' }, `${t('الوقت')}: ${p.elapsed || 0} / ${limit} ${t('ثانية')} — ${t('الحلول التي وُجدت')}: ${p.solutions || 0}`
          + (p.objective != null ? ` — ${t('درجة العقوبة')}: ${p.objective}` : ''))) : null,
      r.message ? h('p', { class: r.status === 'solved' ? 'notice ok' : 'notice warn' }, r.message) : null,
      (r.feasibility || []).length && r.status === 'feasibility_failed'
        ? h('ul', {}, r.feasibility.map(i => h('li', { class: 'err' }, i.message))) : null,
      r.metrics && r.metrics.before ? metricsTable(r.metrics) : null,
      a && a.worst_gaps && a.worst_gaps.length ? h('p', { class: 'small' }, `${t('أكثر المعلمين فراغات')}: `,
        a.worst_gaps.map(x => `${x.teacher} (${x.gaps})`).join('، ')) : null,
      a && a.unplaced && a.unplaced.length ? h('details', { class: 'notice warn', open: true },
        h('summary', {}, `${t('حصص لم تُوضع')}: ${a.unplaced.reduce((s, x) => s + x.periods, 0)}`),
        h('ul', {}, a.unplaced.map(x => h('li', {}, `${x.label}: ${x.periods}`)))) : null,
      r.infeasible_core && r.infeasible_core.length ? h('div', { class: 'notice warn' },
        h('b', {}, t('هذه الشروط لا يمكن تحقيقها معاً، فأرخِ واحداً منها على الأقل:')),
        h('ul', {}, r.infeasible_core.map(c => h('li', {}, c.message)))) : null,
      r.result_timetable_id ? h('div', { class: 'toolbar' },
        h('button', { class: 'btn', id: 'gen-open', onclick: () => openResult(r.result_timetable_id) }, t('فتح الجدول الناتج في الشبكة'))) : null));
    if (running) {
      timer = setTimeout(async () => {
        if (!document.getElementById('gen-run')) return;   // left the page
        try { const x = await api.get(`/api/generator/runs/${r.id}`); showRun(x); if (!['queued', 'running'].includes(x.status)) { loadHistory(); if (x.result_timetable_id) loadTimetables(); } }
        catch (e) { toastError(e); }
      }, 2000);
    }
  }

  // ------------------------------------------------------------------ history
  async function loadHistory() {
    const r = await api.get(`/api/timetables/${tt.id}/generator/runs`);
    const modeName = Object.fromEntries(MODES.map(([v, l]) => [v, t(l)]));
    const tb = bulkTable({
      items: r.items, text: x => [x.label, modeName[x.mode], x.message].join(' '),
      columns: [
        { label: t('الوقت'), get: x => h('span', { dir: 'ltr' }, (x.created_at || '').slice(0, 16).replace('T', ' ')) },
        { label: t('الطريقة'), get: x => modeName[x.mode] },
        { label: t('النتيجة'), get: x => h('span', { class: `chip ${['solved'].includes(x.status) ? 'ok' : ''}` }, x.label) },
        { label: t('الحصص الموضوعة'), get: x => (x.metrics && x.metrics.after ? `${x.metrics.after.periods_placed} / ${x.metrics.after.periods_total}` : '—') },
        { label: t('فراغات المعلمين'), cls: 'num', get: x => (x.metrics && x.metrics.after ? x.metrics.after.teacher_gaps : '—') },
        { label: t('المدة (ثانية)'), cls: 'num', get: x => (x.progress && x.progress.elapsed) || '—' },
      ],
      actions: x => [h('button', { class: 'btn small ghost', onclick: () => { showRun(x); document.getElementById('gen-run')?.scrollIntoView(); } }, t('تفاصيل')),
        x.result_timetable_id ? h('button', { class: 'btn small ghost', onclick: () => openResult(x.result_timetable_id) }, t('فتح')) : null],
      onBulkDelete: async items => {
        const res = await api.post('/api/generator/runs/bulk-delete', { ids: items.map(x => x.id) });
        toast(`${t('تم الحذف')}: ${res.deleted}`, 'ok'); loadHistory();
      },
      emptyText: t('لم يُشغَّل المولّد على هذا الجدول بعد'),
    });
    swap(histHost, tb.el);
    const live = r.items.find(x => x.status === 'queued' || x.status === 'running');
    if (live && !runHost.firstChild) showRun(live);
  }

  put(root, h('h1', { class: 'title' }, `${t('المولّد التلقائي')} — ${tt.name}`),
    h('p', { class: 'muted' }, t('يبني المولّد الجدول آلياً مع احترام كل القواعد: لا تعارض للمعلم أو الشعبة أو القاعة، والتقسيمات والمجموعات، وتوقيت كل صف والاستراحات، وأوقات عدم التوفر، وحدود كل معلم. ثم يقلل فراغات المعلمين ويوزع حصص كل مبحث على أيام الأسبوع. ويُكتب الناتج في مسودة جديدة فلا يمسّ الجدول الحالي حتى تعتمده.')),
    feasHost, options, runHost,
    h('h2', { class: 'section-title' }, t('سجل التشغيل')), histHost);
  await loadFeasibility();
  await loadHistory();
}
