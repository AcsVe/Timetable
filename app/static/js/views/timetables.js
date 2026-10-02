import * as api from '../api.js';
import { loadTimetables } from '../app.js';
import { countAr, t } from '../i18n.js';
import { byId, invalidate, isAdmin, list, state } from '../store.js';
import { confirmBox, h, nameOf, openForm, toast, toastError, put, swap } from '../ui.js';

const STATUS = { draft: 'مسودة', published: 'منشور', archived: 'مؤرشف' };

export async function render(root) {
  const [terms, years] = await Promise.all([list('terms'), list('academic-years')]);
  const y = byId(years);
  const termLabel = tm => `${nameOf(tm)} — ${y[tm.academic_year_id]?.name || ''}`;
  const termOpts = terms.map(tm => ({ value: tm.id, label: termLabel(tm) }));
  const tmap = byId(terms);
  const host = h('div');

  async function refresh() { invalidate('timetables'); await loadTimetables(); draw(); }

  function draw() {
    const heads = [t('الاسم'), t('الفصل'), t('الحالة'), t('تاريخ النشر'), t('الإجراءات')];
    const cell = (i, ...kids) => h('td', { 'data-label': heads[i] }, ...kids);
    const rows = state.timetables.map(tt => h('tr', {},
      cell(0, h('b', {}, tt.name), tt.id === state.ttId ? h('span', { class: 'chip' }, t('المعروض حالياً')) : null),
      cell(1, tmap[tt.term_id] ? termLabel(tmap[tt.term_id]) : ''),
      cell(2, h('span', { class: `chip status-${tt.status}` }, t(STATUS[tt.status]))),
      cell(3, tt.published_at ? new Date(tt.published_at).toLocaleDateString() : '—'),
      h('td', { class: 'actions', 'data-label': heads[4] },
        h('button', { class: 'btn small ghost', onclick: () => open(tt) }, t('فتح')),
        isAdmin() ? [
          h('button', { class: 'btn small ghost', onclick: () => copy(tt) }, t('نسخ كمسودة')),
          tt.status !== 'published' ? h('button', { class: 'btn small', onclick: () => publish(tt) }, t('نشر')) : null,
          h('button', { class: 'btn small ghost', onclick: () => rename(tt) }, t('تعديل الاسم')),
          h('button', { class: 'btn small ghost danger-text', onclick: () => remove(tt) }, t('حذف'))] : null)));
    swap(host, state.timetables.length
      ? [h('p', { class: 'muted small count' }, `${t('العدد')}: ${state.timetables.length}`),
         h('table', { class: 'data stack' }, h('thead', {}, h('tr', {}, heads.map(x => h('th', {}, x)))),
          h('tbody', {}, rows))]
      : h('p', { class: 'muted' }, t('لا يوجد جدول بعد. أنشئ سنةً دراسية وفصلاً دراسياً، ثم جدولاً جديداً.')));
  }

  function open(tt) {
    state.ttId = tt.id;
    try { localStorage.setItem('ttId', tt.id); } catch (_) { /* ignore */ }
    document.getElementById('tt-select').value = tt.id;
    location.hash = '#/grid';
  }
  const create = () => openForm({ title: t('جدول جديد'), fields: [
    { name: 'term_id', label: t('الفصل الدراسي'), type: 'select', options: termOpts, required: true },
    { name: 'name', label: t('الاسم'), required: true, placeholder: t('المسودة 1') }],
    onSubmit: async v => { const tt = await api.post('/api/timetables', v); await refresh(); open(tt); } });
  const rename = tt => openForm({ title: t('تعديل'), values: tt, fields: [{ name: 'name', label: t('الاسم'), required: true }],
    onSubmit: async v => { await api.patch(`/api/timetables/${tt.id}`, { name: v.name, version: tt.version }); await refresh(); } });
  const copy = tt => openForm({ title: t('نسخ كمسودة'), values: { name: `${tt.name} (${t('نسخة')})` },
    fields: [{ name: 'name', label: t('اسم المسودة الجديدة'), required: true }],
    onSubmit: async v => {
      const r = await api.post(`/api/timetables/${tt.id}/copy`, { name: v.name });
      toast(`${t('تم النسخ')}: ${countAr(r.cards_copied, 'card')}`, 'ok');
      await refresh();
    } });
  async function publish(tt) {
    try {
      await api.post(`/api/timetables/${tt.id}/publish`, { version: tt.version });
    } catch (e) {
      if (e.details && e.details.reason === 'timetable_has_errors') {
        const n = e.details.summary.errors;
        if (!(await confirmBox(`${t('في الجدول أخطاء')}: ${n}. ${t('أتريد النشر على الرغم من ذلك؟')}`))) return;
        try { await api.post(`/api/timetables/${tt.id}/publish`, { version: tt.version, force: true }); }
        catch (e2) { toastError(e2); return; }
      } else { toastError(e); return; }
    }
    toast(t('تم النشر، وأُرشِف الجدول المنشور سابقاً'), 'ok');
    await refresh();
  }
  // Deleting a timetable takes its contents with it (lessons, cards, unavailable times, rules, cover
  // records). The first attempt asks the server what is inside; the second, after the user agrees, deletes all.
  async function remove(tt) {
    const name = `«${tt.name}»`;
    let contents = null;
    try {
      if (!(await confirmBox(`${t('أتريد حذف الجدول')} ${name}؟`))) return;
      await api.del(`/api/timetables/${tt.id}`, tt.version);
    } catch (e) {
      if (e.code !== 'has_dependents') { toastError(e); return; }
      contents = e.details || {};
    }
    if (contents) {
      const parts = Object.entries(contents).filter(([k]) => k !== 'id').map(([k, n]) => `${t(k)}: ${n}`);
      const warn = tt.status === 'published' ? `\n${t('تنبيه: هذا هو الجدول المنشور للفصل، وسيبقى الفصل بلا جدول منشور حتى تنشر غيره.')}` : '';
      if (!(await confirmBox(`${t('الجدول')} ${name} ${t('يحتوي على')}: ${parts.join('، ')}.\n${t('سيُحذف الجدول مع كل محتوياته، ولا يؤثر ذلك في الجداول الأخرى ولا في البيانات الأساسية (المعلمين والمباحث والشعب).')}${warn}\n${t('أتريد المتابعة؟')}`))) return;
      try { await api.del(`/api/timetables/${tt.id}`, tt.version, { cascade: true }); }
      catch (e) { toastError(e); return; }
    }
    if (state.ttId === tt.id) { state.ttId = null; try { localStorage.removeItem('ttId'); } catch (_) { /* ignore */ } }
    toast(`${t('حُذف الجدول')} ${name}`, 'ok');
    await refresh();
  }

  put(root, h('h1', { class: 'title' }, t('الجداول')),
    h('p', { class: 'muted' }, t('اعمل على مسودة ثم انشرها. ويؤدي النشر إلى أرشفة الجدول المنشور سابقاً للفصل نفسه، والجدول المؤرشف للقراءة فقط.')),
    isAdmin() ? h('div', { class: 'toolbar' }, h('button', { class: 'btn', onclick: create }, `+ ${t('جدول جديد')}`)) : null,
    host);
  draw();
}
