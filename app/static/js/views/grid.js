// Timetable grid with drag & drop (and tap-to-place on touch screens).
// While a card is picked up, every cell is coloured from /api/cards/<id>/allowed-slots
// (the same server rule engine that validates the save), so the user sees where it can go before dropping.
//
// Views: one section / teacher / room (days as rows or as columns), or the whole school
// (every section or every teacher in rows, days × periods in columns — like ASC's main screen).
import * as api from '../api.js';
import { t } from '../i18n.js';
import { canEdit, invalidate } from '../store.js';
import { h, nameOf, put, swap, toast, toastError, withCount } from '../ui.js';
import { loadContext, noTimetable } from './ctx.js';
import { loadNotice } from './loads.js';

const WHOLE = new Set(['whole-sections', 'whole-teachers']);

// ---------------------------------------------------------------- colours
// Distinct, readable pastel colours (golden-angle hues) and shades of one colour for a subject's teachers.
const hsl = (hue, s, l) => {
  s /= 100; l /= 100;
  const k = n => (n + hue / 30) % 12, a = s * Math.min(l, 1 - l);
  const f = n => Math.round(255 * (l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)))));
  return `#${[f(0), f(8), f(4)].map(x => x.toString(16).padStart(2, '0')).join('')}`;
};
export const distinctColor = i => hsl((i * 137.508) % 360, 62 + (i % 3) * 8, 76 - (i % 2) * 8);
const hexToHsl = hex => {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || '');
  if (!m) return null;
  const [r, g, b] = [0, 2, 4].map(i => parseInt(m[1].slice(i, i + 2), 16) / 255);
  const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2, d = max - min;
  const s = d ? d / (1 - Math.abs(2 * l - 1)) : 0;
  let hh = 0;
  if (d) hh = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [(hh * 60 + 360) % 360, s * 100, l * 100];
};
const shade = (hex, i, n) => {
  const x = hexToHsl(hex);
  if (!x) return hex;
  const steps = Math.max(n, 1);
  return hsl(x[0], Math.max(45, x[1]), 58 + (30 * (i % steps)) / Math.max(steps - 1, 1));
};
export const inkFor = hex => {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || '');
  if (!m) return '#1d2330';
  const [r, g, b] = [0, 2, 4].map(i => parseInt(m[1].slice(i, i + 2), 16));
  return (0.299 * r + 0.587 * g + 0.114 * b) > 150 ? '#1d2330' : '#ffffff';
};

