// Config-driven setup screens for reference data.
import * as api from '../api.js';
import { t } from '../i18n.js';
import { byId, canEdit, currentTimetable, invalidate, isAdmin, list } from '../store.js';
import { confirmBox, h, nameOf, openForm, toast, toastError, put, swap } from '../ui.js';

const DOW = [[7, 'الأحد'], [1, 'الاثنين'], [2, 'الثلاثاء'], [3, 'الأربعاء'], [4, 'الخميس'], [5, 'الجمعة'], [6, 'السبت']];

// Option loaders for reference fields.
const OPTIONS = {
  stages: async () => (await list('stages')).map(o => ({ value: o.id, label: nameOf(o) })),
  grades: async () => {
    const [st, gr] = await Promise.all([list('stages'), list('grades')]);
    const s = byId(st);
    return gr.map(g => ({ value: g.id, label: `${nameOf(s[g.stage_id])} / ${nameOf(g)}` }));
  },
  sections: sectionOptions,
  rooms: async () => (await list('rooms')).map(o => ({ value: o.id, label: nameOf(o) })),
  buildings: async () => (await list('buildings')).map(o => ({ value: o.id, label: nameOf(o) })),
  subjects: async () => (await list('subjects')).map(o => ({ value: o.id, label: nameOf(o) })),
  'academic-years': async () => (await list('academic-years')).map(o => ({ value: o.id, label: o.name })),
  teachers: async () => [...(await list('teachers'))].sort((a, b) => nameOf(a).localeCompare(nameOf(b), 'ar'))
    .map(o => ({ value: o.id, label: nameOf(o) })),
  users: async () => (isAdmin() ? (await list('users')).map(o => ({ value: o.id, label: `${o.display_name} (${o.email})` })) : []),
};

export async function sectionOptions() {
  const [st, gr, se] = await Promise.all([list('stages'), list('grades'), list('sections')]);
  const s = byId(st), g = byId(gr);
  return se.map(x => {
    const grade = g[x.grade_id];
    return { value: x.id, label: `${grade ? nameOf(grade) : ''} / ${nameOf(x)}`, stage: grade && grade.stage_id,
             grade: x.grade_id, sort: `${s[grade?.stage_id]?.sort_order ?? 0}-${grade?.sort_order ?? 0}-${x.name_ar}` };
  }).sort((a, b) => a.sort.localeCompare(b.sort, 'ar'));
}

