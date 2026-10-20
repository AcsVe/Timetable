"""إعداد ملف .env على هذا الجهاز (مرة واحدة).

يأخذ من الأنظمة الأخرى على الجهاز نفسه ما يلزم إن وجدها: مجلد Google Drive للنسخ (BACKUP_DIR) ورمز
Cloudflare (CF_API_TOKEN) — من موقع الجائزة (IAJ) أو من التذاكر أو القاعات أو الحضور.
"""
import getpass
import os
import secrets
import sys
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import BASE, SITE  # noqa: E402

ENV = os.path.join(BASE, '.env')


def read_env(path):
    out = {}
    if os.path.isfile(path):
        for raw in open(path, encoding='utf-8-sig', errors='ignore'):
            line = raw.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def sibling_envs():
    """ملفات .env للأنظمة الأخرى على هذا الجهاز: الجائزة أولاً ثم بقية الأنظمة."""
    cands = [os.environ.get('IAJ_DIR', '')]
    for drive in 'CDEFG':
        cands += [f'{drive}:\\IAJ', f'{drive}:\\IAJ-main', f'{drive}:\\iaj']
    for drive in 'CDEFG':
        cands += [f'{drive}:\\{d}' for d in ('RASTKT', 'TKT', 'Venue', 'Venues', 'Att', 'Attendance')]
    for parent in {os.path.dirname(BASE), os.path.dirname(os.path.dirname(BASE))}:
        try:
            cands += [os.path.join(parent, d) for d in os.listdir(parent)]
        except OSError:
            pass
    seen, out = set(), []
    for d in cands:
        if not d or d in seen or os.path.abspath(d) == os.path.abspath(BASE):
            continue
        seen.add(d)
        env = os.path.join(d, '.env')
        if os.path.isfile(env):
            vals = read_env(env)
            if vals.get('CF_API_TOKEN') or vals.get('BACKUP_DIR'):
                is_iaj = os.path.isfile(os.path.join(d, 'standby', 'cf_switch.py'))
                out.append((0 if is_iaj else 1, d, vals, is_iaj))
    return sorted(out, key=lambda x: x[0])


def ask(label, default='', secret=False):
    shown = ' [مخفي]' if secret and default else (f' [{default}]' if default else '')
    v = (getpass.getpass if secret else input)(f'  {label}{shown}: ').strip()
    return ''.join(ch for ch in v if ch.isprintable()).strip() or default


def backup_default(found):
    for _o, _d, vals, is_iaj in found:
        bk = vals.get('BACKUP_DIR', '')
        if not bk:
            continue
        if is_iaj:
            return os.path.join(bk, SITE)
        # نظام آخر: مجلده داخل IAJ-backups (مثل ...\IAJ-backups\rastkt) — المجاور له لهذا النظام
        return os.path.join(os.path.dirname(bk.rstrip('\\/')), SITE)
    return ''


def main():
    cur = read_env(ENV)
    found = sibling_envs()
    for _o, d, _v, is_iaj in found[:3]:
        print(f'  وُجد {"موقع الجائزة" if is_iaj else "نظام آخر"} في: {d}')
    token = cur.get('CF_API_TOKEN') or next((v['CF_API_TOKEN'] for _o, _d, v, _i in found if v.get('CF_API_TOKEN')), '')
    print('\n  إعدادات نظام الجدول المدرسي (Enter لقبول القيمة بين القوسين)\n')
    vals = dict(cur)
    vals.setdefault('SECRET_KEY', secrets.token_urlsafe(48))
    vals['BASE_URL'] = ask('عنوان الموقع', cur.get('BASE_URL', 'https://4.iajaward.org'))
    vals['PORT'] = cur.get('PORT', '8004')
    vals['APP_TIMEZONE'] = cur.get('APP_TIMEZONE', 'Asia/Amman')
    vals['SESSION_COOKIE_SECURE'] = cur.get('SESSION_COOKIE_SECURE', '1')

    if not cur.get('DATABASE_URL'):
        print('\n  قاعدة البيانات: PostgreSQL على هذا الكمبيوتر')
        user = ask('مستخدم PostgreSQL', 'postgres')
        pw = ask('كلمة مرور PostgreSQL (التي وُضعت عند تثبيته)', '', True)
        dbport = ask('المنفذ', '5432')
        name = ask('اسم القاعدة', 'timetable')
        vals['DATABASE_URL'] = f'postgresql+psycopg://{quote(user)}:{quote(pw, safe="")}@localhost:{dbport}/{name}'
    vals['BACKUP_DIR'] = ask('مجلد النسخ الاحتياطية (داخل Google Drive)', cur.get('BACKUP_DIR') or backup_default(found))
    vals['CF_API_TOKEN'] = token or ask('رمز Cloudflare API', '', True)
    print('\n  البريد (Microsoft 365) — انسخها من Render ← Environment، أو اضبطها لاحقاً من صفحة «البريد». Enter للتخطي:')
    for k, secret in (('MS_TENANT_ID', False), ('MS_CLIENT_ID', False), ('MS_CLIENT_SECRET', True), ('MS_MAIL_SENDER', False)):
        vals[k] = ask(k, cur.get(k, ''), secret)
    order = ['SECRET_KEY', 'BASE_URL', 'PORT', 'DATABASE_URL', 'APP_TIMEZONE', 'SESSION_COOKIE_SECURE', 'BACKUP_DIR',
             'CF_API_TOKEN', 'MS_TENANT_ID', 'MS_CLIENT_ID', 'MS_CLIENT_SECRET', 'MS_MAIL_SENDER']
    keys = order + [k for k in vals if k not in order]
    with open(ENV, 'w', encoding='utf-8') as fh:
        fh.write('# إعدادات نظام الجدول على هذا الجهاز — لا ترفع هذا الملف ولا تشاركه\n')
        for k in keys:
            if vals.get(k):
                fh.write(f'{k}={vals[k]}\n')
    print(f'\n  ✓ حُفظت الإعدادات في {ENV}')
    if not vals.get('CF_API_TOKEN'):
        print('  ⚠ لا يوجد رمز Cloudflare: لن يُربط 4.iajaward.org الآن (أضفه لاحقاً: venv\\Scripts\\python ops\\setenv.py CF_API_TOKEN …)')
    if not vals.get('BACKUP_DIR'):
        print('  ⚠ لا يوجد مجلد Drive: ستُحفظ النسخ في مجلد backups داخل النظام')


if __name__ == '__main__':
    main()
