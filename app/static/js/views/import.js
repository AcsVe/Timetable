// Import from Excel / CSV / aSc Timetables: choose a file, preview exactly what will happen, then confirm.
import * as api from '../api.js';
import { loadTimetables } from '../app.js';
import { lang, t } from '../i18n.js';
import { currentTimetable, invalidate, list, state } from '../store.js';
import { confirmBox, h, jumpTo, nameOf, pageNav, put, swap, toast, toastError } from '../ui.js';

const ENTITIES = [
  ['stages', 'المراحل'], ['grades', 'الصفوف'], ['sections', 'الشعب'], ['divisions', 'التقسيمات'],
  ['groups', 'المجموعات'], ['subjects', 'المباحث'], ['teachers', 'المعلمون'], ['rooms', 'القاعات'],
  ['bell_schedules', 'قوالب التوقيت'], ['bell_assignments', 'إسناد التوقيت للأيام والصفوف'], ['lessons', 'الدروس'],
];
const KINDS = [['', 'تحديد تلقائي من العناوين'], ['teachers', 'المعلمون'], ['subjects', 'المباحث'],
               ['rooms', 'القاعات'], ['sections', 'الشعب'], ['lessons', 'الدروس']];
const NEW_STAGE = '__new__';

export async function render(root) {
  const stages = await list('stages');
  const tt = currentTimetable();
  let files = [];
  let key = null;          // one Idempotency-Key per previewed file+options: a double click commits once
  let busy = false;

  const fileInput = h('input', { type: 'file', id: 'import-file', multiple: true, accept: '.xlsx,.xlsm,.csv,.txt,.xml,.roz' });
  const replaceAll = h('input', { type: 'checkbox', id: 'import-replace' });
  const fileName = h('span', { class: 'drop-name' }, t('لم يُختر ملف'));
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
  const previewBtn = h('button', { class: 'btn big', id: 'import-preview', type: 'button', disabled: true }, t('معاينة'));
  const result = h('div', { id: 'import-result' });

  const reset = () => { key = null; swap(result); };
  fileInput.onchange = () => {
    files = [...fileInput.files].slice(0, 5);
    fileName.textContent = files.length ? files.map(f => f.name).join('، ') : t('لم يُختر ملف');
    kindRow.hidden = !files.some(f => /\.(csv|txt)$/i.test(f.name));
    const main = files.find(f => /\.(xml|roz)$/i.test(f.name)) || files[0];
    if (main && !ttName.value) ttName.value = `${t('مستورد')}: ${main.name.replace(/\.[^.]+$/, '')}`;
    previewBtn.disabled = !files.length;
    reset();
  };
  replaceAll.addEventListener('change', () => { replaceBox.classList.toggle('on', replaceAll.checked); reset(); });
  stageSel.onchange = () => { stageName.hidden = stageSel.value !== NEW_STAGE; reset(); };
  for (const el of [kindSel, stageName, ttName, destNew, destCur]) el.addEventListener('change', reset);

  function fields() {
    const f = {};
    if (replaceAll.checked) f.replace_all = '1';
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
    if (!files.length || busy) return;
    busy = true; previewBtn.disabled = true;
    swap(result, h('p', { class: 'muted' }, t('جارٍ قراءة الملف…')));
    try {
      const rep = await api.upload('/api/import/preview', files, { fields: fields() });
      key = api.uuid();
      swap(result, renderReport(rep, false));
      jumpTo('import-summary');
    } catch (e) { swap(result); toastError(e); } finally { busy = false; previewBtn.disabled = !files.length; }
  }
  previewBtn.onclick = preview;

  async function commit(btn) {
    if (!files.length || busy || !key) return;
    if (replaceAll.checked && !(await confirmBox(t('سيُحذف كل ما في النظام من بيانات (المعلمون والمباحث والشعب والجداول والتوقيت) ويُستبدل بما في الملف. لا يمكن التراجع. أتريد المتابعة؟')))) return;
    busy = true; btn.disabled = true;
    try {
      const rep = await api.upload('/api/import/commit', files, { key, fields: fields() });
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

    const wipedLine = rep.wiped ? h('p', { class: 'form-error' },
      `${done ? t('حُذفت البيانات السابقة') : t('ستُحذف البيانات الحالية أولاً')}: `
      + ENTITIES.filter(([k]) => rep.wiped[k]).map(([k, l]) => `${t(l)} ${rep.wiped[k]}`).concat(
        rep.wiped.timetables ? [`${t('الجداول')} ${rep.wiped.timetables}`] : []).join('، ')) : null;
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
        wipedLine, ttLine, cards,
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
  // Drag & drop onto the big file box (desktop); a tap opens the file picker (phone).
  const drop = h('label', { class: 'dropzone', for: 'import-file' },
    h('span', { class: 'drop-icon', 'aria-hidden': 'true' }, '⇪'),
    h('strong', {}, t('اضغط هنا لاختيار الملف')),
    h('span', { class: 'muted small' }, t('ملف aSc ‏(‎.xml) أو Excel ‏(‎.xlsx) أو CSV')),
    fileName);
  drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', e => {
    e.preventDefault(); drop.classList.remove('over');
    if (e.dataTransfer.files[0]) { fileInput.files = e.dataTransfer.files; fileInput.dispatchEvent(new Event('change')); }
  });

  const replaceBox = h('label', { class: 'replace-box', for: 'import-replace' }, replaceAll,
    h('span', {}, h('strong', {}, t('البدء من جديد: حذف كل البيانات الحالية قبل الاستيراد')),
      h('span', { class: 'small' }, t('يُبقي المستخدمين واسم المدرسة وشعارها وأيام الأسبوع فقط. استخدمه لاستيراد ملف aSc جديد بدل القديم.'))));
  const stepHead = (n, text) => h('h2', { class: 'step-head' }, h('span', { class: 'step-mark' }, String(n)), text);
  put(root,
    h('h1', { class: 'title' }, t('الاستيراد')),
    h('div', { class: 'stat import-box' },
      stepHead(1, t('اختر الملف')), drop, fileInput, kindRow,
      h('p', { class: 'muted small' }, t('يمكن اختيار أكثر من ملف معاً، مثل ملف aSc ‏(‎.xml) مع ملف Excel لتوقيت الحصص.')),
      replaceBox,
      stepHead(2, t('اضغط «معاينة» لترى ما سيُضاف قبل الحفظ')),
      h('div', { class: 'toolbar' }, previewBtn),
      stepHead(3, t('راجع المعاينة ثم اضغط «تأكيد الاستيراد»')),
      h('details', { class: 'more' },
        h('summary', {}, t('خيارات إضافية (اختيارية)')),
        h('div', { class: 'toolbar' },
          h('label', { class: 'inline' }, `${t('المرحلة للشعب التي لم تُحدَّد مرحلتها')}:`, stageSel), stageName),
        h('fieldset', { class: 'plain' },
          h('legend', {}, t('الدروس والحصص تُستورد إلى')),
          h('label', { class: 'inline' }, destNew, t('جدول جديد باسم'), ttName),
          h('label', { class: 'inline' }, destCur,
            tt ? `${t('الجدول المعروض حالياً')}: ${tt.name}` : t('الجدول المعروض حالياً')))),
      h('details', { class: 'more' },
        h('summary', {}, t('من أين أحصل على الملف؟')),
        h('ul', { class: 'small' },
          h('li', {}, t('aSc Timetables: صدِّر من البرنامج عبر: ملف ← تصدير ← aSc Timetables XML، وارفع ملف ‎.xml. ويُقبل ملف ‎.roz إذا كان بصيغة XML.')),
          h('li', {}, t('Excel ‏(‎.xlsx): استخدم القالب الجاهز؛ لكل نوع من البيانات ورقة مستقلة.')),
          h('li', {}, t('CSV: جدول واحد بالعناوين نفسها، ويُقبل الترميز UTF-8 وترميز ويندوز العربي.'))),
        h('a', { class: 'btn ghost small', href: '/api/import/template.xlsx', download: '' }, t('تنزيل قالب Excel')))),
    result);
}