const CONFIG = {
  stages: { title: 'المراحل', fields: [
    { name: 'name_ar', label: 'الاسم (عربي)', required: true }, { name: 'name_en', label: 'الاسم (إنجليزي)' },
    { name: 'sort_order', label: 'الترتيب', type: 'number' }] },
  grades: { title: 'الصفوف', filter: 'stage_id', fields: [
    { name: 'stage_id', label: 'المرحلة', type: 'select', ref: 'stages', required: true },
    { name: 'name_ar', label: 'الاسم (عربي)', required: true }, { name: 'name_en', label: 'الاسم (إنجليزي)' },
    { name: 'sort_order', label: 'الترتيب', type: 'number' }] },
  sections: { title: 'الشعب', filter: 'grade_id', fields: [
    { name: 'grade_id', label: 'الصف', type: 'select', ref: 'grades', required: true },
    { name: 'name_ar', label: 'الاسم (عربي)', required: true }, { name: 'name_en', label: 'الاسم (إنجليزي)' },
    { name: 'student_count', label: 'عدد الطلبة', type: 'number' },
    { name: 'home_room_id', label: 'الغرفة الصفية', type: 'select', ref: 'rooms' },
    { name: 'class_teacher_id', label: 'مربي الصف', type: 'select', ref: 'teachers' }],
    columns: ['grade_id', 'name_ar', 'student_count', 'class_teacher_id', 'home_room_id'],
    // Quick actions, like the buttons beside ASC's class list.
    actions: [
      { label: 'الجدول', go: s => goTo('#/grid', 'grid:view', { mode: 'section', entityId: s.id }) },
      { label: 'الدروس', go: s => goTo('#/lessons', 'lessons:filter', { section: s.id }) },
      { label: 'أوقات عدم التوفر', go: s => { sessionStorage.setItem('av:kind', 'section'); sessionStorage.setItem('av:entity', s.id); location.hash = '#/availability'; } },
      { label: 'التقسيمات', go: s => { sessionStorage.setItem('div:section', s.id); location.hash = '#/setup/divisions'; } },
    ] },
  subjects: { title: 'المباحث', fields: [
    { name: 'name_ar', label: 'الاسم (عربي)', required: true }, { name: 'name_en', label: 'الاسم (إنجليزي)' },
    { name: 'short_ar', label: 'اختصار (عربي)' }, { name: 'color', label: 'اللون', type: 'color' },
    { name: 'max_teachers_per_block', label: 'أقصى عدد من المعلمين في البطاقة الواحدة', type: 'number', min: 1,
      help: 'لحصص الأولاد والبنات، أو الموسيقى والدراما، استخدم مجموعتين من التقسيم نفسه بدلاً من رفع هذا الرقم' },
    { name: 'requires_room_type', label: 'نوع القاعة المطلوب', placeholder: 'lab / gym / music' },
    { name: 'room_ids', label: 'القاعات المسموحة', type: 'multi', ref: 'rooms' }] },
  teachers: { title: 'المعلمون', fields: [
    { name: 'name_ar', label: 'الاسم (عربي)', required: true }, { name: 'name_en', label: 'الاسم (إنجليزي)' },
    { name: 'title', label: 'اللقب', placeholder: 'أ. / د. / م.' }, { name: 'short', label: 'اختصار' },
    { name: 'email', label: 'البريد الإلكتروني', type: 'email' }, { name: 'phone', label: 'الهاتف' },
    { name: 'gender', label: 'الجنس', type: 'select', options: [{ value: 'm', label: 'ذكر' }, { value: 'f', label: 'أنثى' }] },
    { name: 'color', label: 'اللون', type: 'color' },
    { name: 'stage_ids', label: 'المراحل التي يدرّس فيها', type: 'multi', ref: 'stages' },
    { name: 'subject_ids', label: 'المباحث المؤهّل لها', type: 'multi', ref: 'subjects' },
    { name: 'target_weekly_periods', label: 'النصاب الأسبوعي', type: 'number', min: 0 },
    { name: 'max_periods_per_day', label: 'أقصى عدد من الحصص يومياً', type: 'number', min: 0 },
    { name: 'max_gaps_per_day', label: 'أقصى عدد من الفجوات يومياً', type: 'number', min: 0 },
    { name: 'max_gaps_per_week', label: 'أقصى عدد من الفجوات أسبوعياً', type: 'number', min: 0 },
    { name: 'max_consecutive', label: 'أقصى عدد من الحصص المتتالية', type: 'number', min: 0 },
    { name: 'max_days_per_week', label: 'أقصى عدد من أيام الدوام', type: 'number', min: 0 },
    { name: 'user_id', label: 'حساب المستخدم المرتبط', type: 'select', ref: 'users', adminOnly: true }],
    columns: ['name_ar', 'short', 'stage_ids', 'subject_ids', 'target_weekly_periods'],
    extraColumns: teacherCounts,
    actions: [
      { label: 'الجدول', go: x => goTo('#/grid', 'grid:view', { mode: 'teacher', entityId: x.id }) },
      { label: 'الدروس', go: x => goTo('#/lessons', 'lessons:filter', { teacher: x.id }) },
      { label: 'أوقات عدم التوفر', go: x => { sessionStorage.setItem('av:kind', 'teacher'); sessionStorage.setItem('av:entity', x.id); location.hash = '#/availability'; } },
    ] },
  rooms: { title: 'القاعات', fields: [
    { name: 'name_ar', label: 'الاسم (عربي)', required: true }, { name: 'name_en', label: 'الاسم (إنجليزي)' },
    { name: 'short', label: 'اختصار' }, { name: 'building_id', label: 'المبنى', type: 'select', ref: 'buildings' },
    { name: 'room_type', label: 'نوع القاعة', placeholder: 'lab / gym / music' },
    { name: 'capacity', label: 'السعة', type: 'number' },
    { name: 'is_shared', label: 'مشتركة (تتّسع لأكثر من صف في الوقت نفسه)', type: 'bool' }] },
  buildings: { title: 'المباني', fields: [
    { name: 'name_ar', label: 'الاسم (عربي)', required: true }, { name: 'name_en', label: 'الاسم (إنجليزي)' }] },
  'academic-years': { title: 'السنوات الدراسية', fields: [
    { name: 'name', label: 'الاسم', required: true, placeholder: '2026/2027' },
    { name: 'start_date', label: 'تاريخ البداية', type: 'date' }, { name: 'end_date', label: 'تاريخ النهاية', type: 'date' },
    { name: 'is_current', label: 'السنة الحالية', type: 'bool' }] },
  terms: { title: 'الفصول الدراسية', filter: 'academic_year_id', fields: [
    { name: 'academic_year_id', label: 'السنة الدراسية', type: 'select', ref: 'academic-years', required: true },
    { name: 'name_ar', label: 'الاسم (عربي)', required: true }, { name: 'name_en', label: 'الاسم (إنجليزي)' },
    { name: 'ordinal', label: 'الترتيب', type: 'number', required: true, min: 1 },
    { name: 'start_date', label: 'تاريخ البداية', type: 'date' }, { name: 'end_date', label: 'تاريخ النهاية', type: 'date' }] },
  weekdays: { title: 'أيام الأسبوع', fields: [
    { name: 'iso_dow', label: 'اليوم', type: 'select', required: true, options: DOW.map(([v, l]) => ({ value: v, label: l })) },
    { name: 'name_ar', label: 'الاسم (عربي)', required: true }, { name: 'name_en', label: 'الاسم (إنجليزي)' },
    { name: 'sort_order', label: 'الترتيب', type: 'number' }, { name: 'is_school_day', label: 'يوم دراسي', type: 'bool' }] },
  users: { title: 'المستخدمون', fields: [
    { name: 'display_name', label: 'الاسم', required: true }, { name: 'email', label: 'البريد الإلكتروني', type: 'email', required: true },
    { name: 'role', label: 'الدور', type: 'select', required: true, options: [
      { value: 'admin', label: 'مدير النظام' }, { value: 'stage_editor', label: 'محرّر مرحلة' }, { value: 'viewer', label: 'مشاهد' }] },
    { name: 'stage_ids', label: 'المراحل المسموحة (لمحرّر المرحلة)', type: 'multi', ref: 'stages' },
    { name: 'password', label: 'كلمة المرور', type: 'password', help: 'اتركها فارغةً للإبقاء على كلمة المرور الحالية (ثمانية أحرف على الأقل)' },
    { name: 'valid_until', label: 'صالح حتى تاريخ (للحساب البديل المؤقت)', type: 'datetime' },
    { name: 'is_active', label: 'مفعَّل', type: 'bool' },
    { name: 'preferred_lang', label: 'اللغة', type: 'select', required: true,
      options: [{ value: 'ar', label: 'العربية' }, { value: 'en', label: 'English' }] }],
    columns: ['display_name', 'email', 'role', 'stage_ids', 'valid_until', 'is_active'], defaults: { is_active: true, preferred_lang: 'ar', role: 'viewer' } },
};

