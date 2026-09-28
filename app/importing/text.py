"""Small text helpers shared by the parsers."""
from __future__ import annotations

import re

_TASHKEEL = re.compile(r"[ً-ْٰـ]")
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_SPLIT = re.compile(r"\s*[،,؛;+|\n]\s*")
HAS_ARABIC = re.compile(r"[؀-ۿ]")


def clean(v) -> str:
    """Cell value → trimmed single-spaced text ('' for empty)."""
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return re.sub(r"\s+", " ", str(v)).strip()


def norm(v) -> str:
    """Matching key: ignores diacritics, tatweel, hamza forms, ى/ي, ة/ه, case and extra spaces."""
    s = _TASHKEEL.sub("", clean(v))
    s = re.sub("[أإآٱ]", "ا", s).replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي")
    return s.translate(_ARABIC_DIGITS).casefold()


def header_key(v) -> str:
    return re.sub(r"[\s_\-:*().]+", " ", norm(v)).strip()


def to_int(v) -> int | None:
    s = clean(v).translate(_ARABIC_DIGITS)
    if not s:
        return None
    try:
        f = float(s)
    except ValueError:
        raise ValueError(s)
    return int(round(f))


def split_list(v) -> list[str]:
    return [x for x in (clean(p) for p in _SPLIT.split(clean(v))) if x]


def gender(v) -> str | None:
    k = norm(v)
    if not k:
        return None
    if k in {"m", "male", "man", "ذكر", "م", "معلم", "بنين", "رجل"}:
        return "m"
    if k in {"f", "female", "woman", "انثي", "ث", "معلمه", "بنات", "امراه"}:
        return "f"
    raise ValueError(clean(v))


def time_text(v) -> str | None:
    """'8:00', '08:00:00', 0.333 (Excel time fraction) → 'HH:MM'."""
    if v is None or v == "":
        return None
    if hasattr(v, "hour"):
        return f"{v.hour:02d}:{v.minute:02d}"
    if isinstance(v, float) and 0 <= v < 1:
        mins = round(v * 24 * 60)
        return f"{mins // 60:02d}:{mins % 60:02d}"
    m = re.match(r"^(\d{1,2})[:.](\d{2})", clean(v).translate(_ARABIC_DIGITS))
    if not m:
        raise ValueError(clean(v))
    return f"{int(m.group(1)):02d}:{m.group(2)}"
