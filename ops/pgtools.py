"""PostgreSQL: نسخ القاعدة إلى ملف واسترجاعها، على الكمبيوتر (Windows) وعلى الهاتف (Termux).

النسخة ملف SQL عادي مضغوط (pg_dump بصيغة plain) لأنه يُقرأ بأي إصدار من psql: الكمبيوتر قد يحمل
الإصدار 18 والهاتف 17، والصيغة المخصصة (custom) لا تُقرأ بإصدار أقدم من الذي كتبها.
كلمة المرور تُمرَّر في متغير PGPASSWORD لا في سطر الأوامر، فلا تظهر في قائمة العمليات.
"""
import glob
import gzip
import os
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import die, t  # noqa: E402

# جدول النسخ السحابية داخل Neon لا يُنسخ مع بيانات النظام
EXCLUDE_TABLES = ('iaj_cloud_backups', 'iaj_cloud_backups_id_seq')


def find_bin(name):
    """pg_dump / psql: من PATH (الهاتف) أو من أحدث إصدار مثبّت على Windows."""
    exe = name + ('.exe' if os.name == 'nt' else '')
    if os.environ.get('PG_BIN'):
        p = os.path.join(os.environ['PG_BIN'], exe)
        if os.path.isfile(p):
            return p
    if os.name == 'nt':
        found = []
        for root in (os.environ.get('ProgramFiles', r'C:\Program Files'), os.environ.get('ProgramFiles(x86)', '')):
            for p in glob.glob(os.path.join(root or 'C:\\', 'PostgreSQL', '*', 'bin', exe)):
                ver = re.findall(r'PostgreSQL[\\/](\d+)', p)
                found.append((int(ver[0]) if ver else 0, p))
        if found:
            return max(found)[1]
    p = shutil.which(exe)
    if p:
        return p
    die(t(f'لم أجد {name} — ثبّت PostgreSQL (على الكمبيوتر من postgresql.org، وعلى الهاتف: pkg install postgresql)',
          f'{name} not found - install PostgreSQL (PC: postgresql.org, phone: pkg install postgresql)'))


def conn_env(url):
    """رابط القاعدة (بأي صيغة: postgres://، postgresql://، postgresql+psycopg://) ← متغيرات libpq."""
    u = urlparse(url.replace('postgresql+psycopg://', 'postgresql://').replace('postgres://', 'postgresql://', 1))
    q = parse_qs(u.query)
    env = dict(os.environ)
    env.update({'PGHOST': u.hostname or 'localhost', 'PGPORT': str(u.port or 5432),
                'PGUSER': unquote(u.username or 'postgres'), 'PGDATABASE': (u.path or '/').lstrip('/') or 'postgres',
                'PGCONNECT_TIMEOUT': '20', 'PGCLIENTENCODING': 'UTF8'})
    if u.password:
        env['PGPASSWORD'] = unquote(u.password)
    if q.get('sslmode'):
        env['PGSSLMODE'] = q['sslmode'][0]
    elif u.hostname and u.hostname not in ('localhost', '127.0.0.1'):
        env['PGSSLMODE'] = 'require'
    env.pop('PGOPTIONS', None)
    return env


def db_url():
    url = os.environ.get('DATABASE_URL', '').strip()
    if not url:
        die(t('لا يوجد DATABASE_URL في .env — شغّل 1_setup.bat', 'No DATABASE_URL in .env - run 1_setup.bat'))
    return url


def _run(cmd, env, **kw):
    r = subprocess.run(cmd, env=env, capture_output=True, **kw)
    if r.returncode != 0:
        err = (r.stderr or b'').decode('utf-8', 'replace').strip()[-1500:]
        die(t(f'فشل {os.path.basename(cmd[0])}:\n{err}', f'{os.path.basename(cmd[0])} failed:\n{err}'))
    return r


