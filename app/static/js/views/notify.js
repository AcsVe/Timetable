// One dialog for every "notify the teachers" action (cover, invigilation, duties):
// preview each teacher's message, choose e-mail (Microsoft 365) and/or in-app, send, then see who was reached.
import * as api from '../api.js';
import { t } from '../i18n.js';
import { isAdmin } from '../store.js';
import { h, put, toast, toastError } from '../ui.js';

let status = null;
export async function mailStatus() {
  if (status === null) status = await api.get('/api/mail/status').then(r => r.configured).catch(() => false);
  return status;
}
export function resetMailStatus() { status = null; }

const STATUS = { sent: ['أُرسل بالبريد', 'ok'], failed: ['فشل الإرسال', 'err'], no_email: ['لا يوجد بريد', 'warn'],
                 disabled: ['البريد غير مُعَدّ', 'warn'] };

/**
 * title: dialog title; messages: [{teacher_id, name, text, email?, phone?}];
 * send(body) → API result {results, sent, failed, no_email, in_app}; body = {email, in_app, teacher_ids}
 */
export async function notifyDialog({ title, messages, send, canSend = true }) {
  const configured = await mailStatus();
  const dlg = document.getElementById('modal');
  const form = document.getElementById('modal-form');
  form.innerHTML = '';
  const chosen = new Set(messages.map(m => m.teacher_id));
  const byEmail = h('input', { type: 'checkbox', id: 'notify-email', checked: configured, disabled: !configured });
  const inApp = h('input', { type: 'checkbox', id: 'notify-inapp', checked: true });
  const results = new Map();
  const copy = async text => { try { await navigator.clipboard.writeText(text); toast(t('نُسخ النص'), 'ok'); } catch (_) { toast(t('تعذّر النسخ؛ حدِّد النص وانسخه يدوياً'), 'err'); } };
  const wa = p => { const d = String(p || '').replace(/\D/g, '').replace(/^0/, '962'); return d.length >= 9 ? d : null; };
  const list = h('div');
  function drawList() {
    list.replaceChildren(...messages.map(m => {
      const r = results.get(m.teacher_id);
      const st = r && r.email_status && STATUS[r.email_status];
      return h('div', { class: 'msg-card' },
        h('div', { class: 'toolbar' },
          canSend ? h('input', { type: 'checkbox', checked: chosen.has(m.teacher_id), 'aria-label': `${t('تحديد')} — ${m.name}`,
            onchange: e => { e.target.checked ? chosen.add(m.teacher_id) : chosen.delete(m.teacher_id); } }) : null,
          h('b', {}, m.name),
          h('button', { type: 'button', class: 'btn small ghost', onclick: () => copy(m.text) }, t('نسخ')),
          wa(m.phone) ? h('a', { class: 'btn small ghost', target: '_blank', rel: 'noopener', href: `https://wa.me/${wa(m.phone)}?text=${encodeURIComponent(m.text)}` }, t('واتساب')) : null,
          st ? h('span', { class: `chip ${st[1]}`, title: r.error || '' }, t(st[0])) : null,
          r && r.in_app ? h('span', { class: 'chip ok' }, t('إشعار داخل النظام')) : null),
        r && r.error ? h('div', { class: 'reasons small' }, r.error) : null,
        h('pre', { class: 'msg-text', dir: 'auto' }, m.text));
    }));
  }
  drawList();
  const summary = h('p', { class: 'muted' });
  const sendBtn = h('button', { class: 'btn', type: 'button', id: 'notify-send', onclick: async () => {
    if (!chosen.size) { toast(t('اختر معلماً واحداً على الأقل'), 'err'); return; }
    sendBtn.disabled = true;
    try {
      const r = await send({ email: byEmail.checked, in_app: inApp.checked, teacher_ids: [...chosen] });
      for (const x of r.results) results.set(x.teacher_id, x);
      summary.textContent = `${t('أُرسل بالبريد')}: ${r.sent} — ${t('فشل الإرسال')}: ${r.failed} — ${t('لا يوجد بريد')}: ${r.no_email} — ${t('إشعار داخل النظام')}: ${r.in_app}`;
      summary.className = r.failed ? 'reasons' : 'muted';
      toast(t('تم الإبلاغ'), r.failed ? 'err' : 'ok');
      drawList();
    } catch (e) { toastError(e); } finally { sendBtn.disabled = false; }
  } }, t('إرسال'));
  put(form, h('h2', {}, title),
    messages.length ? null : h('p', { class: 'muted' }, t('لا يوجد معلمون لإبلاغهم')),
    canSend && messages.length ? h('div', { class: 'toolbar' },
      h('label', { class: 'inline' }, byEmail, t('بالبريد الإلكتروني (Microsoft 365)')),
      h('label', { class: 'inline' }, inApp, t('إشعار داخل النظام لمن له حساب')),
      configured ? null : h('span', { class: 'muted small' }, t('البريد غير مُعَدّ بعد.'), ' ',
        isAdmin() ? h('a', { href: '#/mail', onclick: () => dlg.close() }, t('إعدادات البريد')) : null)) : null,
    list, summary,
    h('div', { class: 'modal-actions' }, h('button', { class: 'btn ghost', type: 'button', onclick: () => dlg.close() }, t('إغلاق')),
      canSend && messages.length ? sendBtn : null));
  dlg.onclose = null;
  dlg.showModal();
}
