// Time-off grid: click a cell to mark the teacher/section/room/subject unavailable in that period.
import * as api from '../api.js';
import { t } from '../i18n.js';
import { canEdit, invalidate, list } from '../store.js';
import { h, nameOf, toastError, put, swap } from '../ui.js';
import { loadContext, noTimetable } from './ctx.js';

export async function render(root) {
  const ctx = await loadContext();
  if (!ctx) return noTimetable(root);
  let kind = sessionStorage.getItem('av:kind') || 'teacher';
  let entityId = sessionStorage.getItem('av:entity') || '';
  const host = h('div');
  const editable = canEdit() && !ctx.readOnly;

  const options = () => ({
    teacher: ctx.teachers.map(x => ({ value: x.id, label: nameOf(x) })),
    section: ctx.sortedSections().map(s => ({ value: s.id, label: ctx.sectionLabel(s.id) })),
    room: ctx.rooms.map(x => ({ value: x.id, label: nameOf(x) })),
    subject: ctx.subjects.map(x => ({ value: x.id, label: nameOf(x) })),
  }[kind]);

  function periods(dayId) {
    if (kind === 'section') { const s = ctx.section[entityId]; return s ? ctx.periodsFor(s.grade_id, dayId).map(p => p.period_no) : []; }
    const set = new Set();
    for (const g of ctx.grades) for (const p of ctx.periodsFor(g.id, dayId)) set.add(p.period_no);
    return [...set].sort((a, b) => a - b);
  }

  async function draw() {
    if (!entityId) { swap(host, h('p', { class: 'muted' }, t('اختر من القائمة'))); return; }
    const rows = await list('availability', `?timetable_id=${ctx.tt.id}&entity_type=${kind}&entity_id=${entityId}`);
    const key = (d, p) => `${d}|${p}`;
    const map = new Map(rows.map(r => [key(r.weekday_id, r.period_no), r]));
    const dp = ctx.days.map(d => periods(d.id));
    const maxP = Math.max(0, ...dp.flat());
    swap(host, h('table', { class: 'tt-grid av-grid' },
      h('thead', {}, h('tr', {}, h('th'), ctx.days.map(d => h('th', {}, nameOf(d))))),
      h('tbody', {}, Array.from({ length: maxP }, (_, i) => i + 1).map(p => h('tr', {}, h('th', {}, p),
        ctx.days.map((d, di) => {
          if (!dp[di].includes(p)) return h('td', { class: 'slot none' });
          const r = map.get(key(d.id, p));
          return h('td', { class: `slot${r ? ' unavailable' : ''}`, dataset: { day: d.id, period: p },
                           title: r ? t('غير متاح') : t('متاح'),
                           onclick: editable ? () => toggle(d.id, p, r) : null }, r ? '✕' : '');
        }))))),
      h('p', { class: 'legend' }, t('اضغط على الخانة لتبديلها بين متاح / غير متاح. الحصص لا توضع في خانة غير متاحة.')));
  }
  async function toggle(dayId, period, row) {
    try {
      if (row) await api.del(`/api/availability/${row.id}`, row.version);
      else await api.post('/api/availability', { timetable_id: ctx.tt.id, entity_type: kind, entity_id: entityId,
                                                 weekday_id: dayId, period_no: period, status: 'unavailable' });
    } catch (e) { toastError(e); }
    invalidate('availability');
    await draw();
  }

  const entitySel = h('select', { onchange: e => { entityId = e.target.value; sessionStorage.setItem('av:entity', entityId); draw(); } });
  function fill() {
    const opts = options();
    if (!opts.some(o => o.value === entityId)) entityId = opts[0]?.value || '';
    entitySel.replaceChildren(...opts.map(o => h('option', { value: o.value, selected: o.value === entityId }, o.label)));
  }
  const kindSel = h('select', { onchange: e => { kind = e.target.value; sessionStorage.setItem('av:kind', kind); fill(); draw(); } },
    [['teacher', 'معلم'], ['section', 'شعبة'], ['room', 'قاعة'], ['subject', 'مبحث']]
      .map(([v, l]) => h('option', { value: v, selected: v === kind }, t(l))));
  fill();
  put(root, h('h1', { class: 'title' }, `${t('أوقات عدم التوفر')} — ${ctx.tt.name}`),
    h('div', { class: 'toolbar' }, kindSel, entitySel), host);
  await draw();
}
