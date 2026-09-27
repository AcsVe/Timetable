// Loads everything a timetable screen needs in one go and resolves bell periods client-side
// (same rule as the server: grade-specific assignment wins over the stage-wide one).
import * as api from '../api.js';
import { t } from '../i18n.js';
import { byId, currentTimetable, list } from '../store.js';
import { h, nameOf, put } from '../ui.js';

export async function loadContext() {
  const tt = currentTimetable();
  if (!tt) return null;
  const [stages, grades, sections, divisions, groups, subjects, teachers, rooms, weekdays, scheds, assigns, lessonsR] =
    await Promise.all([
      list('stages'), list('grades'), list('sections'), list('divisions'), list('groups'), list('subjects'),
      list('teachers'), list('rooms'), list('weekdays'), list('bell-schedules'),
      list('bell-assignments', `?term_id=${tt.term_id}`),
      api.get(`/api/timetables/${tt.id}/lessons`),
    ]);
  const lessons = lessonsR.items;
  const ctx = {
    tt, stages, grades, sections, divisions, groups, subjects, teachers, rooms, scheds, assigns, lessons,
    days: weekdays.filter(d => d.is_school_day).sort((a, b) => a.sort_order - b.sort_order),
    stage: byId(stages), grade: byId(grades), section: byId(sections), division: byId(divisions), group: byId(groups),
    subject: byId(subjects), teacher: byId(teachers), room: byId(rooms), sched: byId(scheds), lesson: byId(lessons),
    readOnly: tt.status === 'archived',
  };
  ctx.cards = lessons.flatMap(l => l.cards.map(c => ({ ...c, lesson: l })));
  ctx.sectionLabel = id => {
    const s = ctx.section[id];
    return s ? `${nameOf(ctx.grade[s.grade_id])} / ${nameOf(s)}` : '?';
  };
  ctx.targetLabel = tg => {
    const base = ctx.sectionLabel(tg.section_id);
    return tg.group_id ? `${base} (${nameOf(ctx.group[tg.group_id])})` : base;
  };
  ctx.periodsFor = (gradeId, dayId) => {
    const g = ctx.grade[gradeId];
    if (!g) return [];
    const a = assigns.find(x => x.weekday_id === dayId && x.grade_id === gradeId)
      || assigns.find(x => x.weekday_id === dayId && x.stage_id === g.stage_id && !x.grade_id);
    const s = a && ctx.sched[a.bell_schedule_id];
    return s ? s.slots.filter(x => x.kind === 'lesson') : [];
  };
  ctx.sortedSections = () => [...sections].sort((a, b) => {
    const ga = ctx.grade[a.grade_id], gb = ctx.grade[b.grade_id];
    const sa = ctx.stage[ga?.stage_id], sb = ctx.stage[gb?.stage_id];
    return (sa?.sort_order ?? 0) - (sb?.sort_order ?? 0) || (ga?.sort_order ?? 0) - (gb?.sort_order ?? 0)
      || String(a.name_ar).localeCompare(String(b.name_ar), 'ar');
  });
  return ctx;
}

export function noTimetable(root) {
  put(root, h('p', { class: 'muted' }, t('لا يوجد جدول محدد. أنشئ جدولاً من صفحة "الجداول".')),
    h('a', { href: '#/timetables', class: 'btn' }, t('الجداول')));
}
