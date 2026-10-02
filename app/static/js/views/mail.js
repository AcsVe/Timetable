// E-mail through the school's Microsoft 365 (Microsoft Graph, app registration with a client secret).
import * as api from '../api.js';
import { t } from '../i18n.js';
import { isAdmin, state } from '../store.js';
import { bulkTable, h, put, searchBox, swap, toast, toastError } from '../ui.js';
import { resetMailStatus } from './notify.js';

export async function render(root) {
  if (!isAdmin()) { put(root, h('p', {}, t('هذه الصفحة لمدير النظام فقط'))); return; }
  let s = await api.get('/api/mail/settings');
  const statusHost = h('div');
  const logHost = h('div');
  let logTable = null;

  const input = (name, attrs = {}) => h('input', { id: `mail-${name}`, name, value: s[name] || '', autocomplete: 'off',
    disabled: s.source?.[name] === 'env', dir: 'ltr', ...attrs });
  const fTenant = input('tenant_id', { placeholder: 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx', 'aria-label': t('معرّف المستأجر (Tenant ID)') });
  const fClient = input('client_id', { placeholder: 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx', 'aria-label': t('معرّف التطبيق (Client ID)') });
  const fSecret = h('input', { id: 'mail-client_secret', type: 'password', autocomplete: 'new-password', dir: 'ltr',
    disabled: s.source?.client_secret === 'env', 'aria-label': t('سر التطبيق (Client secret)'),
    placeholder: s.has_secret ? t('محفوظ — اكتب سراً جديداً لاستبداله') : t('الصق قيمة السر (Value) لا معرّفه') });
  const fSender = input('sender', { type: 'email', placeholder: 'timetable@school.edu.jo', 'aria-label': t('بريد المرسل') });
  const fEnabled = h('input', { type: 'checkbox', id: 'mail-enabled', checked: s.enabled });
  const fTo = h('input', { id: 'mail-test-to', type: 'email', dir: 'ltr', value: state.me?.email || '', placeholder: 'name@school.edu.jo',
    'aria-label': t('أرسل رسالة التجربة إلى') });

  function drawStatus() {
    swap(statusHost, s.configured
      ? h('p', { class: 'notice ok' }, `${t('البريد مُعَدّ ومفعّل؛ تُرسل الرسائل من')} ${s.sender}`)
      : h('p', { class: 'notice warn' }, t('البريد غير مُعَدّ بعد: أكمل الحقول ثم احفظ وجرّب الإرسال.')),
      Object.values(s.source || {}).includes('env')
        ? h('p', { class: 'muted small' }, t('بعض القيم مأخوذة من متغيرات البيئة على الخادم (MS_TENANT_ID، MS_CLIENT_ID، MS_CLIENT_SECRET، MS_MAIL_SENDER) ولا تُعدَّل من هنا.')) : null);
  }
  const field = (label, el, help) => h('div', { class: 'field' }, h('label', { for: el.id }, label), el,
    help ? h('div', { class: 'muted small' }, help) : null);

  async function save() {
    try {
      const body = { tenant_id: fTenant.value, client_id: fClient.value, sender: fSender.value,
                     enabled: fEnabled.checked };
      if (fSecret.value) body.client_secret = fSecret.value;
      s = await api.put('/api/mail/settings', body);
      fSecret.value = '';
      fSecret.placeholder = s.has_secret ? t('محفوظ — اكتب سراً جديداً لاستبداله') : t('الصق قيمة السر (Value) لا معرّفه');
      resetMailStatus();
      drawStatus();
      toast(t('تم الحفظ'), 'ok');
    } catch (e) { toastError(e); }
  }
  async function test() {
    try {
      const r = await api.post('/api/mail/test', { to: fTo.value });
      if (r.ok) toast(`${t('أُرسلت رسالة التجربة إلى')} ${r.to}`, 'ok');
      else toast(r.error, 'err');
      loadLog();
    } catch (e) { toastError(e); }
  }
  const STATUS = { sent: [t('أُرسل'), 'ok'], failed: [t('فشل'), 'err'] };
  const KIND = { cover: 'حصص الإشغال', exams: 'المراقبة', duties: 'المناوبة', test: 'تجربة' };
  async function loadLog() {
    const r = await api.get('/api/mail/log');
    logTable = bulkTable({
      items: r.items, text: x => [x.to, x.name, x.subject, x.error, t(KIND[x.kind] || x.kind)].join(' '),
      columns: [
        { label: t('الوقت'), get: x => h('span', { dir: 'ltr' }, x.at.slice(0, 16).replace('T', ' ')) },
        { label: t('إلى'), get: x => [x.name ? h('div', {}, x.name) : null, h('span', { class: 'muted small', dir: 'ltr' }, x.to)] },
        { label: t('الموضوع'), get: x => x.subject },
        { label: t('النوع'), get: x => t(KIND[x.kind] || x.kind) },
        { label: t('الحالة'), get: x => [h('span', { class: `chip ${STATUS[x.status][1]}` }, STATUS[x.status][0]),
                                        x.error ? h('div', { class: 'reasons small' }, x.error) : null] },
      ],
      emptyText: t('لم تُرسل أي رسالة بعد'),
    });
    swap(logHost, logTable.el);
  }

  put(root, h('h1', { class: 'title' }, t('البريد عبر Microsoft 365')),
    h('p', { class: 'muted' }, t('تُرسل الإشعارات (حصص الإشغال، والمراقبة على الامتحانات، والمناوبة) إلى بريد المعلمين من حساب مدرسي عبر Microsoft Graph.')),
    statusHost,
    h('section', { class: 'stat' },
      h('div', { class: 'form-grid' },
        field(t('معرّف المستأجر (Tenant ID)'), fTenant, t('من Microsoft Entra ← نظرة عامة ← Tenant ID')),
        field(t('معرّف التطبيق (Client ID)'), fClient, t('Application (client) ID للتطبيق المسجَّل')),
        field(t('سر التطبيق (Client secret)'), fSecret, t('لا يُعرض السر بعد حفظه، ويُحفظ في الخادم فقط')),
        field(t('بريد المرسل'), fSender, t('صندوق بريد حقيقي في المستأجر، مثل حساب مشترك للنظام')),
        h('div', { class: 'field' }, h('label', { class: 'inline', for: 'mail-enabled' }, fEnabled, t('تفعيل الإرسال بالبريد')))),
      h('div', { class: 'toolbar' }, h('button', { class: 'btn', id: 'mail-save', onclick: save }, t('حفظ الإعدادات')),
        h('label', { class: 'inline grow' }, `${t('أرسل رسالة التجربة إلى')}:`, fTo),
        h('button', { class: 'btn ghost', id: 'mail-test', onclick: test }, t('إرسال رسالة تجربة')))),
    h('details', { class: 'more' }, h('summary', {}, t('خطوات الإعداد في Microsoft Entra (مرة واحدة)')),
      h('ol', { class: 'small' },
        h('li', {}, t('ادخل إلى entra.microsoft.com بحساب مسؤول ← التطبيقات ← تسجيلات التطبيقات ← تسجيل جديد (حساب في هذا الدليل فقط).')),
        h('li', {}, t('انسخ «معرّف التطبيق» و«معرّف الدليل (المستأجر)» من صفحة النظرة العامة.')),
        h('li', {}, t('الشهادات والأسرار ← سر عميل جديد، وانسخ «القيمة» فوراً (لا تظهر مرة أخرى). ودوِّن تاريخ انتهائه لتجدده قبله.')),
        h('li', {}, t('أذونات واجهة البرمجة ← إضافة إذن ← Microsoft Graph ← أذونات التطبيق ← Mail.Send، ثم «منح موافقة المسؤول».')),
        h('li', {}, t('يُنصح بحصر التطبيق في صندوق المرسل فقط عبر سياسة الوصول في Exchange Online (New-ApplicationAccessPolicy).')),
        h('li', {}, t('أدخل القيم هنا ثم احفظ وأرسل رسالة تجربة. ويمكن بدلاً من ذلك وضعها في متغيرات البيئة على الخادم.')))),
    h('h2', { class: 'section-title' }, t('سجل الرسائل')),
    h('div', { class: 'toolbar' }, searchBox(v => logTable && logTable.setQuery(v), t('ابحث بالاسم أو البريد أو الموضوع…'))),
    logHost);
  drawStatus();
  await loadLog();
}
