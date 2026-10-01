"""Grammatically correct Arabic (فصحى) for counted nouns and gendered phrases in messages."""
from __future__ import annotations

# noun -> (singular, dual, plural 3–10); the dual in the genitive/accusative is DUAL_GEN
DUAL_GEN = {"period": "حصتين", "slot": "خانتين", "gap": "فجوتين", "day": "يومين", "card": "بطاقتين", "teacher": "معلمَين"}
NOUNS = {
    "period": ("حصة", "حصتان", "حصص"),
    "slot": ("خانة", "خانتان", "خانات"),
    "gap": ("فجوة", "فجوتان", "فجوات"),
    "day": ("يوم", "يومان", "أيام"),
    "card": ("بطاقة", "بطاقتان", "بطاقات"),
    "teacher": ("معلم", "معلمان", "معلمين"),
}
FEMININE = {"period", "slot", "gap", "card"}


def count(n: int, noun: str, case: str = "nom") -> str:
    """3 → «3 حصص»، 11 → «11 حصة»، 1 → «حصة واحدة»، 2 → «حصتان» (case="gen": «حصتين»، بعد حرف الجر)."""
    one, two, few = NOUNS[noun]
    if n == 1:
        return f"{one} {'واحدة' if noun in FEMININE else 'واحد'}"
    if n == 2:
        return DUAL_GEN[noun] if case == "gen" else two
    r = n % 100
    if 3 <= r <= 10:
        return f"{n} {few}"
    return f"{n} {one}"


def teacher_title(gender: str | None) -> str:
    return "المعلمة" if gender == "f" else "المعلم"


def g(gender: str | None, masculine: str, feminine: str) -> str:
    return feminine if gender == "f" else masculine
