"""تشغيل نظام الجدول على الكمبيوتر أو الهاتف بخادم Waitress (يعمل على Windows وTermux).

    python serve.py              # الترحيلات + البيانات الأساسية، ثم الخادم
    python serve.py --prepare    # الترحيلات + البيانات الأساسية فقط (يستعمله 1_setup.bat)

• العنوان المحلي: http://localhost:8004  (PORT في .env) — والعام عبر Cloudflare: https://4.iajaward.org
• القاعدة: PostgreSQL (DATABASE_URL في .env). عند تشغيل الكمبيوتر ينتظر الخادم خدمة PostgreSQL حتى تعمل.
• السجل: logs/server.log
"""
import logging
import logging.handlers
import os
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'ops'))
from common import load_env, port  # noqa: E402

load_env()
os.makedirs(os.path.join(BASE, 'logs'), exist_ok=True)
handler = logging.handlers.RotatingFileHandler(os.path.join(BASE, 'logs', 'server.log'),
                                               maxBytes=5 * 1024 * 1024, backupCount=5, encoding='utf-8')
handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
log = logging.getLogger('timetable')


def setup_logging():
    """Also after the migrations: Alembic's logging setup replaces the root handlers."""
    root = logging.getLogger()
    for h in list(root.handlers):
        if h is not handler:
            root.removeHandler(h)
    root.addHandler(handler)
    root.addHandler(logging.StreamHandler())
    root.setLevel(logging.INFO)


setup_logging()


def wait_for_database(app, minutes=5):
    """بعد إقلاع Windows قد تبدأ خدمة PostgreSQL بعد هذا الخادم بقليل."""
    from sqlalchemy import text
    from app.extensions import db
    deadline = time.time() + minutes * 60
    while True:
        try:
            with app.app_context():
                db.session.execute(text('SELECT 1'))
                db.session.remove()
            return
        except Exception as e:   # noqa: BLE001
            if time.time() > deadline:
                raise
            log.warning('Database not ready yet (%s) - retrying', e.__class__.__name__)
            time.sleep(5)


def prepare(app):
    """الترحيلات والبيانات الأساسية (تكرارها لا يغيّر شيئاً) — كما في أمر التشغيل على Render."""
    from flask_migrate import upgrade
    with app.app_context():
        upgrade(directory=os.path.join(BASE, 'migrations'))
    setup_logging()
    r = app.test_cli_runner().invoke(args=['seed-base'])
    if r.exit_code != 0:
        raise RuntimeError(f'seed-base failed: {r.output} {r.exception!r}')
    log.info('Database ready: %s', (r.output or '').strip())


def main():
    from wsgi import app
    wait_for_database(app)
    prepare(app)
    if '--prepare' in sys.argv:
        return
    from waitress import serve
    p = port()
    log.info('Timetable running on http://localhost:%s  (site: %s)', p, os.environ.get('BASE_URL') or '-')
    serve(
        app,
        host=os.environ.get('HOST', '0.0.0.0'),
        port=p,
        threads=int(os.environ.get('THREADS') or 8),
        trusted_proxy='127.0.0.1',            # Cloudflare Tunnel يتصل من الجهاز نفسه ويمرّر https
        trusted_proxy_count=1,
        trusted_proxy_headers={'x-forwarded-proto', 'x-forwarded-host', 'x-forwarded-for'},
        clear_untrusted_proxy_headers=True,
        channel_timeout=300,
        max_request_body_size=60 * 1024 * 1024,   # استيراد ملفات aSc وExcel
        ident='Timetable',
    )


if __name__ == '__main__':
    try:
        main()
    except Exception:
        log.exception('Server failed to start')
        raise
