"""حساب مدير النظام الأول: إن لم يوجد أي مدير في القاعدة يُطلب بريده وكلمة مروره وينشأ.

    python ops/first_admin.py           # فقط إن لم يوجد مدير
    python ops/first_admin.py --reset   # إنشاء مدير أو تغيير كلمة مرور مدير موجود
"""
import getpass
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'ops'))
from common import load_env, t  # noqa: E402


def main():
    load_env()
    from sqlalchemy import func, select
    from wsgi import app
    from app.extensions import db
    from app.models import AppUser
    with app.app_context():
        admins = db.session.scalar(select(func.count()).select_from(AppUser).where(AppUser.role == 'admin',
                                                                                  AppUser.deleted_at.is_(None)))
    if admins and '--reset' not in sys.argv:
        print(t(f'  ✓ يوجد مدير نظام في القاعدة ({admins})', f'  ✓ An admin account exists ({admins})'))
        return
    print(t('\n  إنشاء حساب مدير النظام', '\n  Create the admin account'))
    email = input(t('  البريد الإلكتروني: ', '  Email: ')).strip()
    pw = getpass.getpass(t('  كلمة المرور (8 أحرف على الأقل، لا تظهر أثناء الكتابة): ', '  Password (8+ characters, hidden): '))
    if not email or len(pw) < 8:
        print(t('  ✖ البريد أو كلمة المرور غير صالحين — أعد التشغيل: venv\\Scripts\\python ops\\first_admin.py',
                '  ✖ Invalid email or password - run again: venv\\Scripts\\python ops\\first_admin.py'))
        sys.exit(1)
    r = app.test_cli_runner().invoke(args=['create-admin', '--email', email, '--password', pw])
    print('  ' + (r.output or '').strip())
    sys.exit(r.exit_code)


if __name__ == '__main__':
    main()
