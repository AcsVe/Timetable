"""Language quality: correct Arabic number agreement, and every UI string has an English translation."""
import re
from pathlib import Path

from app.arabic import count

STATIC = Path(__file__).resolve().parent.parent / "app" / "static" / "js"


def test_arabic_counted_nouns():
    assert count(1, "period") == "حصة واحدة"
    assert count(2, "period") == "حصتان"
    assert count(3, "period") == "3 حصص"
    assert count(10, "gap") == "10 فجوات"
    assert count(11, "period") == "11 حصة"
    assert count(24, "slot") == "24 خانة"
    assert count(103, "day") == "103 أيام"
    assert count(1, "teacher") == "معلم واحد"


def test_every_ui_string_has_an_english_translation():
    dict_src = (STATIC / "i18n.js").read_text(encoding="utf-8")
    keys = set(re.findall(r"'([^']+)':", dict_src))
    used = set()
    for f in STATIC.rglob("*.js"):
        if f.name == "i18n.js":  # the dictionary itself (its comments contain examples)
            continue
        src = f.read_text(encoding="utf-8")
        used |= set(re.findall(r"\bt\('([^']+)'\)", src))
        if f.name == "crud.js":  # config labels are translated with t(f.label)
            used |= set(re.findall(r"(?:label|title|help): '([^']*[؀-ۿ][^']*)'", src))
    missing = sorted(s for s in used if re.search(r"[؀-ۿ]", s) and s not in keys)
    assert missing == [], missing


def test_validation_messages_agree_in_number_and_gender(school):
    a = school["api"]
    t = a.ok("get", f"/api/teachers/{school['t2']}")  # سارة
    a.ok("patch", f"/api/teachers/{t['id']}", {"version": t["version"], "gender": "f", "target_weekly_periods": 5})
    a.ok("post", "/api/lessons", {"timetable_id": school["tt"], "subject_id": school["math"], "periods_per_week": 3,
                                  "teachers": [school["t2"]], "targets": [{"section_id": school["s5a"]}]})
    rep = a.ok("get", f"/api/timetables/{school['tt']}/validate")
    msgs = [w["message"] for w in rep["warnings"]]
    assert "الرياضيات: 3 حصص لم تُدرَج في الجدول بعد" in msgs
    assert "المعلمة سارة: لم يُسنَد إليها إلا 3 حصص، ونصابها الأسبوعي 5" in msgs
