"""نسخة احتياطية: قاعدة البيانات (PostgreSQL) + نسخة من الكود.

    python ops/backup.py                 # إلى BACKUP_DIR (مجلد Google Drive) أو backups
    python ops/backup.py --tag phone     # من الهاتف (اسم الملف ينتهي بـ -phone)
    python ops/backup.py --dir PATH --no-code

• القاعدة: BACKUP_DIR/db/timetable-<وقت>.sql.gz  (آخر 48 نسخة من كل نوع)
  وفيها كل شيء: البيانات والشعار والإعدادات ومفاتيح التنبيهات (لا ملفات مرفقة خارج القاعدة).
• الكود: BACKUP_DIR/code/timetable-code.zip  (لتحديث الهاتف دون GitHub — بلا .env ولا بيانات)
• نسخة ثانية في Neon إن كان NEON_BACKUP_URL في .env (فقط إذا تغيّرت البيانات).
"""
import argparse
import glob
import os
import shutil
import sys
import tempfile
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pgtools  # noqa: E402
from common import BASE, SITE, backup_root, load_env, stamp, t  # noqa: E402


def _to_dest(local_file, dest_file):
    """نسخ ملف جاهز إلى مجلد النسخ مرة واحدة. Google Drive يقفل الملفات الجديدة فوراً للمزامنة،
    لذلك لا تُنشأ ملفات مؤقتة داخله — وعند الانشغال تُعاد المحاولة."""
    for attempt in range(6):
        try:
            shutil.copyfile(local_file, dest_file)
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(5)


def _neon_push(gz):
    try:
        import neon_store
        if neon_store._url():
            neon_store.push(gz)
    except BaseException as e:   # noqa: BLE001 (SystemExit من neon_store أيضاً) — لا تُفشل النسخ
        print(t(f'⚠ Neon: تعذّر الرفع ({e})', f'⚠ Neon: upload failed ({e})'))


def backup_db(dest_dir, tag, keep):
    os.makedirs(dest_dir, exist_ok=True)
    name = f'{SITE}-{stamp()}{"-" + tag if tag else ""}.sql.gz'
    final = os.path.join(dest_dir, name)
    with tempfile.TemporaryDirectory() as tmpd:
        gz = os.path.join(tmpd, name)
        pgtools.dump(pgtools.db_url(), gz)
        _to_dest(gz, final)
        _neon_push(gz)
    pattern = f'{SITE}-*-phone.sql.gz' if tag == 'phone' else f'{SITE}-*.sql.gz'
    files = sorted(f for f in glob.glob(os.path.join(dest_dir, pattern)) if tag == 'phone' or not f.endswith('-phone.sql.gz'))
    for old in files[:-keep] if keep > 0 else []:
        try:
            os.remove(old)
        except OSError:
            pass
    return final


def code_zip(dest_dir):
    os.makedirs(dest_dir, exist_ok=True)
    skip_dirs = {'.git', 'venv', '.venv', 'data', 'backups', 'logs', '__pycache__', '.pytest_cache', 'node_modules'}
    tmpd = tempfile.mkdtemp()
    local = os.path.join(tmpd, f'{SITE}-code.zip')
    with zipfile.ZipFile(local, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(BASE):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for f in files:
                if f in ('.env', 'pyexe.txt') or f.endswith('.pyc'):
                    continue
                full = os.path.join(root, f)
                arc = os.path.join(SITE, os.path.relpath(full, BASE))
                if f.endswith('.sh'):   # الهاتف يحتاج نهايات أسطر LF
                    z.writestr(arc, open(full, 'rb').read().replace(b'\r\n', b'\n'))
                else:
                    z.write(full, arc)
    _to_dest(local, os.path.join(dest_dir, f'{SITE}-code.zip'))
    shutil.rmtree(tmpd, ignore_errors=True)


def main():
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default='')
    ap.add_argument('--tag', default='')
    ap.add_argument('--keep', type=int, default=48)
    ap.add_argument('--no-code', action='store_true')
    a = ap.parse_args()
    root = a.dir or backup_root()
    f = backup_db(os.path.join(root, 'db'), a.tag, a.keep)
    print(t('✓ القاعدة: ', '✓ Database: ') + f)
    if not a.no_code:
        code_zip(os.path.join(root, 'code'))
        print(t('✓ الكود', '✓ Code'))


if __name__ == '__main__':
    main()
