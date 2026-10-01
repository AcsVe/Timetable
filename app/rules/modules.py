"""Configurable screens (exams, duties): field labels the school renames, value lists it edits
(duty purposes, locations with floors and corridors, time slots…), and extra fields — optionally
attached under a built-in field as its sub-field (e.g. «الموقع» › «الطابق»).

Stored in app_setting["module:<name>"]; GET /api/modules/<name> returns it merged with the defaults."""
from __future__ import annotations

import re

from app.errors import ApiError

MODULES = ("exams", "duties")
FIELD_TYPES = ("text", "number", "select", "teachers", "date", "time", "bool", "textarea")
MAX_ITEMS = 300
SEP = " › "

# Built-in fields of each screen, with their default labels (the school may rename any of them).
FIELDS = {
    "exams": {
        "exam_date": ("التاريخ", "Date"), "session_label": ("الجلسة", "Session"),
        "starts_at": ("من الساعة", "From"), "ends_at": ("إلى الساعة", "To"),
        "stage_id": ("المرحلة", "Stage"), "grade_ids": ("الصفوف", "Grades"),
        "subject_id": ("المبحث", "Subject"), "title": ("عنوان الامتحان", "Exam title"),
        "room_id": ("القاعة", "Room"), "location": ("الموقع", "Location"),
        "section_ids": ("الشعب", "Sections"), "teacher_ids": ("المعلمون المراقبون", "Invigilators"),
        "notes": ("ملاحظات", "Notes"),
    },
    "duties": {
        "weekday_id": ("اليوم", "Day"), "duty_type": ("الغاية", "Purpose"),
        "location": ("الموقع", "Location"), "stage_id": ("المرحلة", "Stage"),
        "time_label": ("الفترة", "Time slot"), "starts_at": ("من الساعة", "From"), "ends_at": ("إلى الساعة", "To"),
        "teacher_ids": ("المعلمون المناوبون", "Teachers on duty"), "notes": ("ملاحظات", "Notes"),
    },
}

DEFAULTS = {
    "exams": {
        "title": {"ar": "جدول الامتحانات", "en": "Exam timetable"},
        "lists": {
            "session_labels": ["الجلسة الأولى", "الجلسة الثانية"],
            "locations": ["المبنى الرئيسي › الطابق الأرضي", "المبنى الرئيسي › الطابق الأول", "المبنى الرئيسي › الطابق الثاني"],
        },
    },
    "duties": {
        "title": {"ar": "جدول المناوبة", "en": "Duty roster"},
        "lists": {
            "duty_types": ["استقبال الطلبة في الفترة الصباحية", "الطابور الصباحي", "الاستراحات", "الأنشطة",
                           "الممرات", "مغادرة الطلبة"],
            "locations": ["البوابة الرئيسية", "الساحة", "المقصف",
                          "الطابق الأرضي › الممر الشرقي", "الطابق الأرضي › الممر الغربي",
                          "الطابق الأول › الممر الشرقي", "الطابق الأول › الممر الغربي",
                          "الطابق الثاني › الممر الشرقي", "الطابق الثاني › الممر الغربي"],
            "time_labels": ["قبل بدء الدوام", "الطابور الصباحي", "الاستراحة الأولى", "الاستراحة الثانية",
                            "نهاية الدوام"],
        },
    },
}
LIST_KEYS = {"exams": ("session_labels", "locations"), "duties": ("duty_types", "locations", "time_labels")}


def _bad(field: str, reason: str):
    return ApiError("validation", 400, details={"field": field, "reason": reason})


def _text(v, field, max_len=120) -> str:
    if not isinstance(v, str):
        raise _bad(field, "must be text")
    v = re.sub(r"\s+", " ", v).strip()
    if len(v) > max_len:
        raise _bad(field, f"max length {max_len}")
    return v


def clean_path(v: str) -> str:
    """'الطابق الأول>الممر الشرقي' / '… › …' → normalised «parent › child»."""
    parts = [p.strip() for p in re.split(r"\s*[›>]\s*", v) if p.strip()]
    return SEP.join(parts)


