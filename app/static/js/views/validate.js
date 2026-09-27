import * as api from '../api.js';
import { lang, t } from '../i18n.js';
import { h, put } from '../ui.js';
import { loadContext, noTimetable } from './ctx.js';

export async function render(root) {
  const ctx = await loadContext();
  if (!ctx) return noTimetable(root);
  const rep = await api.get(`/api/timetables/${ctx.tt.id}/validate`);
  const cardLesson = Object.fromEntries(ctx.cards.map(c => [c.id, c.lesson]));

  function goto(item) {
    let view = null;
    if (item.teacher_id) view = { mode: 'teacher', entityId: item.teacher_id };
    else if (item.section_id) view = { mode: 'section', entityId: item.section_id };
    else {
      const l = item.card_id ? cardLesson[item.card_id] : item.lesson_id ? ctx.lesson[item.lesson_id] : null;
      if (l && l.targets[0]) view = { mode: 'section', entityId: l.targets[0].section_id };
    }
    if (!view) return null;
    return h('a', { href: '#/grid', class: 'btn small ghost',
                    onclick: () => sessionStorage.setItem('grid:view', JSON.stringify(view)) }, t('عرض في الجدول'));
  }
  const msg = i => (lang === 'en' ? i.message_en || i.message : i.message);
  const issues = (items, cls) => items.length
    ? h('ul', { class: 'issues' }, items.map(i => h('li', { class: cls }, msg(i), ' ', goto(i))))
    : h('p', { class: 'muted' }, t('لا شيء'));

  const s = rep.summary;
  put(root, 
    h('h1', { class: 'title' }, `${t('التحقق')} — ${ctx.tt.name}`),
    h('div', { class: 'stats' },
      h('div', { class: 'stat' }, h('b', { class: s.errors ? 'reasons' : '' }, s.errors), t('أخطاء')),
      h('div', { class: 'stat' }, h('b', {}, s.warnings), t('تحذيرات')),
      h('div', { class: 'stat' }, h('b', {}, `${s.periods_placed} / ${s.periods_total}`), t('الحصص المُدرَجة')),
      h('div', { class: 'stat' }, h('b', {}, s.placed_ratio == null ? '—' : `${Math.round(s.placed_ratio * 100)}%`), t('نسبة الإنجاز'))),
    h('h2', {}, t('أخطاء')), issues(rep.errors, 'err'),
    h('h2', {}, t('تحذيرات')), issues(rep.warnings, 'warn'),
    h('button', { class: 'btn ghost', onclick: () => import('../app.js').then(m => m.rerender()) }, t('إعادة الفحص')));
}