const NUMERIC_SELECT = new Set(['iso_dow']);

function goTo(hash, key, value) {
  sessionStorage.setItem(key, JSON.stringify(value));
  location.hash = hash;
}

/** "Count" and "Time off" columns of ASC's teacher list, for the currently selected timetable. */
async function teacherCounts() {
  const tt = currentTimetable();
  if (!tt) return [];
  const [lessons, off] = await Promise.all([
    api.get(`/api/timetables/${tt.id}/lessons`).then(r => r.items),
    list('availability', `?timetable_id=${tt.id}&entity_type=teacher`)]);
  const count = {}, placed = {}, offN = {};
  for (const l of lessons) for (const x of l.teachers) {
    count[x.teacher_id] = (count[x.teacher_id] || 0) + l.periods_per_week;
    placed[x.teacher_id] = (placed[x.teacher_id] || 0) + l.cards.filter(c => c.weekday_id).reduce((a, c) => a + c.duration, 0);
  }
  for (const a of off) offN[a.entity_id] = (offN[a.entity_id] || 0) + 1;
  return [
    { label: t('عدد الحصص'), get: x => {
      const n = count[x.id] || 0, target = x.target_weekly_periods;
      return h('span', { class: target != null && n > target ? 'reasons' : '' }, `${n}${placed[x.id] !== undefined ? ` (${t('المُدرَج')} ${placed[x.id]})` : ''}`);
    } },
    { label: t('أوقات عدم التوفر'), get: x => (offN[x.id] ? h('span', { class: 'chip' }, offN[x.id]) : '—') },
  ];
}

async function resolveFields(cfg) {
  const out = [];
  for (const f of cfg.fields) {
    if (f.adminOnly && !isAdmin()) continue;
    const g = { ...f, label: t(f.label), help: f.help && t(f.help) };
    if (f.ref) g.options = await OPTIONS[f.ref]();
    if (f.options && !f.ref) g.options = f.options.map(o => ({ ...o, label: t(o.label) }));
    out.push(g);
  }
  return out;
}

