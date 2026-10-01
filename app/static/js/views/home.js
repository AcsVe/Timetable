// Start page: a guided checklist that shows what is done and what to do next, with one click to each step.
import * as api from '../api.js';
import { t } from '../i18n.js';
import { currentTimetable, isAdmin, list, state } from '../store.js';
import { h, put } from '../ui.js';

export async function render(root) {
  const tt = currentTimetable();
  const safe = p => p.catch(() => []);
  const [years, terms, stages, grades, sections, subjects, teachers, assigns, lessons] = await Promise.all([
    safe(list('academic-years')), safe(list('terms')), safe(list('stages')), safe(list('grades')),
    safe(list('sections')), safe(list('subjects')), safe(list('teachers')),
    tt ? safe(list('bell-assignments', `?term_id=${tt.term_id}`)) : Promise.resolve([]),
    tt ? api.get(`/api/timetables/${tt.id}/lessons`).then(r => r.items).catch(() => []) : Promise.resolve([]),
  ]);
  const cards = lessons.flatMap(l => l.cards);
  const placed = cards.filter(c => c.weekday_id).length;

  const steps = [
    { done: !!state.school, title: t('بيانات المدرسة'), info: t('الاسم والشعار'), href: '#/school' },
    { done: years.length > 0 && terms.length > 0, title: t('السنة والفصل الدراسي'),
      info: `${t('السنوات')}: ${years.length} — ${t('الفصول')}: ${terms.length}`, href: years.length ? '#/setup/terms' : '#/setup/academic-years' },
    { done: sections.length > 0, title: t('المراحل والصفوف والشعب'),
      info: `${t('المراحل')}: ${stages.length} — ${t('الصفوف')}: ${grades.length} — ${t('الشعب')}: ${sections.length}`,
      href: !stages.length ? '#/setup/stages' : !grades.length ? '#/setup/grades' : '#/setup/sections' },
    { done: subjects.length > 0 && teachers.length > 0, title: t('المباحث والمعلمون'),
      info: `${t('المباحث')}: ${subjects.length} — ${t('المعلمون')}: ${teachers.length}`,
      href: subjects.length ? '#/setup/teachers' : '#/setup/subjects' },
    { done: !!tt, title: t('إنشاء جدول (مسودة)'), info: tt ? tt.name : t('لا يوجد جدول بعد'), href: '#/timetables' },
    { done: assigns.length > 0, title: t('توقيت الحصص'), info: t('أوقات الحصص والاستراحات لكل يوم'), href: '#/bells' },
    { done: lessons.length > 0, title: t('الدروس والتوزيع'),
      info: `${t('الدروس')}: ${lessons.length} — ${t('الحصص')}: ${cards.length}`, href: '#/lessons' },
    { done: cards.length > 0 && placed === cards.length, title: t('توزيع الحصص على الجدول'),
      info: `${placed} / ${cards.length}`, href: '#/grid' },
    { done: tt?.status === 'published', title: t('التحقق والنشر'), info: t('راجع الأخطاء ثم انشر الجدول'), href: '#/validate' },
  ];
  const next = steps.findIndex(s => !s.done);

  put(root,
    h('h1', { class: 'title' }, t('البداية')),
    isAdmin() ? h('a', { class: 'hero', href: '#/import', id: 'home-import' },
      h('span', { class: 'hero-icon', 'aria-hidden': 'true' }, '⇪'),
      h('span', {},
        h('strong', {}, t('استيراد ملف aSc ‏(XML) أو Excel')),
        h('span', { class: 'muted' }, t('يُدخل المعلمين والمباحث والشعب والدروس والجدول دفعةً واحدة')))) : null,
    h('h2', {}, t('خطوات إعداد الجدول')),
    h('ol', { class: 'steps' }, steps.map((s, i) => h('li', { class: s.done ? 'done' : i === next ? 'next' : '' },
      h('span', { class: 'step-mark', 'aria-hidden': 'true' }, s.done ? '✓' : String(i + 1)),
      h('span', { class: 'step-body' },
        h('strong', {}, s.title),
        h('span', { class: 'muted small' }, s.info),
        i === next ? h('span', { class: 'chip' }, t('الخطوة التالية')) : null),
      h('a', { class: `btn small ${i === next ? '' : 'ghost'}`, href: s.href }, t('افتح'))))));
}