export async function render(root) {
  let ctx = await loadContext();
  if (!ctx) return noTimetable(root);
  const saved = JSON.parse(sessionStorage.getItem('grid:view') || '{}');
  let mode = saved.mode || 'section';
  let entityId = saved.entityId || '';
  let orient = saved.orient || 'rows';        // rows: days are rows (ASC print / SCL style); cols: days are columns
  let stageId = saved.stageId || '';          // whole-school filter
  let colorBy = saved.colorBy || 'subject';   // subject | teacher | subject-teachers | none
  let showPalette = false;
  let picked = null;                          // card currently being dragged / selected
  let allowed = null;                         // Map "dayId|period" -> {ok, messages}
  const editable = canEdit() && !ctx.readOnly;
  const gridHost = h('div', { class: 'grid-wrap' });
  const info = h('div', { class: 'legend' });
  const noticeHost = h('div');
  const noticeP = loadNotice(ctx.tt);
  const isWhole = () => WHOLE.has(mode);

  // ------------------------------------------------------------------ data helpers
  const teacherName = id => ctx.teacher[id]?.short || nameOf(ctx.teacher[id]);
  const entities = () => {
    if (mode === 'teacher') return [...ctx.teachers].sort((a, b) => nameOf(a).localeCompare(nameOf(b), 'ar')).map(x => ({ value: x.id, label: nameOf(x) }));
    if (mode === 'room') return ctx.rooms.map(x => ({ value: x.id, label: nameOf(x) }));
    return ctx.sortedSections().map(s => ({ value: s.id, label: ctx.sectionLabel(s.id) }));
  };
  const stageOfSection = sid => ctx.grade[ctx.section[sid]?.grade_id]?.stage_id;
  // Rows of the whole-school view.
  const wholeRows = () => {
    if (mode === 'whole-sections') {
      return ctx.sortedSections().filter(s => !stageId || stageOfSection(s.id) === stageId)
        .map(s => ({ id: s.id, label: ctx.sectionLabel(s.id), gradeId: s.grade_id }));
    }
    return [...ctx.teachers].filter(x => !stageId || (x.stage_ids || []).includes(stageId))
      .sort((a, b) => nameOf(a).localeCompare(nameOf(b), 'ar')).map(x => ({ id: x.id, label: nameOf(x), gradeId: null }));
  };
  // Does this card belong to a given row / the selected entity?
  const belongs = (card, rowId) => {
    const l = card.lesson;
    if (mode === 'teacher' || mode === 'whole-teachers') return l.teachers.some(x => x.teacher_id === rowId);
    if (mode === 'room') return card.room_id === rowId || (!card.weekday_id && l.preferred_room_id === rowId);
    return l.targets.some(x => x.section_id === rowId);
  };
  const unionPeriods = dayId => {
    const seen = new Map();
    for (const g of ctx.grades) for (const p of ctx.periodsFor(g.id, dayId)) if (!seen.has(p.period_no)) seen.set(p.period_no, p);
    return [...seen.values()].sort((a, b) => a.period_no - b.period_no);
  };
  const periodsFor = (gradeId, dayId) => (gradeId ? ctx.periodsFor(gradeId, dayId) : unionPeriods(dayId));

  // ------------------------------------------------------------------ cards
  function chip(card, rowId, { continuation = false, mini = false } = {}) {
    const l = card.lesson;
    const subj = ctx.subject[l.subject_id];
    const bySection = mode === 'section' || mode === 'whole-sections';
    const groups = l.targets.filter(x => x.section_id === rowId && x.group_id).map(x => nameOf(ctx.group[x.group_id]));
    const sub = l.kind === 'meeting' ? (mini ? '' : `${t('الأعضاء')}: ${l.teachers.length}`) : bySection
      ? [groups.join('، '), mini ? '' : l.teachers.map(x => teacherName(x.teacher_id)).join('، ')].filter(Boolean).join(' · ')
      : l.targets.map(x => (mini ? ctx.sectionLabel(x.section_id) : ctx.targetLabel(x))).join('، ');
    const room = card.room_id ? nameOf(ctx.room[card.room_id]) : '';
    const isMeeting = l.kind === 'meeting';
    const full = [isMeeting ? l.title : nameOf(subj), bySection ? groups.join('، ') : '', l.targets.map(x => ctx.targetLabel(x)).join('، '),
                  l.teachers.map(x => nameOf(ctx.teacher[x.teacher_id])).join('، '), room].filter(Boolean);
    const bg = chipColor(l);
    const el = h('div', {
      class: `card-chip${mini ? ' mini' : ''}${card.duration > 1 && !continuation && !mini ? ' double' : ''}${colorBy === 'none' ? ' plain' : ''}`,
      style: { background: bg, color: inkFor(bg), opacity: continuation ? '.55' : null },
      draggable: editable && !card.is_locked && !continuation ? 'true' : null,
      dataset: { card: card.id }, title: [...new Set(full)].join('\n'),
    },
      h('div', { class: 'subj' }, isMeeting ? l.title : (subj?.short_ar || nameOf(subj)), continuation && !mini ? ` (${t('تتمّة')})` : ''),
      sub ? h('div', {}, sub) : null,
      room && !mini ? h('div', { class: 'muted' }, room) : null,
      !continuation && !mini && (card.is_locked || editable) ? h('span', {
        class: 'lock', role: 'button', title: card.is_locked ? t('مقفلة — انقر لإلغاء القفل') : t('انقر لقفل الحصة'),
        style: { opacity: card.is_locked ? 1 : .25, cursor: editable ? 'pointer' : 'default' },
        onclick: e => { e.stopPropagation(); if (editable) toggleLock(card); } }, '🔒') : null,
      mini && card.is_locked && !continuation ? h('span', { class: 'lock' }, '🔒') : null);
    if (editable && !continuation) {
      el.addEventListener('dragstart', e => { e.dataTransfer.setData('text/plain', card.id); e.dataTransfer.effectAllowed = 'move'; pick(card, el); });
      el.addEventListener('dragend', () => unpick());
      el.addEventListener('click', e => { e.stopPropagation(); (picked && picked.id === card.id ? unpick() : pick(card, el)); });
    }
    return el;
  }

  // ------------------------------------------------------------------ colours
  const subjectIndex = id => ctx.subjects.findIndex(x => x.id === id);
  const teacherIndex = id => ctx.teachers.findIndex(x => x.id === id);
  const subjectColor = id => ctx.subject[id]?.color || distinctColor(Math.max(0, subjectIndex(id)));
  const teacherColor = id => ctx.teacher[id]?.color || distinctColor(Math.max(0, teacherIndex(id)) + 7);
  const subjectTeachers = sid => [...new Set(ctx.lessons.filter(l => l.subject_id === sid).flatMap(l => l.teachers.map(x => x.teacher_id)))]
    .sort((a, b) => nameOf(ctx.teacher[a]).localeCompare(nameOf(ctx.teacher[b]), 'ar'));
  function chipColor(l) {
    const tid = l.teachers[0]?.teacher_id;
    if (colorBy === 'none') return '#ffffff';
    if (colorBy === 'teacher') return tid ? teacherColor(tid) : '#dbe7f7';
    if (colorBy === 'subject-teachers') {
      const list = subjectTeachers(l.subject_id);
      return shade(subjectColor(l.subject_id), Math.max(0, list.indexOf(tid)), list.length);
    }
    return subjectColor(l.subject_id);
  }

  async function pick(card, el) {
    if (card.is_locked) { toast(t('الحصة مقفلة؛ ألغِ قفلها أولاً'), 'err'); return; }
    unpick();
    picked = card;
    el.classList.add('dragging');
    info.textContent = t('اختر خانةً خضراء لوضع الحصة فيها، أو أفلِتها في صندوق "غير مُدرَجة" لإزالتها من الجدول.');
    try {
      const r = await api.get(`/api/cards/${card.id}/allowed-slots`);
      if (picked !== card) return;
      allowed = new Map();
      for (const d of r.days) for (const p of d.periods) allowed.set(`${d.weekday_id}|${p.period_no}`, p);
      paintAllowed();
    } catch (e) { /* colouring is a hint only; the save is still validated */ }
  }
  function unpick() {
    picked = null; allowed = null;
    gridHost.querySelectorAll('.dragging').forEach(x => x.classList.remove('dragging'));
    gridHost.querySelectorAll('td.slot').forEach(td => { td.classList.remove('allowed', 'blocked', 'over'); td.title = ''; });
    info.textContent = '';
  }
  function paintAllowed() {
    gridHost.querySelectorAll('td.slot[data-day]').forEach(td => {
      if (td.classList.contains('none')) return;
      // In the whole-school view only the rows the card belongs to are candidates.
      if (td.dataset.row && !belongs(picked, td.dataset.row)) return;
      const a = allowed && allowed.get(`${td.dataset.day}|${td.dataset.period}`);
      td.classList.toggle('allowed', !!(a && a.ok));
      td.classList.toggle('blocked', !!(a && !a.ok) || (!a && !!allowed));
      td.title = a && !a.ok ? a.messages.join('\n') : '';
    });
  }

  async function place(card, dayId, period, rowId) {
    if (rowId && !belongs(card, rowId)) { toast(t('هذه الحصة لا تخص هذا الصف من الجدول'), 'err'); return; }
    let msg = null, err = null;
    try {
      await api.patch(`/api/cards/${card.id}`, { version: card.version, weekday_id: dayId, period_no: period });
      msg = dayId ? t('تم وضع الحصة') : t('أُزيلت الحصة من الجدول');
    } catch (e) { err = e; }
    unpick();
    if (!err || !api.isOffline()) { ctx = await loadContext(); draw(); }
    // Toast after the redraw, so the message always matches what is on screen.
    if (err) toastError(err); else toast(msg, 'ok');
  }
  async function toggleLock(card) {
    try { await api.patch(`/api/cards/${card.id}`, { version: card.version, is_locked: !card.is_locked }); }
    catch (e) { toastError(e); }
    ctx = await loadContext();
    draw();
  }

  function slot(di, day, p, exists, cards, rowId, mini) {
    const td = h('td', { class: `slot${exists ? '' : ' none'}${mini ? ' mini' : ''}`,
                         dataset: { di, period: p, ...(exists ? { day: day.id } : {}), ...(rowId && isWhole() ? { row: rowId } : {}) } });
    if (!exists) return td;
    for (const c of cards) {
      if (c.weekday_id !== day.id) continue;
      if (c.period_no === p) td.append(chip(c, rowId, { mini }));
      else if (c.period_no < p && c.period_no + c.duration > p) td.append(chip(c, rowId, { continuation: true, mini }));
    }
    if (editable) {
      td.addEventListener('dragover', e => { if (picked) { e.preventDefault(); td.classList.add('over'); } });
      td.addEventListener('dragleave', () => td.classList.remove('over'));
      td.addEventListener('drop', e => { e.preventDefault(); td.classList.remove('over'); if (picked) place(picked, day.id, p, isWhole() ? rowId : null); });
      td.addEventListener('click', e => { if (picked && e.target === td) place(picked, day.id, p, isWhole() ? rowId : null); });
    }
    return td;
  }
  const timeLabel = x => (x ? h('span', { class: 'ptime', dir: 'ltr' }, `${x.starts_at.slice(0, 5)}–${x.ends_at.slice(0, 5)}`) : null);

  // ------------------------------------------------------------------ single entity grid
  function singleTable(cards) {
    const gradeId = mode === 'section' ? ctx.section[entityId]?.grade_id : null;
    const dayPeriods = ctx.days.map(d => periodsFor(gradeId, d.id));
    const maxP = Math.max(0, ...dayPeriods.flat().map(p => p.period_no));
    const periods = Array.from({ length: maxP }, (_, i) => i + 1);
    const pInfo = p => (mode === 'section' ? dayPeriods.flat().find(x => x.period_no === p) : null);
    const cell = (di, p) => slot(di, ctx.days[di], p, dayPeriods[di].some(x => x.period_no === p), cards, entityId, false);
    if (orient === 'cols') {
      return h('table', { class: 'tt-grid' },
        h('thead', {}, h('tr', {}, h('th'), ctx.days.map(d => h('th', {}, nameOf(d))))),
        h('tbody', {}, periods.map(p => h('tr', {}, h('th', {}, `${p}`, timeLabel(pInfo(p))),
          ctx.days.map((_, di) => cell(di, p))))));
    }
    return h('table', { class: 'tt-grid days-rows' },
      h('thead', {}, h('tr', {}, h('th'), periods.map(p => h('th', {}, h('span', { class: 'pnum' }, p), timeLabel(pInfo(p)))))),
      h('tbody', {}, ctx.days.map((d, di) => h('tr', {}, h('th', { class: 'dayname' }, nameOf(d)), periods.map(p => cell(di, p))))));
  }

  // ------------------------------------------------------------------ whole school grid
  function wholeTable(rows) {
    const perDay = ctx.days.map(d => unionPeriods(d.id).map(p => p.period_no));
    return h('table', { class: 'tt-grid whole' },
      h('thead', {},
        h('tr', {}, h('th', { rowspan: 2, class: 'rowhead' }), ctx.days.map((d, di) => h('th', { colspan: perDay[di].length || 1, class: 'daygroup' }, nameOf(d)))),
        h('tr', {}, ctx.days.map((d, di) => perDay[di].map(p => h('th', { class: `pcol${p === perDay[di][0] ? ' daystart' : ''}` }, p))))),
      h('tbody', {}, rows.map(r => {
        const cards = ctx.cards.filter(c => belongs(c, r.id));
        return h('tr', { dataset: { row: r.id } }, h('th', { class: 'rowhead' }, r.label),
          ctx.days.map((d, di) => {
            const own = new Set(periodsFor(r.gradeId, d.id).map(x => x.period_no));
            return perDay[di].map(p => {
              const td = slot(di, d, p, own.has(p), cards, r.id, true);
              if (p === perDay[di][0]) td.classList.add('daystart');
              return td;
            });
          }));
      })));
  }

  function legend(cards) {
    if (colorBy === 'none') return null;
    if (colorBy === 'teacher') {
      const ids = [...new Set(cards.flatMap(c => c.lesson.teachers.map(x => x.teacher_id)))].filter(id => ctx.teacher[id])
        .sort((a, b) => nameOf(ctx.teacher[a]).localeCompare(nameOf(ctx.teacher[b]), 'ar'));
      return ids.length ? h('div', { class: 'subject-legend' }, ids.map(id => h('span', { class: 'legend-item' },
        h('span', { class: 'swatch', style: { background: teacherColor(id) } }), nameOf(ctx.teacher[id])))) : null;
    }
    const ids = [...new Set(cards.map(c => c.lesson.subject_id))].filter(id => ctx.subject[id])
      .sort((a, b) => nameOf(ctx.subject[a]).localeCompare(nameOf(ctx.subject[b]), 'ar'));
    return ids.length ? h('div', { class: 'subject-legend' }, ids.map(id => {
      const s = ctx.subject[id];
      const head = h('span', { class: 'legend-item' }, h('span', { class: 'swatch', style: { background: subjectColor(id) } }),
        s.short_ar ? `${s.short_ar} — ${nameOf(s)}` : nameOf(s));
      if (colorBy !== 'subject-teachers') return head;
      const list = subjectTeachers(id);
      return h('span', { class: 'legend-group' }, head, list.map((tid, i) => h('span', { class: 'legend-item sub' },
        h('span', { class: 'swatch', style: { background: shade(subjectColor(id), i, list.length) } }), nameOf(ctx.teacher[tid]))));
    })) : null;
  }

  // Palette: change a subject's or teacher's colour here, or give everything distinct colours in one go.
  function palette(cards) {
    if (!showPalette) return null;
    const byTeacher = colorBy === 'teacher';
    const ids = byTeacher
      ? [...new Set(cards.flatMap(c => c.lesson.teachers.map(x => x.teacher_id)))].filter(id => ctx.teacher[id])
      : [...new Set(cards.map(c => c.lesson.subject_id))].filter(id => ctx.subject[id]);
    const res = byTeacher ? 'teachers' : 'subjects';
    const obj = id => (byTeacher ? ctx.teacher[id] : ctx.subject[id]);
    const colorOf = id => (byTeacher ? teacherColor(id) : subjectColor(id));
    async function setColor(id, color) {
      const o = obj(id);
      const r = await api.patch(`/api/${res}/${id}`, { version: o.version, color });
      Object.assign(o, r);
    }
    async function setMany(pairs) {
      try {
        for (const [id, color] of pairs) await setColor(id, color);
        invalidate(res); ctx = await loadContext(); draw();
        toast(t('تم حفظ الألوان'), 'ok');
      } catch (e) { toastError(e); }
    }
    const all = (byTeacher ? ctx.teachers : ctx.subjects).map(x => x.id);
    return h('div', { class: 'palette no-print' },
      h('div', { class: 'toolbar' }, h('b', {}, byTeacher ? t('ألوان المعلمين') : t('ألوان المباحث')),
        editable ? h('button', { type: 'button', class: 'btn small ghost', onclick: () => setMany(all.map((id, i) => [id, distinctColor(i + (byTeacher ? 7 : 0))])) },
          t('ألوان متباينة تلقائياً للجميع')) : null,
        h('span', { class: 'muted small' }, colorBy === 'subject-teachers' ? t('في عرض «المبحث ومعلموه» يأخذ كل معلم درجة من لون مبحثه.') : '')),
      h('div', { class: 'palette-items' }, ids.sort((a, b) => nameOf(obj(a)).localeCompare(nameOf(obj(b)), 'ar')).map(id =>
        h('label', { class: 'palette-item' },
          h('input', { type: 'color', value: colorOf(id), disabled: !editable, 'aria-label': `${t('اللون')} — ${nameOf(obj(id))}`,
                       onchange: e => setMany([[id, e.target.value]]) }),
          nameOf(obj(id))))));
  }

  function draw() {
    let cards, table;
    if (entitySel) fillEntities();   // keep the placed / total counts in the list current
    if (isWhole()) {
      const rows = wholeRows();
      cards = ctx.cards.filter(c => rows.some(r => belongs(c, r.id)));
      table = rows.length ? wholeTable(rows) : h('p', { class: 'muted' }, t('لا توجد بيانات مطابقة'));
    } else {
      if (!entityId) { swap(gridHost, h('p', { class: 'muted' }, t('اختر من القائمة لعرض الجدول'))); return; }
      cards = ctx.cards.filter(c => belongs(c, entityId));
      table = singleTable(cards);
    }
    const unplaced = cards.filter(c => !c.weekday_id);
    const tray = h('div', { class: `tray${isWhole() ? ' tray-wide' : ''}` }, h('h3', {}, `${t('غير مُدرَجة')} (${unplaced.length})`),
      unplaced.length ? unplaced.map(c => chip(c, isWhole() ? c.lesson.targets[0]?.section_id : entityId, { mini: isWhole() }))
        : h('p', { class: 'muted tray-hint' }, t('أُدرِجت الحصص كلها')));
    if (editable) {
      tray.addEventListener('dragover', e => { if (picked && picked.weekday_id) { e.preventDefault(); tray.classList.add('over'); } });
      tray.addEventListener('dragleave', () => tray.classList.remove('over'));
      tray.addEventListener('drop', e => { e.preventDefault(); tray.classList.remove('over'); if (picked && picked.weekday_id) place(picked, null, null); });
      tray.addEventListener('click', e => { if (picked && picked.weekday_id && !e.target.closest('.card-chip')) place(picked, null, null); });
    }
    const total = cards.reduce((a, c) => a + c.duration, 0);
    const placed = cards.filter(c => c.weekday_id).reduce((a, c) => a + c.duration, 0);
    swap(gridHost, h('div', { class: 'grid-scroll' }, palette(cards), table,
      h('p', { class: 'legend' }, `${t('المُدرَج')}: ${placed} / ${total} · ${t('اسحب الحصة، أو انقر عليها ثم انقر على الخانة المطلوبة. الخانات الخضراء متاحة، والحمراء فيها تعارض (مرِّر المؤشر فوقها لمعرفة السبب).')}`),
      legend(cards)),
      tray);
    gridHost.classList.toggle('stacked', isWhole());
  }

  // ------------------------------------------------------------------ toolbar
  const persist = () => sessionStorage.setItem('grid:view', JSON.stringify({ mode, entityId, orient, stageId, colorBy }));
  const colorSel = h('select', { id: 'grid-color', 'aria-label': t('التلوين'), onchange: e => { colorBy = e.target.value; persist(); draw(); } },
    [['subject', t('لون لكل مبحث')], ['teacher', t('لون لكل معلم')], ['subject-teachers', t('المبحث ومعلموه (درجات اللون)')], ['none', t('بلا ألوان')]]
      .map(([v, l]) => h('option', { value: v, selected: v === colorBy }, l)));
  const paletteBtn = h('button', { class: 'btn ghost', type: 'button', id: 'grid-palette', 'aria-pressed': 'false',
    onclick: () => { showPalette = !showPalette; paletteBtn.setAttribute('aria-pressed', String(showPalette)); draw(); } }, t('تعديل الألوان'));
  var entitySel = h('select', { id: 'grid-entity', 'aria-label': t('اختر من القائمة'), onchange: e => { entityId = e.target.value; persist(); draw(); } });
  const stageSel = h('select', { id: 'grid-stage', 'aria-label': t('المرحلة'), onchange: e => { stageId = e.target.value; persist(); draw(); } });
  const orientSel = h('select', { id: 'grid-orient', 'aria-label': t('اتجاه الجدول'), onchange: e => { orient = e.target.value; persist(); draw(); } },
    [['rows', t('الأيام صفوفاً')], ['cols', t('الأيام أعمدةً')]].map(([v, l]) => h('option', { value: v, selected: v === orient }, l)));
  function syncControls() {
    fillStages();
    entitySel.hidden = isWhole();
    orientSel.hidden = isWhole();
    stageSel.hidden = !isWhole();
  }
  function fillEntities() {
    if (isWhole()) return;
    const opts = entities();
    if (!opts.some(o => o.value === entityId)) entityId = opts[0]?.value || '';
    // each choice shows its placed / total periods
    const tally = id => {
      let placed = 0, total = 0;
      for (const c of ctx.cards) if (belongs(c, id)) { total += c.duration; if (c.weekday_id) placed += c.duration; }
      return `${placed} / ${total}`;
    };
    entitySel.replaceChildren(...opts.map(o => h('option', { value: o.value, selected: o.value === entityId, dataset: { label: o.label } },
      withCount(o.label, tally(o.value)))));
  }
  function fillStages() {
    const rowsIn = st => (mode === 'whole-teachers'
      ? ctx.teachers.filter(x => !st || (x.stage_ids || []).includes(st)).length
      : ctx.sortedSections().filter(x => !st || stageOfSection(x.id) === st).length);
    stageSel.replaceChildren(h('option', { value: '' }, withCount(t('جميع المراحل'), rowsIn(''))),
      ...ctx.stages.map(st => h('option', { value: st.id, selected: st.id === stageId }, withCount(nameOf(st), rowsIn(st.id)))));
  }
  const modeSel = h('select', { id: 'grid-mode', 'aria-label': t('طريقة العرض'), onchange: e => { mode = e.target.value; entityId = ''; fillEntities(); syncControls(); persist(); draw(); } },
    [['section', t('حسب الشعبة')], ['teacher', t('حسب المعلم')], ['room', t('حسب القاعة')],
     ['whole-sections', t('الجدول الكامل — الشعب')], ['whole-teachers', t('الجدول الكامل — المعلمون')]]
      .map(([v, l]) => h('option', { value: v, selected: v === mode }, l)));
  fillEntities();
  syncControls();

  // One click from the grid to a printable PDF of what is on screen (one page per section / teacher).
  function printPdf() {
    const kinds = { section: 'section-timetable', 'whole-sections': 'section-timetable', teacher: 'teacher-timetable',
                    'whole-teachers': 'teacher-timetable', room: 'room-timetable' };
    const q = new URLSearchParams({ format: 'pdf', lang: document.documentElement.lang === 'en' ? 'en' : 'ar', layout: 'rows' });
    const key = { section: 'section_id', teacher: 'teacher_id', room: 'room_id' }[mode];
    if (key && entityId) q.set(key, entityId);
    else if (stageSel.value) q.set('stage_id', stageSel.value);
    window.open(`/api/timetables/${ctx.tt.id}/reports/${kinds[mode]}?${q}`, '_blank');
  }

  put(root, h('h1', { class: 'title' }, `${t('شبكة الجدول')} — ${ctx.tt.name}`),
    ctx.readOnly ? h('p', { class: 'reasons' }, t('هذا الجدول مؤرشف وللقراءة فقط')) : null,
    h('div', { class: 'toolbar sticky' }, modeSel, entitySel, stageSel, orientSel, colorSel, paletteBtn,
      h('button', { class: 'btn', id: 'grid-print', type: 'button', onclick: printPdf }, t('طباعة PDF')),
      h('a', { class: 'btn ghost', href: '#/lessons' }, t('الدروس والتوزيع')),
      h('a', { class: 'btn ghost', href: '#/validate' }, t('التحقق'))),
    info, gridHost, noticeHost);
  swap(noticeHost, await noticeP);
  if (!window.__gridEsc) {
    window.__gridEsc = true;
    document.addEventListener('keydown', e => { if (e.key === 'Escape') document.querySelectorAll('.card-chip.dragging').forEach(x => x.click()); });
  }
  draw();
}