function fmt(f, v) {
  if (v === null || v === undefined || v === '') return '';
  if (f.type === 'bool') return v ? '✓' : '—';
  if (f.type === 'color') return h('span', { class: 'swatch', style: { background: v } });
  if (f.type === 'select' && f.options) {
    const o = f.options.find(x => String(x.value) === String(v));
    return o ? o.label : '';
  }
  if (f.type === 'multi') {
    const m = Object.fromEntries((f.options || []).map(o => [o.value, o.label]));
    return v.map(x => h('span', { class: 'chip' }, m[x] || '?'));
  }
  if (f.type === 'datetime') return new Date(v).toLocaleString(document.documentElement.lang === 'en' ? 'en-GB' : 'ar-JO');
  return String(v);
}

export async function render(root, [res]) {
  if (res === 'divisions') return renderDivisions(root);
  const cfg = CONFIG[res];
  if (!cfg) { put(root, h('p', {}, t('الصفحة غير موجودة'))); return; }
  const fields = await resolveFields(cfg);
  const fieldMap = Object.fromEntries(fields.map(f => [f.name, f]));
  const columns = (cfg.columns || cfg.fields.filter(f => f.type !== 'password' && f.type !== 'multi').map(f => f.name).slice(0, 6))
    .filter(c => fieldMap[c]);
  const filterField = cfg.filter && fieldMap[cfg.filter];
  let filterValue = sessionStorage.getItem(`filter:${res}`) || '';

  const tableHost = h('div');
  async function draw() {
    const [items, extra] = await Promise.all([
      list(res, filterValue && filterField ? `?${cfg.filter}=${filterValue}` : ''),
      cfg.extraColumns ? cfg.extraColumns().catch(() => []) : []]);
    const rows = items.map(item => h('tr', { dataset: { id: item.id } },
      columns.map(c => h('td', {}, fmt(fieldMap[c], item[c]))),
      extra.map(x => h('td', {}, x.get(item))),
      h('td', { class: 'row-actions' },
        (cfg.actions || []).map(a => [h('button', { class: 'btn small ghost', onclick: () => a.go(item) }, t(a.label)), ' ']),
        canEdit() ? [
          h('button', { class: 'btn small ghost', onclick: () => edit(item) }, t('تعديل')), ' ',
          h('button', { class: 'btn small ghost', onclick: () => remove(item) }, t('حذف'))] : null)));
    swap(tableHost, items.length
      ? h('div', { class: 'grid-scroll' }, h('table', { class: 'data' }, h('thead', {}, h('tr', {}, columns.map(c => h('th', {}, fieldMap[c].label)),
          extra.map(x => h('th', {}, x.label)), h('th'))),
          h('tbody', {}, rows)))
      : h('p', { class: 'muted' }, t('لا توجد سجلات بعد')));
  }

  async function save(values, item) {
    const body = { ...values };
    for (const f of fields) {
      if (NUMERIC_SELECT.has(f.name) && body[f.name] !== null) body[f.name] = Number(body[f.name]);
    }
    if (item) await api.patch(`/api/${res}/${item.id}`, { ...body, version: item.version });
    else await api.post(`/api/${res}`, body);
    invalidate(res);
    toast(t('تم الحفظ'), 'ok');
    await draw();
  }
  const edit = item => openForm({ title: `${t('تعديل')} — ${t(cfg.title)}`, fields, values: item,
                                  onSubmit: v => save(v, item) });
  const add = () => openForm({ title: `${t('إضافة')} — ${t(cfg.title)}`, fields,
                               values: { ...(cfg.defaults || {}), ...(filterField && filterValue ? { [cfg.filter]: filterValue } : {}) },
                               onSubmit: v => save(v, null) });
  async function remove(item) {
    if (!(await confirmBox(t('أتريد حذف هذا السجل؟')))) return;
    try {
      await api.del(`/api/${res}/${item.id}`, item.version);
      invalidate(res);
      toast(t('تم الحذف'), 'ok');
      await draw();
    } catch (e) { toastError(e); }
  }

  const toolbar = h('div', { class: 'toolbar' },
    canEdit() ? h('button', { class: 'btn', onclick: add }, `+ ${t('إضافة')}`) : null,
    filterField ? h('label', { class: 'inline' }, `${filterField.label}:`,
      h('select', { onchange: e => { filterValue = e.target.value; sessionStorage.setItem(`filter:${res}`, filterValue); draw(); } },
        h('option', { value: '' }, t('الكل')),
        filterField.options.map(o => h('option', { value: o.value, selected: o.value === filterValue }, o.label)))) : null);
  put(root, h('h1', { class: 'title' }, t(cfg.title)), toolbar, tableHost);
  await draw();
}

