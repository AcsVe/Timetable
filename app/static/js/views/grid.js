// Timetable grid with drag & drop (and tap-to-place on touch screens).
// While a card is picked up, every cell is coloured from /api/cards/<id>/allowed-slots
// (the same server rule engine that validates the save), so the user sees where it can go before dropping.
import * as api from '../api.js';
import { t } from '../i18n.js';
import { canEdit } from '../store.js';
import { h, nameOf, toast, toastError, put, swap } from '../ui.js';
import { loadContext, noTimetable } from './ctx.js';

export async function render(root) {
  let ctx = await loadContext();
  if (!ctx) return noTimetable(root);
  const saved = JSON.parse(sessionStorage.getItem('grid:view') || '{}');
  let mode = saved.mode || 'section';
  let entityId = saved.entityId || '';
  let picked = null;          // card currently being dragged / selected
  let allowed = null;         // Map "dayId|period" -> {ok, messages}
  const editable = canEdit() && !ctx.readOnly;
  const gridHost = h('div', { class: 'grid-wrap' });
  const info = h('div', { class: 'legend' });

  const entities = () => {
    if (mode === 'teacher') return [...ctx.teachers].sort((a, b) => nameOf(a).localeCompare(nameOf(b), 'ar')).map(x => ({ value: x.id, label: nameOf(x) }));
    if (mode === 'room') return ctx.rooms.map(x => ({ value: x.id, label: nameOf(x) }));
    return ctx.sortedSections().map(s => ({ value: s.id, label: ctx.sectionLabel(s.id) }));
  };
  const relevant = card => {
    const l = card.lesson;
    if (mode === 'teacher') return l.teachers.some(x => x.teacher_id === entityId);
    if (mode === 'room') return card.room_id === entityId || (!card.weekday_id && l.preferred_room_id === entityId);
    return l.targets.some(x => x.section_id === entityId);
  };

  function periodsOf(dayId) {
    if (mode === 'section') {
      const s = ctx.section[entityId];
      return s ? ctx.periodsFor(s.grade_id, dayId) : [];
    }
    // teacher / room: union of period numbers across all grades on that day
    const seen = new Map();
    for (const g of ctx.grades) for (const p of ctx.periodsFor(g.id, dayId)) if (!seen.has(p.period_no)) seen.set(p.period_no, p);
    return [...seen.values()].sort((a, b) => a.period_no - b.period_no);
  }

  function chip(card, { continuation = false } = {}) {
    const l = card.lesson;
    const subj = ctx.subject[l.subject_id];
    const sub = mode === 'section'
      ? [l.targets.filter(x => x.section_id === entityId && x.group_id).map(x => nameOf(ctx.group[x.group_id])).join('، '),
         l.teachers.map(x => ctx.teacher[x.teacher_id]?.short || nameOf(ctx.teacher[x.teacher_id])).join('، ')].filter(Boolean).join(' · ')
      : l.targets.map(x => ctx.targetLabel(x)).join('، ');
    const room = card.room_id ? nameOf(ctx.room[card.room_id]) : '';
    const el = h('div', {
      class: `card-chip${card.duration > 1 && !continuation ? ' double' : ''}`,
      style: { background: subj?.color || '#dbe7f7', opacity: continuation ? '.55' : null },
      draggable: editable && !card.is_locked && !continuation ? 'true' : null,
      dataset: { card: card.id }, title: [nameOf(subj), sub, room].filter(Boolean).join('\n'),
    },
      h('div', { class: 'subj' }, subj?.short_ar || nameOf(subj), continuation ? ` (${t('تتمّة')})` : ''),
      h('div', {}, sub), room ? h('div', { class: 'muted' }, room) : null,
      !continuation && (card.is_locked || editable) ? h('span', {
        class: 'lock', role: 'button', title: card.is_locked ? t('مقفلة — انقر لإلغاء القفل') : t('انقر لقفل الحصة'),
        style: { opacity: card.is_locked ? 1 : .25, cursor: editable ? 'pointer' : 'default' },
        onclick: e => { e.stopPropagation(); if (editable) toggleLock(card); } }, '🔒') : null);
    if (editable && !continuation) {
      el.addEventListener('dragstart', e => { e.dataTransfer.setData('text/plain', card.id); e.dataTransfer.effectAllowed = 'move'; pick(card, el); });
      el.addEventListener('dragend', () => unpick());
      el.addEventListener('click', () => (picked && picked.id === card.id ? unpick() : pick(card, el)));
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
      const a = allowed && allowed.get(`${td.dataset.day}|${td.dataset.period}`);
      td.classList.toggle('allowed', !!(a && a.ok));
      td.classList.toggle('blocked', !!(a && !a.ok) || (!a && allowed && !td.classList.contains('none')));
      td.title = a && !a.ok ? a.messages.join('\n') : '';
    });
  }

  async function place(card, dayId, period) {
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

  function dropTarget(el, dayId, period) {
    el.addEventListener('dragover', e => { if (picked) { e.preventDefault(); el.classList.add('over'); } });
    el.addEventListener('dragleave', () => el.classList.remove('over'));
    el.addEventListener('drop', e => { e.preventDefault(); el.classList.remove('over'); if (picked) place(picked, dayId, period); });
    el.addEventListener('click', e => { if (picked && (e.target === el || e.target.closest('.tray-hint'))) place(picked, dayId, period); });
  }

  function draw() {
    if (!entityId) { swap(gridHost, h('p', { class: 'muted' }, t('اختر من القائمة لعرض الجدول'))); return; }
    const cards = ctx.cards.filter(relevant);
    const dayPeriods = ctx.days.map(d => periodsOf(d.id));
    const maxP = Math.max(0, ...dayPeriods.flat().map(p => p.period_no));
    const table = h('table', { class: 'tt-grid' },
      h('thead', {}, h('tr', {}, h('th'), ctx.days.map(d => h('th', {}, nameOf(d))))),
      h('tbody', {}, Array.from({ length: maxP }, (_, i) => i + 1).map(p => h('tr', {},
        h('th', {}, `${p}`, (() => {
          const any = dayPeriods.flat().find(x => x.period_no === p);
          return mode === 'section' && any ? h('span', { class: 'ptime', dir: 'ltr' }, `${any.starts_at.slice(0, 5)}–${any.ends_at.slice(0, 5)}`) : null;
        })()),
        ctx.days.map((d, di) => {
          const exists = dayPeriods[di].some(x => x.period_no === p);
          const td = h('td', { class: `slot${exists ? '' : ' none'}`, dataset: exists ? { day: d.id, period: p } : {} });
          if (!exists) return td;
          for (const c of cards) {
            if (c.weekday_id !== d.id) continue;
            if (c.period_no === p) td.append(chip(c));
            else if (c.period_no < p && c.period_no + c.duration > p) td.append(chip(c, { continuation: true }));
          }
          if (editable) dropTarget(td, d.id, p);
          return td;
        })))));
    const unplaced = cards.filter(c => !c.weekday_id);
    const tray = h('div', { class: 'tray' }, h('h3', {}, `${t('غير مُدرَجة')} (${unplaced.length})`),
      unplaced.length ? unplaced.map(c => chip(c)) : h('p', { class: 'muted tray-hint' }, t('أُدرِجت الحصص كلها')));
    if (editable) {
      tray.addEventListener('dragover', e => { if (picked && picked.weekday_id) { e.preventDefault(); tray.classList.add('over'); } });
      tray.addEventListener('dragleave', () => tray.classList.remove('over'));
      tray.addEventListener('drop', e => { e.preventDefault(); tray.classList.remove('over'); if (picked && picked.weekday_id) place(picked, null, null); });
      tray.addEventListener('click', e => { if (picked && picked.weekday_id && !e.target.closest('.card-chip')) place(picked, null, null); });
    }
    const total = cards.reduce((a, c) => a + c.duration, 0);
    const placed = cards.filter(c => c.weekday_id).reduce((a, c) => a + c.duration, 0);
    swap(gridHost, h('div', { class: 'grid-scroll' }, table,
      h('p', { class: 'legend' }, `${t('المُدرَج')}: ${placed} / ${total} · ${t('اسحب الحصة، أو انقر عليها ثم انقر على الخانة المطلوبة. الخانات الخضراء متاحة، والحمراء فيها تعارض (مرِّر المؤشر فوقها لمعرفة السبب).')}`)),
      tray);
  }

  const entitySel = h('select', { id: 'grid-entity', onchange: e => { entityId = e.target.value; persist(); draw(); } });
  function fillEntities() {
    const opts = entities();
    if (!opts.some(o => o.value === entityId)) entityId = opts[0]?.value || '';
    entitySel.replaceChildren(...opts.map(o => h('option', { value: o.value, selected: o.value === entityId }, o.label)));
  }
  const persist = () => sessionStorage.setItem('grid:view', JSON.stringify({ mode, entityId }));
  const modeSel = h('select', { id: 'grid-mode', onchange: e => { mode = e.target.value; entityId = ''; fillEntities(); persist(); draw(); } },
    [['section', t('حسب الشعبة')], ['teacher', t('حسب المعلم')], ['room', t('حسب القاعة')]]
      .map(([v, l]) => h('option', { value: v, selected: v === mode }, l)));
  fillEntities();

  put(root, h('h1', { class: 'title' }, `${t('شبكة الجدول')} — ${ctx.tt.name}`),
    ctx.readOnly ? h('p', { class: 'reasons' }, t('هذا الجدول مؤرشف وللقراءة فقط')) : null,
    h('div', { class: 'toolbar' }, modeSel, entitySel,
      h('a', { class: 'btn ghost', href: '#/lessons' }, t('الدروس والتوزيع')),
      h('a', { class: 'btn ghost', href: '#/validate' }, t('التحقق'))),
    info, gridHost);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') unpick(); });
  draw();
}
