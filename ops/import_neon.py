"""نقل كل البيانات من قاعدة Neon (التي يعمل عليها Render الآن) إلى قاعدة هذا الجهاز — مرة واحدة.

    python ops/import_neon.py            # يطلب رابط Neon (لا يظهر أثناء اللصق)
    python ops/import_neon.py --yes      # بلا سؤال تأكيد

• الرابط من Render ← الخدمة timetable ← Environment ← DATABASE_URL (يبدأ بـ postgresql://).
• يستبدل بيانات هذا الجهاز بالكامل (وتُحفظ نسخة أمان منها في data أولاً).
• Neon لا يتغيّر: النقل قراءة فقط.
"""
import getpass
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pgtools  # noqa: E402
from common import data_dir, die, load_env, stamp, t  # noqa: E402


def main():
    load_env()
    url = os.environ.get('NEON_DATABASE_URL', '').strip() or getpass.getpass(
        t('  الصق رابط Neon (DATABASE_URL من Render) ثم Enter: ', '  Paste the Neon link (DATABASE_URL from Render), then Enter: ')).strip()
    url = ''.join(ch for ch in url if ch.isprintable()).strip()
    if not url:
        die(t('تم الإلغاء', 'Cancelled'))
    if '://' not in url:
        die(t('الرابط لم يُلصق صحيحاً. في PowerShell أو CMD الصق بزر الفأرة الأيمن — لا يظهر شيء أثناء اللصق، ثم Enter',
              'The link was not pasted correctly. In PowerShell/CMD paste with a right-click - nothing shows while pasting - then Enter'))
    if '--yes' not in sys.argv and input(t('  ستُستبدل بيانات هذا الجهاز ببيانات Neon. اكتب YES: ',
                                           '  The data on this device will be replaced by Neon. Type YES: ')).strip() != 'YES':
        die(t('تم الإلغاء', 'Cancelled'))
    local = pgtools.db_url()
    pgtools.ensure_database(local)
    print(t('  تحميل البيانات من Neon…', '  Downloading the data from Neon...'))
    with tempfile.TemporaryDirectory() as tmpd:
        gz = os.path.join(tmpd, 'neon.sql.gz')
        pgtools.dump(url, gz)
        n, _ = pgtools.check(local)
        if n:
            os.makedirs(data_dir(), exist_ok=True)
            safe = os.path.join(data_dir(), f'before-neon-import-{stamp()}.sql.gz')
            pgtools.dump(local, safe)
            print(t(f'  ✓ نسخة أمان من بيانات هذا الجهاز: {safe}', f'  ✓ Safety copy of this device: {safe}'))
        pgtools.restore(local, gz)
    n, rev = pgtools.check(local)
    print(t(f'\n  ✅ نُقلت البيانات إلى هذا الجهاز (عدد الجداول: {n}، الترحيل {rev}).',
            f'\n  ✅ The data is on this device now ({n} tables, migration {rev}).'))


if __name__ == '__main__':
    main()
