"""خادم تجربة لفحص المظهر واللغة (tests/ui_audit.py): قاعدة PostgreSQL للتجربة تُمسح وتُبنى من الترحيلات، ثم تُملأ
بالمدرسة التجريبية (app.demo) ويُنشأ مدير.

    AUDIT_DATABASE_URL=postgresql://… python tests/audit_server.py <المنفذ>
يطبع سطراً واحداً (ready) ثم يبقى يعمل حتى يُوقَف. لا يُشغَّل أبداً على قاعدة حقيقية: يمسح مخطط public كاملاً.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PORT = int(sys.argv[1])
URL = os.environ.get('AUDIT_DATABASE_URL') or os.environ.get('TEST_DATABASE_URL')
if not URL or 'test' not in URL and 'audit' not in URL:
    raise SystemExit('AUDIT_DATABASE_URL must point to a test database (its name contains "test" or "audit")')
os.environ['TEST_DATABASE_URL'] = URL

from flask_migrate import upgrade  # noqa: E402
from sqlalchemy import text  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

from app import create_app  # noqa: E402
from app.config import TestConfig  # noqa: E402
from app.demo import seed_demo  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import AppUser  # noqa: E402

app = create_app(TestConfig)
with app.app_context():
    db.session.execute(text('DROP SCHEMA public CASCADE; CREATE SCHEMA public'))
    db.session.commit()
    upgrade(directory=str(ROOT / 'migrations'))
assert app.test_cli_runner().invoke(args=['seed-base']).exit_code == 0
with app.app_context():
    u = AppUser(email='admin@school.test', display_name='admin', role='admin')
    u.set_password('password123')
    db.session.add(u)
    db.session.commit()
    seed_demo(app, u.id)
print('ready', flush=True)
make_server('127.0.0.1', PORT, app, threaded=True).serve_forever()
