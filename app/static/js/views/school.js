import * as api from '../api.js';
import { t } from '../i18n.js';
import { invalidate, state } from '../store.js';
import { confirmBox, h, put, toast, toastError } from '../ui.js';

export async function render(root) {
  const items = (await api.get('/api/school')).items;
  let school = items[0] || null;
  const f = (name, label, v, extra = {}) => h('div', { class: 'field' }, h('label', { for: `s-${name}` }, label),
    h('input', { id: `s-${name}`, name, value: v ?? '', ...extra }));

  const preview = h('img', { src: school?.logo_path || '', style: { maxHeight: '90px' }, hidden: !school?.logo_path, alt: '' });
  const setLogo = path => {
    preview.src = path || '';
    preview.hidden = !path;
    const top = document.getElementById('school-logo');
    top.src = path || '';
    top.hidden = !path;
  };

  const form = h('form', { class: 'stat', style: { maxWidth: '640px' } },
    h('div', { class: 'form-grid' },
      f('name_ar', t('اسم المدرسة (عربي)'), school?.name_ar, { required: true }),
      f('name_en', t('اسم المدرسة (إنجليزي)'), school?.name_en)),
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
      drawLogo();
    } catch (e) { toastError(e); }
  };

  const logoHost = h('div');
  function drawLogo() {
    if (!school) {
      logoHost.replaceChildren(h('p', { class: 'muted' }, t('احفظ اسم المدرسة أولاً، ثم ارفع الشعار')));
      return;
    }
    const file = h('input', { type: 'file', id: 'logo-file', accept: 'image/png,image/jpeg' });
    file.onchange = async () => {
      if (!file.files[0]) return;
      try {
        const r = await api.upload('/api/school/logo', file.files[0]);
        school = { ...school, logo_path: r.logo_path, version: r.version };
        invalidate('school');
        setLogo(r.logo_path);
        toast(t('تم رفع الشعار'), 'ok');
      } catch (e) { toastError(e); }
      file.value = '';
    };
    const remove = async () => {
      if (!(await confirmBox(t('أتريد حذف الشعار؟')))) return;
      try {
        const r = await api.del('/api/school/logo', school.version);
        school = { ...school, logo_path: null, version: r.version };
        invalidate('school');
        setLogo(null);
      } catch (e) { toastError(e); }
    };
    logoHost.replaceChildren(h('div', { class: 'stat', style: { maxWidth: '640px', marginTop: '14px' } },
      h('h3', {}, t('شعار المدرسة')),
      h('div', { class: 'logo-box' }, preview,
        h('label', { class: 'btn ghost', for: 'logo-file' }, t('اختيار صورة الشعار')), file,
        school.logo_path ? h('button', { class: 'btn ghost', type: 'button', onclick: remove }, t('حذف الشعار')) : null),
      h('p', { class: 'muted', style: { fontSize: '.85rem' } },
        t('صيغة PNG أو JPEG، بحجم لا يتجاوز 1 ميغابايت. يظهر الشعار في رأس الواجهة وفي كل تقرير مطبوع أو مُصدَّر (Excel وPDF).'))));
    file.style.display = 'none';
  }

  put(root, h('h1', { class: 'title' }, t('بيانات المدرسة')), form, logoHost);
  drawLogo();
}
