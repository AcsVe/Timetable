import * as api from '../api.js';
import { t } from '../i18n.js';
import { invalidate, state } from '../store.js';
import { h, toast, toastError, put } from '../ui.js';

export async function render(root) {
  const items = (await api.get('/api/school')).items;
  let school = items[0] || null;
  const f = (name, label, v, extra = {}) => h('div', { class: 'field' }, h('label', { for: `s-${name}` }, label),
    h('input', { id: `s-${name}`, name, value: v ?? '', ...extra }));
  const preview = h('img', { src: school?.logo_path || '', style: { maxHeight: '80px' }, hidden: !school?.logo_path });
  const form = h('form', { class: 'stat', style: { maxWidth: '640px' } },
    h('div', { class: 'form-grid' },
      f('name_ar', t('اسم المدرسة (عربي)'), school?.name_ar, { required: true }),
      f('name_en', t('اسم المدرسة (إنجليزي)'), school?.name_en),
      h('div', { class: 'field full' }, h('label', { for: 's-logo_path' }, t('رابط الشعار')),
        h('input', { id: 's-logo_path', name: 'logo_path', value: school?.logo_path || '', placeholder: 'https://…/logo.png',
                     oninput: e => { preview.src = e.target.value; preview.hidden = !e.target.value; } }),
        h('div', { class: 'muted', style: { fontSize: '.8rem' } }, t('يظهر الشعار في رأس الواجهة وفي كل تقرير مطبوع أو مُصدَّر.'))),
      h('div', { class: 'field full' }, preview)),
    h('div', { class: 'modal-actions' }, h('button', { class: 'btn', type: 'submit' }, t('حفظ'))));
  form.onsubmit = async ev => {
    ev.preventDefault();
    const body = Object.fromEntries(new FormData(form).entries());
    for (const k of Object.keys(body)) if (body[k] === '') body[k] = null;
    try {
      school = school ? await api.patch(`/api/school/${school.id}`, { ...body, version: school.version })
                      : await api.post('/api/school', body);
      state.school = school;
      invalidate('school');
      document.getElementById('school-name').textContent = school.name_ar;
      toast(t('تم الحفظ'), 'ok');
    } catch (e) { toastError(e); }
  };
  put(root, h('h1', { class: 'title' }, t('بيانات المدرسة')), form);
}