// ---------------------------------------------------------------------------
// Divisions & groups: per section
// ---------------------------------------------------------------------------
async function renderDivisions(root) {
  const sections = await sectionOptions();
  let sectionId = sessionStorage.getItem('div:section') || (sections[0] && sections[0].value) || '';
  const host = h('div');
  const help = h('p', { class: 'muted' }, t('يقسم التقسيمُ الشعبةَ إلى مجموعات تُدرَّس في الحصة نفسها، مثل: التربية الرياضية (أولاد / بنات)، أو (موسيقى / دراما). ويجوز أن تجتمع مجموعات التقسيم الواحد في حصة واحدة، أما مجموعات تقسيمين مختلفين فتتعارض.'));

  async function draw() {
    if (!sectionId) { swap(host, h('p', { class: 'muted' }, t('أضف شعبة أولاً'))); return; }
    const [divs, groups] = await Promise.all([list('divisions', `?section_id=${sectionId}`), list('groups')]);
    swap(host, ...divs.map(d => {
      const gs = groups.filter(g => g.division_id === d.id);
      return h('div', { class: 'stat', style: { marginBottom: '12px' } },
        h('div', { class: 'toolbar' }, h('b', {}, d.name),
          canEdit() ? [
            h('button', { class: 'btn small ghost', onclick: () => addGroup(d) }, `+ ${t('مجموعة')}`),
            h('button', { class: 'btn small ghost', onclick: () => rename(d) }, t('تعديل')),
            h('button', { class: 'btn small ghost', onclick: () => remove('divisions', d) }, t('حذف'))] : null),
        gs.length ? gs.map(g => h('span', { class: 'chip' }, nameOf(g),
          canEdit() ? h('button', { class: 'btn small ghost', style: { border: 0, padding: '0 4px' },
                                    title: t('حذف'), onclick: () => remove('groups', g) }, '×') : null))
          : h('span', { class: 'muted' }, t('لا توجد مجموعات')));
    }), divs.length ? '' : h('p', { class: 'muted' }, t('لا توجد تقسيمات لهذه الشعبة')));
  }
  const refresh = async () => { invalidate('divisions', 'groups'); await draw(); };
  const addDivision = () => openForm({ title: t('تقسيم جديد'), fields: [
    { name: 'name', label: t('اسم التقسيم'), required: true, placeholder: t('أولاد/بنات') },
    { name: 'groups', label: t('المجموعات (افصل بينها بفاصلة)'), placeholder: t('أولاد، بنات'), full: true }],
    onSubmit: async v => {
      const d = await api.post('/api/divisions', { section_id: sectionId, name: v.name });
      for (const g of (v.groups || '').split(/[،,]/).map(s => s.trim()).filter(Boolean)) {
        await api.post('/api/groups', { division_id: d.id, name_ar: g });
      }
      await refresh();
    } });
  const addGroup = d => openForm({ title: `${t('مجموعة جديدة')} — ${d.name}`,
    fields: [{ name: 'name_ar', label: t('الاسم (عربي)'), required: true }, { name: 'name_en', label: t('الاسم (إنجليزي)') },
             { name: 'student_count', label: t('عدد الطلبة'), type: 'number' }],
    onSubmit: async v => { await api.post('/api/groups', { ...v, division_id: d.id }); await refresh(); } });
  const rename = d => openForm({ title: t('تعديل'), fields: [{ name: 'name', label: t('اسم التقسيم'), required: true }],
    values: d, onSubmit: async v => { await api.patch(`/api/divisions/${d.id}`, { name: v.name, version: d.version }); await refresh(); } });
  async function remove(res, o) {
    if (!(await confirmBox(t('أتريد حذف هذا السجل؟')))) return;
    try { await api.del(`/api/${res}/${o.id}`, o.version); await refresh(); } catch (e) { toastError(e); }
  }

  put(root, h('h1', { class: 'title' }, t('التقسيمات والمجموعات')), help,
    h('div', { class: 'toolbar' },
      h('label', { class: 'inline' }, `${t('الشعبة')}:`, h('select', {
        onchange: e => { sectionId = e.target.value; sessionStorage.setItem('div:section', sectionId); draw(); } },
        sections.map(o => h('option', { value: o.value, selected: o.value === sectionId }, o.label)))),
      canEdit() && sectionId ? h('button', { class: 'btn', onclick: addDivision }, `+ ${t('تقسيم جديد')}`) : null),
    host);
  await draw();
}