def normalize_module_config(key: str, value) -> dict:
    name = key.split(":", 1)[1]
    if name not in MODULES:
        raise _bad("key", f"unknown module; one of {list(MODULES)}")
    if not isinstance(value, dict):
        raise _bad("value", "must be an object")
    out: dict = {}
    if "title" in value and value["title"] is not None:
        t = value["title"]
        if not isinstance(t, dict):
            raise _bad("title", "must be {ar, en}")
        out["title"] = {k: _text(t.get(k) or "", f"title.{k}") for k in ("ar", "en")}
    labels = value.get("labels") or {}
    if not isinstance(labels, dict):
        raise _bad("labels", "must be an object")
    out["labels"] = {}
    for f, lab in labels.items():
        if f not in FIELDS[name]:
            raise _bad(f"labels.{f}", "unknown field")
        if not isinstance(lab, dict):
            raise _bad(f"labels.{f}", "must be {ar, en}")
        clean = {k: _text(lab.get(k) or "", f"labels.{f}.{k}") for k in ("ar", "en")}
        if clean["ar"] or clean["en"]:
            out["labels"][f] = clean
    lists = value.get("lists") or {}
    if not isinstance(lists, dict):
        raise _bad("lists", "must be an object")
    out["lists"] = {}
    for k, items in lists.items():
        if k not in LIST_KEYS[name]:
            raise _bad(f"lists.{k}", "unknown list")
        if not isinstance(items, list) or len(items) > MAX_ITEMS:
            raise _bad(f"lists.{k}", f"list of at most {MAX_ITEMS}")
        seen = []
        for i, it in enumerate(items):
            p = clean_path(_text(it, f"lists.{k}[{i}]", 200))
            if p and p not in seen:
                seen.append(p)
        out["lists"][k] = seen
    extra = value.get("extra_fields") or []
    if not isinstance(extra, list) or len(extra) > 40:
        raise _bad("extra_fields", "list of at most 40")
    out["extra_fields"] = []
    keys = set()
    for i, f in enumerate(extra):
        if not isinstance(f, dict):
            raise _bad(f"extra_fields[{i}]", "must be an object")
        k = str(f.get("key") or "").strip()
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,30}", k) or k in keys or k in FIELDS[name]:
            raise _bad(f"extra_fields[{i}].key", "invalid or duplicate key")
        keys.add(k)
        typ = f.get("type") or "text"
        if typ not in FIELD_TYPES:
            raise _bad(f"extra_fields[{i}].type", f"one of {list(FIELD_TYPES)}")
        label_ar = _text(f.get("label_ar") or "", f"extra_fields[{i}].label_ar")
        if not label_ar:
            raise _bad(f"extra_fields[{i}].label_ar", "required")
        parent = f.get("parent") or None
        if parent is not None and parent not in FIELDS[name]:
            raise _bad(f"extra_fields[{i}].parent", "unknown field")
        level = f.get("level") or "session"
        if level not in ("session", "room") or (name != "exams" and level != "session"):
            raise _bad(f"extra_fields[{i}].level", "invalid")
        options = [clean_path(_text(o, f"extra_fields[{i}].options", 200)) for o in (f.get("options") or [])]
        out["extra_fields"].append({
            "key": k, "label_ar": label_ar, "label_en": _text(f.get("label_en") or "", f"extra_fields[{i}].label_en"),
            "type": typ, "options": [o for o in options if o][:MAX_ITEMS], "parent": parent, "level": level,
            "placeholder": _text(f.get("placeholder") or "", f"extra_fields[{i}].placeholder"),
            "show_in_report": bool(f.get("show_in_report", True)),
        })
    return out


def module_config(name: str, saved: dict | None) -> dict:
    """Saved configuration merged over the defaults (a list the school saved replaces the default list)."""
    base = DEFAULTS[name]
    saved = saved or {}
    labels = {f: {"ar": ar, "en": en} for f, (ar, en) in FIELDS[name].items()}
    for f, lab in (saved.get("labels") or {}).items():
        if f in labels:
            labels[f] = {"ar": lab.get("ar") or labels[f]["ar"], "en": lab.get("en") or labels[f]["en"]}
    title = dict(base["title"])
    for k in ("ar", "en"):
        if (saved.get("title") or {}).get(k):
            title[k] = saved["title"][k]
    lists = {k: list(base["lists"].get(k, [])) for k in LIST_KEYS[name]}
    for k, items in (saved.get("lists") or {}).items():
        if k in lists:
            lists[k] = list(items)
    return {"name": name, "title": title, "labels": labels, "default_labels": {
        f: {"ar": ar, "en": en} for f, (ar, en) in FIELDS[name].items()},
        "lists": lists, "extra_fields": list(saved.get("extra_fields") or [])}


def load_module(name: str) -> dict:
    from app.extensions import db
    from app.models import AppSetting
    row = db.session.get(AppSetting, f"module:{name}")
    return module_config(name, row.value if row else None)