def dump(url, out_gz):
    """نسخة كاملة من القاعدة إلى ملف .sql.gz (يكتب ملفاً مؤقتاً محلياً أولاً)."""
    env = conn_env(url)
    cmd = [find_bin('pg_dump'), '--no-owner', '--no-privileges', '--format=plain', '--encoding=UTF8']
    for tb in EXCLUDE_TABLES:
        cmd.append(f'--exclude-table={tb}')
    with tempfile.TemporaryDirectory() as tmpd:
        raw = os.path.join(tmpd, 'dump.sql')
        cmd += ['--file', raw]
        _run(cmd, env)
        if os.path.getsize(raw) < 200:
            die(t('النسخة فارغة — القاعدة غير موجودة؟', 'The dump is empty - is the database there?'))
        with open(raw, 'rb') as fi, gzip.open(out_gz, 'wb', compresslevel=6) as fo:
            shutil.copyfileobj(fi, fo)
    return out_gz


# أسطر يكتبها pg_dump الأحدث ولا يفهمها psql أو الخادم الأقدم، وأسطر تتعارض مع المخطط الجديد الفارغ
_SKIP = re.compile(rb'^(\\restrict |\\unrestrict |SET transaction_timeout|CREATE SCHEMA public;|COMMENT ON SCHEMA public )')


def server_version(url):
    r = _run([find_bin('psql'), '-At', '-c', 'SHOW server_version_num'], conn_env(url))
    return int(r.stdout.decode().strip() or 0)


def restore(url, gz):
    """يستبدل كل ما في القاعدة بمحتوى النسخة (المخطط public يُحذف ويُعاد إنشاؤه)."""
    env = conn_env(url)
    psql = find_bin('psql')
    with tempfile.TemporaryDirectory() as tmpd:
        sql = os.path.join(tmpd, 'restore.sql')
        with gzip.open(gz, 'rb') as fi, open(sql, 'wb') as fo:
            fo.write(b'SET client_min_messages = warning;\nDROP SCHEMA IF EXISTS public CASCADE;\nCREATE SCHEMA public;\n')
            for line in fi:
                if not _SKIP.match(line):
                    fo.write(line)
        _run([psql, '-q', '-X', '-v', 'ON_ERROR_STOP=1', '--single-transaction', '-f', sql], env)


def check(url):
    """عدد جداول النظام ورقم الترحيل — للتأكد أن النسخة سليمة."""
    env, psql = conn_env(url), find_bin('psql')
    r = _run([psql, '-At', '-c', "SELECT count(*), to_regclass('public.alembic_version') IS NOT NULL "
                                 "FROM information_schema.tables WHERE table_schema='public'"], env)
    n, has_rev = r.stdout.decode().strip().split('|')
    rev = '-'
    if has_rev == 't':
        rev = _run([psql, '-At', '-c', 'SELECT version_num FROM alembic_version LIMIT 1'], env).stdout.decode().strip() or '-'
    return int(n), rev


def fingerprint(url):
    """يتغيّر مع أي كتابة في النظام (سجل التدقيق يُكتب مع كل تعديل): هل سُجّل شيء أثناء الطوارئ؟"""
    r = subprocess.run([find_bin('psql'), '-At', '-c',
                        "SELECT coalesce(max(id),0) || ':' || count(*) FROM audit_log"], env=conn_env(url), capture_output=True)
    return r.stdout.decode().strip() if r.returncode == 0 else 'none'


def ensure_database(url):
    """ينشئ القاعدة على الخادم المحلي إن لم تكن موجودة."""
    env = conn_env(url)
    name = env['PGDATABASE']
    admin = dict(env, PGDATABASE='postgres')
    psql = find_bin('psql')
    r = subprocess.run([psql, '-At', '-c', f"SELECT 1 FROM pg_database WHERE datname = '{name}'"], env=admin, capture_output=True)
    if r.returncode != 0:
        err = (r.stderr or b'').decode('utf-8', 'replace').strip()
        die(t(f'تعذّر الاتصال بـ PostgreSQL على هذا الجهاز:\n{err}\n  تأكد أن خدمة PostgreSQL تعمل وأن كلمة المرور صحيحة',
              f'Could not connect to PostgreSQL on this device:\n{err}\n  Check the PostgreSQL service and the password'))
    if r.stdout.decode().strip() != '1':
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
            die(t(f'اسم القاعدة غير صالح: {name}', f'Invalid database name: {name}'))
        _run([psql, '-q', '-c', f'CREATE DATABASE "{name}" ENCODING \'UTF8\' TEMPLATE template0'], admin)
        print(t(f'✓ أُنشئت القاعدة {name}', f'✓ Created the database {name}'))
