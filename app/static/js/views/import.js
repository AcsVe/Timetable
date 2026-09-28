// Import from Excel / CSV / aSc Timetables: choose a file, preview exactly what will happen, then confirm.
import * as api from '../api.js';
import { loadTimetables } from '../app.js';
import { lang, t } from '../i18n.js';
import { currentTimetable, invalidate, list, state } from '../store.js';
import { h, jumpTo, nameOf, pageNav, put, swap, toast, toastError } from '../ui.js';

const ENTITIES = [
  ['stages', 'المراحل'], ['grades', 'الصفوف'], ['sections', 'الشعب'], ['divisions', 'التقسيمات'],
  ['groups', 'المجموعات'], ['subjects', 'المباحث'], ['teachers', 'المعلمون'], ['rooms', 'القاعات'],
  ['bell_schedules', 'قوالب التوقيت'], ['lessons', 'الدروس'],
];
const KINDS = [['', 'تحديد تلقائي من العناوين'], ['teachers', 'المعلمون'], ['subjects', 'المباحث'],
               ['rooms', 'القاعات'], ['sections', 'الشعب'], ['lessons', 'الدروس']];
const NEW_STAGE = '__new__';

export async function render(root) {
  const stages = await list('stages');
  const tt = currentTimetable();
  let file = null;
  let key = null;          // one Idempotency-Key per previewed file+options: a double click commits once
  let busy = false;

  const fileInput = h('input', { type: 'file', id: 'import-file', accept: '.xlsx,.xlsm,.csv,.txt,.xml,.roz' });
  const fileName = h('span', { class: 'muted' }, t('لم يُختر ملف'));
  const kindSel = h('select', { id: 'import-kind' }, KINDS.map(([v, l]) => h('option', { value: v }, t(l))));
  const kindRow = h('label', { class: 'inline', hidden: true }, `${t('محتوى ملف CSV')}:`, kindSel);
  const stageSel = h('select', { id: 'import-stage' },
    h('option', { value: '' }, t('تلقائي')),
    stages.map(s => h('option', { value: s.id }, nameOf(s))),
    h('option', { value: NEW_STAGE }, t('مرحلة جديدة…')));
  const stageName = h('input', { id: 'import-stage-name', placeholder: t('اسم المرحلة الجديدة'), hidden: true });
  const ttName = h('input', { id: 'import-tt-name', value: '' });
  const destNew = h('input', { type: 'radio', name: 'dest', value: 'new', checked: true });
  const destCur = h('input', { type: 'radio', name: 'dest', value: 'current', disabled: !tt || tt.status === 'archived' });
  const previewBtn = h('button', { class: 'btn', id: 'import-preview', type: 'button', disabled: true }, t('معاينة'));
  const result = h('div', { id: 'import-result' });

  const reset = () => { key = null; swap(result); };
  fileInput.onchange = () => {
    file = fileInput.files[0] || null;
    fileName.textContent = file ? file.name : t('لم يُختر ملف');
    kindRow.hidden = !(file && /\.(csv|txt)$/i.test(file.name));
    if (file && !ttName.value) ttName.value = `${t('مستورد')}: ${file.name.replace(/\.[^.]+$/, '')}`;
    previewBtn.disabled = !file;
    reset();
  };
  stageSel.onchange = () => { stageName.hidden = stageSel.value !== NEW_STAGE; reset(); };
  for (const el of [kindSel, stageName, ttName, destNew, destCur]) el.addEventListener('change', reset);

  function fields() {
    const f = {};
    if (kindSel.value && !kindRow.hidden) f.kind = kindSel.value;
    if (stageSel.value === NEW_STAGE) { if (stageName.value.trim()) f.stage_name = stageName.value.trim(); }
    else if (stageSel.value) f.stage_id = stageSel.value;
    if (destCur.checked && tt) f.timetable_id = tt.id;
    else {
      f.new_timetable_name = ttName.value.trim() || t('جدول مستورد');
      if (tt) f.term_id = tt.term_id;
    }
    return f;
  }

  async function preview() {
    if (!file || busy) return;
    busy = true; previewBtn.disabled = true;
    swap(result, h('p', { class: 'muted' }, t('جارٍ قراءة الملف…')));
    try {
      const rep = await api.upload('/api/import/preview', file, { fields: fields() });
      key = api.uuid();
      swap(result, renderReport(rep, false));
      jumpTo('import-summary');
    } catch (e) { swap(result); toastError(e); } finally { busy = false; previewBtn.disabled = !file; }
  }
  previewBtn.onclick = preview;

  async function commit(btn) {
    if (!file || busy || !key) return;
    busy = true; btn.disabled = true;
    try {
      const rep = await api.upload('/api/import/commit', file, { key, fields: fields() });
      invalidate();
      if (rep.timetable) {
        state.ttId = rep.timetable.id;
        try { localStorage.setItem('ttId', rep.timetable.id); } catch (_) { /* ignore */ }
      }
      await loadTimetables().catch(() => {});
      swap(result, renderReport(rep, true));
      jumpTo('import-summary');
      toast(t('تم الاستيراد'), 'ok');
    } catch (e) { btn.disabled = false; toastError(e); } finally { busy = false; }
  }

  function renderReport(rep, done) {
    const msg = i => (lang === 'en' ? i.message_en || i.message : i.message);
    const where = i => [i.where, i.row ? `${t('السطر')} ${i.row}` : ''].filter(Boolean).join(' — ');
    const rows = ENTITIES.filter(([k]) => {
      const s = rep.summary[k];
      return s && (s.created || s.updated || s.unchanged);
    }).map(([k, l]) => {
      const s = rep.summary[k];
      const names = rep.created[k] || [];
      return h('tr', {}, h('th', {}, t(l)), h('td', { class: 'num' }, String(s.created)),
        h('td', { class: 'num' }, String(s.updated)), h('td', { class: 'num' }, String(s.unchanged)),
        h('td', { class: 'muted small' }, names.slice(0, 12).join('، ') + (names.length > 12 ? '…' : '')));
    });
    const cards = rep.cards && (rep.cards.placed || rep.cards.unplaced)
      ? h('p', {}, `${t('الحصص الموزعة على الجدول')}: ${rep.cards.placed} — ${t('غير الموزعة')}: ${rep.cards.unplaced}`) : null;
    const ttLine = rep.timetable
      ? h('p', {}, `${rep.timetable.created ? t('جدول جديد') : t('الجدول')}: `, h('strong', {}, rep.timetable.name)) : null;
    const issues = (list_, cls) => h('ul', { class: 'issues' },
      list_.map(i => h('li', { class: cls }, where(i) ? h('span', { class: 'muted' }, `${where(i)}: `) : null, msg(i))));
    const links = [{ id: 'import-summary', label: t('الملخص') }];
    if (rep.error_count) links.push({ id: 'import-errors', label: `${t('أخطاء')} (${rep.error_count})` });
    if (rep.warning_count) links.push({ id: 'import-warnings', label: `${t('تنبيهات')} (${rep.warning_count})` });

    const commitBtn = h('button', { class: 'btn', id: 'import-commit', type: 'button' }, t('تأكيد الاستيراد'));
    commitBtn.onclick = () => commit(commitBtn);
    return h('div', {},
      links.length > 1 ? pageNav(links) : null,
      h('section', { class: 'stat', id: 'import-summary' },
        h('h2', {}, done ? t('تم الاستيراد') : t('معاينة الاستيراد — لم يُحفظ شيء بعد')),
        rows.length ? h('div', { class: 'grid-scroll' }, h('table', { class: 'data' },
          h('thead', {}, h('tr', {}, h('th', {}, ''), h('th', {}, t('جديد')), h('th', {}, t('تحديث')),
            h('th', {}, t('بلا تغيير')), h('th', {}, t('أمثلة من الجديد')))),
          h('tbody', {}, rows))) : h('p', { class: 'muted' }, t('لا توجد بيانات صالحة للاستيراد')),
        ttLine, cards,
        rep.error_count ? h('p', { class: 'form-error' },
          t('الأسطر التي فيها أخطاء لن تُستورد، ويُستورد الباقي. يمكنك تصحيح الملف وإعادة المعاينة.')) : null,
        done
          ? h('div', { class: 'toolbar' }, h('a', { class: 'btn', href: '#/grid' }, t('فتح شبكة الجدول')),
              h('a', { class: 'btn ghost', href: '#/validate' }, t('التحقق')))
          : h('div', { class: 'toolbar' }, commitBtn,
              h('button', { class: 'btn ghost', type: 'button', onclick: reset }, t('إلغاء')))),
      rep.error_count ? h('section', { id: 'import-errors' },
        h('h2', {}, `${t('أخطاء')} (${rep.error_count})`), issues(rep.errors, 'err')) : null,
      rep.warning_count ? h('section', { id: 'import-warnings' },
        h('h2', {}, `${t('تنبيهات')} (${rep.warning_count})`), issues(rep.warnings, 'warn')) : null);
  }

  fileInput.style.display = 'none';
  put(root,
    h('h1', { class: 'title' }, t('الاستيراد')),
    h('div', { class: 'stat', style: { maxWidth: '860px' } },
      h('p', {}, t('استورد المعلمين والمباحث والقاعات والشعب والدروس من ملف Excel أو CSV، أو استورد جدولاً كاملاً من aSc Timetables. تُعرض معاينة أولاً، ولا يُحفظ شيء قبل التأكيد، ولا يتكرر شيء عند إعادة الاستيراد.')),
      h('ul', { class: 'muted small' },
        h('li', {}, t('Excel ‏(‎.xlsx): استخدم القالب الجاهز؛ لكل نوع من البيانات ورقة مستقلة.')),
        h('li', {}, t('CSV: جدول واحد بالعناوين نفسها، ويُقبل الترميز UTF-8 وترميز ويندوز العربي.')),
        h('li', {}, t('aSc Timetables: صدِّر من البرنامج عبر: ملف ← تصدير ← aSc Timetables XML، وارفع ملف ‎.xml. ويُقبل ملف ‎.roz إذا كان بصيغة XML.'))),
      h('a', { class: 'btn ghost', href: '/api/import/template.xlsx', download: '' }, t('تنزيل قالب Excel'))),
    h('div', { class: 'stat', style: { maxWidth: '860px', marginTop: '14px' } },
      h('div', { class: 'toolbar' },
        h('label', { class: 'btn ghost', for: 'import-file' }, t('اختيار ملف')), fileInput, fileName, kindRow),
      h('div', { class: 'toolbar' },
        h('label', { class: 'inline' }, `${t('المرحلة للشعب التي لم تُحدَّد مرحلتها')}:`, stageSel), stageName),
      h('fieldset', { class: 'plain' },
        h('legend', {}, t('الدروس والحصص تُستورد إلى')),
        h('label', { class: 'inline' }, destNew, t('جدول جديد باسم'), ttName),
        h('label', { class: 'inline' }, destCur,
          tt ? `${t('الجدول المعروض حالياً')}: ${tt.name}` : t('الجدول المعروض حالياً'))),
      h('div', { class: 'toolbar' }, previewBtn)),
    result);
}
