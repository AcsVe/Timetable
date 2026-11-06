"""أدوات مشتركة للكمبيوتر والهاتف: قراءة .env، والمسارات، ووقت عمّان، ورسائل الخطأ."""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = 'timetable'                 # اسم النظام في النسخ الاحتياطية وNeon وDrive


# نوافذ الأوامر في ويندوز لا تعرض العربية (مربعات)، لذلك الكمبيوتر بالإنجليزية والهاتف (Termux) بالعربية.
# يمكن فرض أي منهما بـ IAJ_LANG=ar أو IAJ_LANG=en.
_LANG = os.environ.get('IAJ_LANG') or os.environ.get('LANG_UI') or ('en' if os.name == 'nt' else 'ar')
EN = _LANG == 'en'
_ASCII = {'✓': '[OK]', '✅': '[OK]', '✖': '[X]', '❌': '[X]', '⚠': '[!]', '←': '<-', '→': '->', '★': '*', '•': '-',
          '🟢': '[OK]', '🔴': '[X]', '✋': '[!]', '…': '...', '—': '-', '–': '-', '«': '"', '»': '"'}


def _plain(text):
    for k, v in _ASCII.items():
        text = text.replace(k, v)
    return text


def t(ar, en):
    if not EN:
        return ar
    return _plain(en) if os.name == 'nt' else en


class _PlainOut:
    """على ويندوز: كل ما يُطبع يمر بـ _plain، فلا تظهر الرموز (✓ ✖ ←) مربعات في نافذة الأوامر."""

    def __init__(self, stream):
        self._stream = stream

    def write(self, text):
        return self._stream.write(_plain(text) if isinstance(text, str) else text)

    def __getattr__(self, name):
        return getattr(self._stream, name)


if EN and os.name == 'nt':
    for _name in ('stdout', 'stderr'):
        if getattr(sys, _name, None) is not None and not isinstance(getattr(sys, _name), _PlainOut):
            setattr(sys, _name, _PlainOut(getattr(sys, _name)))


def load_env():
    """يقرأ .env (لا يستبدل متغيراً موجوداً مسبقاً)."""
    path = os.path.join(BASE, '.env')
    if os.path.isfile(path):
        with open(path, encoding='utf-8-sig', errors='ignore') as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k == 'VAPID_PRIVATE_KEY':
                    v = v.replace('\\n', '\n')   # مفتاح PEM مكتوب في سطر واحد
                if k and k not in os.environ:
                    os.environ[k] = v
    os.environ.setdefault('APP_TIMEZONE', 'Asia/Amman')
    os.environ.setdefault('DATA_DIR', os.path.join(BASE, 'data'))


def data_dir():
    return os.environ.get('DATA_DIR') or os.path.join(BASE, 'data')


def backup_root():
    return os.environ.get('BACKUP_DIR') or os.path.join(BASE, 'backups')


def port():
    return int(os.environ.get('PORT') or 8004)


def stamp():
    """وقت عمّان (للترتيب ولأسماء الملفات)"""
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo('Asia/Amman')).strftime('%Y-%m-%d_%H%M%S')
    except Exception:
        return datetime.now().strftime('%Y-%m-%d_%H%M%S')


def die(msg, code=1):
    print('\n✖ ' + msg)
    sys.exit(code)
