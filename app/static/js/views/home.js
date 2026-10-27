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

  // Clickable figures: each one opens the list it counts.
  const kpi = (n, label, href, cls = '', sub = null) => h('a', { class: `kpi ${cls}${n === 0 ? ' zero' : ''}`, href },
    h('span', { class: 'n' }, String(n)), h('span', { class: 'l' }, label), sub ? h('small', {}, sub) : null);
  const unplaced = cards.length - placed;
  const kpis = h('div', { class: 'kpis', id: 'home-kpis' },
    kpi(teachers.length, t('المعلمون'), '#/setup/teachers'),
    kpi(sections.length, t('الشعب'), '#/setup/sections'),
    kpi(subjects.length, t('المباحث'), '#/setup/subjects'),
    kpi(lessons.length, t('الدروس'), '#/lessons', '', `${t('الحصص')}: ${cards.length}`),
    kpi(placed, t('حصص في الجدول'), '#/grid', cards.length && !unplaced ? 'ok' : '', `${placed} / ${cards.length}`),
    kpi(unplaced, t('حصص غير مُدرَجة'), '#/grid', unplaced ? 'warn' : 'ok'));
  const tile = (href, icon, title, sub) => h('a', { class: 'tile', href },
    h('span', { class: 'ic', 'aria-hidden': 'true' }, h('i', { class: `fa-solid ${icon}` })),
    h('span', {}, h('b', {}, title), h('small', {}, sub)));
  const tiles = h('div', { class: 'tiles' },
    tile('#/grid', 'fa-table-cells', t('شبكة الجدول'), t('توزيع الحصص بالسحب والإفلات')),
    tile('#/validate', 'fa-circle-check', t('التحقق'), t('راجع الأخطاء ثم انشر الجدول')),
    tile('#/reports', 'fa-chart-column', t('التقارير'), t('معاينة وطباعة وتصدير إلى Excel وPDF')),
    tile('#/cover', 'fa-user-clock', t('الغياب وحصص الإشغال'), t('تسجيل الغياب وتوزيع حصص الإشغال')),
    tile('#/exams', 'fa-file-pen', t('جدول الامتحانات'), t('الامتحانات والمراقبة عليها')),
    tile('#/duties', 'fa-clipboard-user', t('جدول المناوبة'), t('توزيع المناوبة على المعلمين')));

  put(root,
    h('h1', { class: 'title' }, t('البداية')),
    isAdmin() ? h('a', { class: 'hero', href: '#/import', id: 'home-import' },
      h('span', { class: 'hero-icon', 'aria-hidden': 'true' }, h('i', { class: 'fa-solid fa-file-import' })),
      h('span', {},
        h('strong', {}, t('استيراد ملف aSc ‏(XML) أو Excel')),
        h('span', { class: 'muted' }, t('يُدخل المعلمين والمباحث والشعب والدروس والجدول دفعةً واحدة')))) : null,
    kpis,
    h('h2', { class: 'home-h2' }, t('الوصول السريع')),
    tiles,
    h('h2', { class: 'home-h2' }, t('خطوات إعداد الجدول')),
    h('ol', { class: 'steps' }, steps.map((s, i) => h('li', { class: s.done ? 'done' : i === next ? 'next' : '' },
      h('span', { class: 'step-mark', 'aria-hidden': 'true' }, s.done ? '✓' : String(i + 1)),
      h('span', { class: 'step-body' },
        h('strong', {}, s.title),
        h('span', { class: 'muted small' }, s.info),
        i === next ? h('span', { class: 'chip' }, t('الخطوة التالية')) : null),
      h('a', { class: `btn small ${i === next ? '' : 'ghost'}`, href: s.href }, t('افتح'))))));
}
