"""استرجاع نسخة احتياطية (أوقف النظام قبلها — ملفات .bat وأزرار الهاتف تفعل ذلك تلقائياً).

    python ops/restore.py --latest auto --yes                # أحدث نسخة في BACKUP_DIR
    python ops/restore.py --latest auto --tag phone --yes    # أحدث نسخة رفعها الهاتف
    python ops/restore.py --latest DIR --yes                 # من مجلد آخر
    python ops/restore.py --file PATH.sql.gz --yes

• قبل الاستبدال تُحفظ القاعدة الحالية في data/before-restore-<وقت>.sql.gz (آخر 5).
• الاسترجاع كله في معاملة واحدة: إن فشل لا يتغيّر شيء.
• --since-marker: مع --tag phone يرفض نسخة الهاتف إن كانت أقدم من وقت تشغيل الطوارئ (لم تُرفع بعد).
"""
import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pgtools  # noqa: E402
from common import SITE, backup_root, data_dir, die, load_env, stamp, t  # noqa: E402

PREFIX = len(SITE) + 1      # timetable-YYYY-MM-DD_HHMMSS…


def file_stamp(path):
    return os.path.basename(path)[PREFIX:PREFIX + 17]


def pick(root, tag):
    files = glob.glob(os.path.join(root, 'db', f'{SITE}-*.sql.gz'))
    if tag == 'phone':
        files = [f for f in files if f.endswith('-phone.sql.gz')]
    files.sort(key=file_stamp)
    return files[-1] if files else None


def main():
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument('--latest', default='')
    ap.add_argument('--file', default='')
    ap.add_argument('--tag', default='')
    ap.add_argument('--since-marker', action='store_true')
    ap.add_argument('--yes', action='store_true')
    a = ap.parse_args()
    root = backup_root() if a.latest in ('', 'auto') else a.latest
    src = a.file or pick(root, a.tag)
    if not src or not os.path.isfile(src):
        die(t(f'لا توجد نسخة احتياطية في {root}/db', f'No backup found in {root}/db'))
    if a.since_marker:
        mk = os.path.join(root, 'db', 'ACTIVE_SITE.txt')
        if os.path.isfile(mk):
            parts = open(mk, encoding='utf-8', errors='ignore').read().split()
            if len(parts) >= 2 and parts[0] == 'phone' and file_stamp(src) < parts[1]:
                die(t(f'نسخة الهاتف ({file_stamp(src)}) أقدم من بدء الطوارئ ({parts[1]}) — ارفع بيانات الهاتف أولاً (زر TT 5) وانتظر مزامنة Drive دقيقة',
                      f'The phone backup ({file_stamp(src)}) is older than the emergency start ({parts[1]}) - upload the phone data first (TT 5) and wait a minute for Drive'))
    print(t(f'النسخة: {src}', f'Backup: {src}'))
    if not a.yes and input(t('ستُستبدل كل بيانات هذا الجهاز. اكتب YES: ', 'All data on this device will be replaced. Type YES: ')).strip() != 'YES':
        die(t('تم الإلغاء', 'Cancelled'))

    url = pgtools.db_url()
    pgtools.ensure_database(url)
    os.makedirs(data_dir(), exist_ok=True)
    n, _rev = pgtools.check(url)
    if n:
        safe = os.path.join(data_dir(), f'before-restore-{stamp()}.sql.gz')
        pgtools.dump(url, safe)
        for old in sorted(glob.glob(os.path.join(data_dir(), 'before-restore-*.sql.gz')))[:-5]:
            os.remove(old)
        print(t(f'✓ نسخة أمان من البيانات السابقة: {safe}', f'✓ Safety copy of the previous data: {safe}'))
    pgtools.restore(url, src)
    n, rev = pgtools.check(url)
    if not n:
        die(t('النسخة فارغة — راجع الملف', 'The backup is empty - check the file'))
    print(t(f'✓ استُرجعت القاعدة (عدد الجداول: {n}، الترحيل {rev})', f'✓ Database restored ({n} tables, migration {rev})'))


if __name__ == '__main__':
    main()
