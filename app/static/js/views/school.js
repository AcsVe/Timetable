// School settings: names, logo (the system icon until one is uploaded), and the e-mail (Microsoft Graph) status.
import * as api from '../api.js';
import { t } from '../i18n.js';
import { invalidate, state } from '../store.js';
import { confirmBox, h, put, toast, toastError } from '../ui.js';
import { drawBrand } from '../app.js';
import { graphStatus } from './mail.js';

const SYSTEM_ICON = '/static/brand/system.svg';

export async function render(root) {
  const items = (await api.get('/api/school')).items;
  let school = items[0] || null;
  const f = (name, label, v, extra = {}) => h('div', { class: 'field' }, h('label', { for: `s-${name}` }, label),
    h('input', { id: `s-${name}`, name, value: v ?? '', ...extra }));

  const preview = h('img', { id: 'logo-preview', alt: t('معاينة شعار المدرسة') });
  const remove = h('input', { type: 'checkbox', id: 'logo-remove', name: 'remove_logo' });
  const removeBox = h('label', { class: 'inline', for: 'logo-remove' }, remove, t('إزالة الشعار'));
  const file = h('input', { type: 'file', id: 'logo-file', accept: 'image/png,image/jpeg', hidden: true });
  const pickBtn = h('label', { class: 'btn ghost', for: 'logo-file' }, h('i', { class: 'fa-solid fa-upload', 'aria-hidden': 'true' }),
    t('اختيار صورة الشعار'));
  const logoNote = h('p', { class: 'hint' });

  function drawLogo() {
    const logo = school && school.logo_path;
    preview.src = logo || SYSTEM_ICON;
    preview.classList.toggle('sys-icon', !logo);
    remove.checked = false;
    removeBox.hidden = !logo;
    pickBtn.hidden = !school;
    logoNote.textContent = !school ? t('احفظ اسم المدرسة أولاً، ثم ارفع الشعار')
      : logo ? t('صيغة PNG أو JPEG، بحجم لا يتجاوز 1 ميغابايت. يظهر الشعار في القائمة الجانبية وصفحة الدخول وفي كل تقرير مطبوع أو مُصدَّر (Excel وPDF).')
        : t('إلى أن يُرفع شعار تظهر أيقونة النظام.');
  }
  function refreshShell() {
    state.school = school;
    invalidate('school');
    drawBrand();
  }

  file.onchange = async () => {
    if (!file.files[0]) return;
    try {
      const r = await api.upload('/api/school/logo', file.files[0]);
      school = { ...school, logo_path: r.logo_path, version: r.version };
      refreshShell();
      drawLogo();
      toast(t('تم رفع الشعار'), 'ok');
    } catch (e) { toastError(e); }
    file.value = '';
  };

  const form = h('form', { class: 'card', id: 'school-form' },
    h('h2', {}, h('i', { class: 'fa-solid fa-school', 'aria-hidden': 'true' }), t('هوية المدرسة')),
    h('div', { class: 'form-grid' },
      f('name_ar', t('اسم المدرسة (عربي)'), school?.name_ar, { required: true }),
      f('name_en', t('اسم المدرسة (إنجليزي)'), school?.name_en, { dir: 'ltr' }),
      h('div', { class: 'field full' }, h('label', {}, t('شعار المدرسة')),
        h('div', { class: 'logo-pick' }, preview, h('div', {}, pickBtn, file, removeBox)), logoNote)),
    h('div', { class: 'modal-actions' }, h('button', { class: 'btn', type: 'submit' },
      h('i', { class: 'fa-solid fa-floppy-disk', 'aria-hidden': 'true' }), t('حفظ'))));
  form.onsubmit = async ev => {
    ev.preventDefault();
    const body = {};
    for (const k of ['name_ar', 'name_en']) body[k] = form.elements[k].value.trim() || null;
    try {
      if (remove.checked && school?.logo_path) {
        if (!(await confirmBox(t('أتريد حذف الشعار؟')))) return;
        const r = await api.del('/api/school/logo', school.version);
        school = { ...school, logo_path: null, version: r.version };
      }
      school = school ? await api.patch(`/api/school/${school.id}`, { ...body, version: school.version })
                      : await api.post('/api/school', body);
      refreshShell();
      drawLogo();
      toast(t('تم الحفظ'), 'ok');
    } catch (e) { toastError(e); }
  };

  const mailCard = h('section', { class: 'card', id: 'graph-card' },
    h('h2', {}, h('i', { class: 'fa-solid fa-envelope', 'aria-hidden': 'true' }), t('البريد')));
  try {
    const s = await api.get('/api/mail/settings');
    mailCard.append(graphStatus(s), h('div', { class: 'modal-actions' },
      h('a', { class: 'btn ghost', href: '#/mail' }, h('i', { class: 'fa-solid fa-gear', 'aria-hidden': 'true' }), t('إعداد البريد'))));
  } catch (_) {
    mailCard.append(h('p', { class: 'muted' }, t('تعذّر تحميل حالة البريد')));
  }

  put(root, h('h1', { class: 'title' }, t('بيانات المدرسة')), form, mailCard);
  drawLogo();
}
