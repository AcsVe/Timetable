// Timetable grid with drag & drop (and tap-to-place on touch screens).
// While a card is picked up, every cell is coloured from /api/cards/<id>/allowed-slots
// (the same server rule engine that validates the save), so the user sees where it can go before dropping.
//
// Views: one section / teacher / room (days as rows or as columns), or the whole school
// (every section or every teacher in rows, days × periods in columns — like ASC's main screen).
import * as api from '../api.js';
import { t } from '../i18n.js';
import { canEdit } from '../store.js';
import { h, nameOf, put, swap, toast, toastError } from '../ui.js';
import { loadContext, noTimetable } from './ctx.js';

const WHOLE = new Set(['whole-sections', 'whole-teachers']);

export async function render(root) {
  let ctx = await loadContext();
  if (!ctx) return noTimetable(root);
  const saved = JSON.parse(sessionStorage.getItem('grid:view') || '{}');
  let mode = saved.mode || 'section';
  let entityId = saved.entityId || '';
  let orient = saved.orient || 'rows';        // rows: days are rows (ASC print / SCL style); cols: days are columns
  let stageId = saved.stageId || '';          // whole-school filter
  let picked = null;                          // card currently being dragged / selected
  let allowed = null;                         // Map "dayId|period" -> {ok, messages}
  const editable = canEdit() && !ctx.readOnly;
  const gridHost = h('div', { class: 'grid-wrap' });
  const info = h('div', { class: 'legend' });
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
    const sub = bySection
      ? [groups.join('، '), mini ? '' : l.teachers.map(x => teacherName(x.teacher_id)).join('، ')].filter(Boolean).join(' · ')
      : l.targets.map(x => (mini ? ctx.sectionLabel(x.section_id) : ctx.targetLabel(x))).join('، ');
    const room = card.room_id ? nameOf(ctx.room[card.room_id]) : '';
    const full = [nameOf(subj), bySection ? groups.join('، ') : '', l.targets.map(x => ctx.targetLabel(x)).join('، '),
                  l.teachers.map(x => nameOf(ctx.teacher[x.teacher_id])).join('، '), room].filter(Boolean);
    const el = h('div', {
      class: `card-chip${mini ? ' mini' : ''}${card.duration > 1 && !continuation && !mini ? ' double' : ''}`,
      style: { background: subj?.color || '#dbe7f7', opacity: continuation ? '.55' : null },
      draggable: editable && !card.is_locked && !continuation ? 'true' : null,
      dataset: { card: card.id }, title: [...new Set(full)].join('\n'),
    },
      h('div', { class: 'subj' }, subj?.short_ar || nameOf(subj), continuation && !mini ? ` (${t('تتمّة')})` : ''),
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
    const ids = [...new Set(cards.map(c => c.lesson.subject_id))];
    return ids.length ? h('div', { class: 'subject-legend' }, ids.map(id => ctx.subject[id]).filter(Boolean)
      .sort((a, b) => nameOf(a).localeCompare(nameOf(b), 'ar'))
      .map(s => h('span', { class: 'legend-item' }, h('span', { class: 'swatch', style: { background: s.color || '#dbe7f7' } }),
        s.short_ar ? `${s.short_ar} — ${nameOf(s)}` : nameOf(s)))) : null;
  }

  function draw() {
    let cards, table;
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
    swap(gridHost, h('div', { class: 'grid-scroll' }, table,
      h('p', { class: 'legend' }, `${t('المُدرَج')}: ${placed} / ${total} · ${t('اسحب الحصة، أو انقر عليها ثم انقر على الخانة المطلوبة. الخانات الخضراء متاحة، والحمراء فيها تعارض (مرِّر المؤشر فوقها لمعرفة السبب).')}`),
      legend(cards)),
      tray);
    gridHost.classList.toggle('stacked', isWhole());
  }

  // ------------------------------------------------------------------ toolbar
  const persist = () => sessionStorage.setItem('grid:view', JSON.stringify({ mode, entityId, orient, stageId }));
  const entitySel = h('select', { id: 'grid-entity', onchange: e => { entityId = e.target.value; persist(); draw(); } });
  const stageSel = h('select', { id: 'grid-stage', onchange: e => { stageId = e.target.value; persist(); draw(); } },
    h('option', { value: '' }, t('جميع المراحل')), ctx.stages.map(s => h('option', { value: s.id, selected: s.id === stageId }, nameOf(s))));
  const orientSel = h('select', { id: 'grid-orient', onchange: e => { orient = e.target.value; persist(); draw(); } },
    [['rows', t('الأيام صفوفاً')], ['cols', t('الأيام أعمدةً')]].map(([v, l]) => h('option', { value: v, selected: v === orient }, l)));
  function syncControls() {
    entitySel.hidden = isWhole();
    orientSel.hidden = isWhole();
    stageSel.hidden = !isWhole();
  }
  function fillEntities() {
    if (isWhole()) return;
    const opts = entities();
    if (!opts.some(o => o.value === entityId)) entityId = opts[0]?.value || '';
    entitySel.replaceChildren(...opts.map(o => h('option', { value: o.value, selected: o.value === entityId }, o.label)));
  }
  const modeSel = h('select', { id: 'grid-mode', onchange: e => { mode = e.target.value; entityId = ''; fillEntities(); syncControls(); persist(); draw(); } },
    [['section', t('حسب الشعبة')], ['teacher', t('حسب المعلم')], ['room', t('حسب القاعة')],
     ['whole-sections', t('الجدول الكامل — الشعب')], ['whole-teachers', t('الجدول الكامل — المعلمون')]]
      .map(([v, l]) => h('option', { value: v, selected: v === mode }, l)));
  fillEntities();
  syncControls();

  put(root, h('h1', { class: 'title' }, `${t('شبكة الجدول')} — ${ctx.tt.name}`),
    ctx.readOnly ? h('p', { class: 'reasons' }, t('هذا الجدول مؤرشف وللقراءة فقط')) : null,
    h('div', { class: 'toolbar sticky' }, modeSel, entitySel, stageSel, orientSel,
      h('a', { class: 'btn ghost', href: '#/lessons' }, t('الدروس والتوزيع')),
      h('a', { class: 'btn ghost', href: '#/validate' }, t('التحقق'))),
    info, gridHost);
  if (!window.__gridEsc) {
    window.__gridEsc = true;
    document.addEventListener('keydown', e => { if (e.key === 'Escape') document.querySelectorAll('.card-chip.dragging').forEach(x => x.click()); });
  }
  draw();
}
