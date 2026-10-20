"""بصمة البيانات: تتغيّر مع أي تعديل في النظام (يستخدمها الهاتف ليعرف هل سُجّل شيء أثناء الطوارئ)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pgtools  # noqa: E402
from common import load_env  # noqa: E402

load_env()
print(pgtools.fingerprint(pgtools.db_url()))
