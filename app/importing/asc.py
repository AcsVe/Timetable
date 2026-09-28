"""aSc Timetables → Bundle.

aSc can export everything to XML (File → Export → aSc Timetables XML). That file
lists periods, day/week definitions, subjects, teachers, classrooms, grades, classes,
groups (with their division tag), lessons and the placed cards. `.roz` is aSc's own
project format; it is read when it turns out to be (possibly compressed) XML,
otherwise the user is asked to export the XML from aSc.
"""
from __future__ import annotations

import gzip
import io
import re
import zipfile
import zlib
import xml.etree.ElementTree as ET
from collections import defaultdict

from app.errors import ApiError
from app.importing.bundle import Bundle
from app.importing.text import HAS_ARABIC, clean, time_text

MAX_XML = 40_000_000


def _unsupported_roz() -> ApiError:
    return ApiError(
        "validation", 400, details={"reason": "unsupported_roz"},
        message="تعذّرت قراءة ملف ‎.roz مباشرةً لأن صيغته مغلقة. افتح الملف في aSc Timetables ثم اختر: "
                "ملف ← تصدير ← aSc Timetables XML، وارفع ملف XML الناتج",
        message_en="This .roz file cannot be read directly (closed format). Open it in aSc Timetables, "
                   "choose File → Export → aSc Timetables XML, and upload the XML file",
    )


def extract_xml(data: bytes, filename: str) -> bytes:
    """Return XML bytes from an aSc XML file or a .roz that wraps XML (plain, zip, gzip or zlib)."""
    head = data[:64].lstrip(b"\xef\xbb\xbf \r\n\t")
    if head.startswith(b"<"):
        return data
    if data[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for info in z.infolist():
                    if info.file_size > MAX_XML:
                        continue
                    blob = z.read(info)
                    if blob.lstrip(b"\xef\xbb\xbf \r\n\t")[:1] == b"<" and b"<timetable" in blob[:4096]:
                        return blob
        except zipfile.BadZipFile:
            pass
    for opener in (gzip.decompress, zlib.decompress, lambda b: zlib.decompress(b, -15)):
        try:
            blob = opener(data)
        except Exception:
            continue
        if blob.lstrip(b"\xef\xbb\xbf \r\n\t")[:1] == b"<":
            return blob
    if filename.lower().endswith(".roz"):
        raise _unsupported_roz()
    raise ApiError("validation", 400, details={"reason": "not_asc_xml"},
                   message="الملف ليس ملف aSc XML صالحاً", message_en="Not a valid aSc XML file")


def _num(v, default=None):
    s = clean(v)
    if not s:
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _ids(v) -> list[str]:
    return [x for x in (p.strip() for p in clean(v).split(",")) if x]


_CLASS_SPLIT = re.compile(r"^(?P<grade>.+?)(?P<sep>\s*[-/.]\s*|\s+)?(?P<sec>[A-Za-zء-ي])$")


def split_class_name(name: str) -> tuple[str, str] | None:
    """'7A' → ('7', 'A'); 'السابع أ' → ('السابع', 'أ'); 'Math' → None."""
    m = _CLASS_SPLIT.match(name)
    if not m:
        return None
    grade = m.group("grade").strip()
    if not grade or not (re.search(r"\d", grade) or m.group("sep")):
        return None
    return grade, m.group("sec")


def parse_asc(data: bytes, filename: str = "") -> Bundle:
    xml = extract_xml(data, filename)
    if len(xml) > MAX_XML:
        raise ApiError("validation", 413, details={"reason": "file_too_large"})
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        raise ApiError("validation", 400, details={"reason": "xml_parse_error", "detail": str(e)},
                       message="ملف XML تالف أو غير مكتمل", message_en="The XML file is damaged or incomplete")
    if root.tag != "timetable":
        raise ApiError("validation", 400, details={"reason": "not_asc_xml"},
                       message="الملف ليس ملف aSc XML صالحاً", message_en="Not a valid aSc XML file")

    b = Bundle(source="asc", by_name=False)
    each = lambda tag: [e.attrib for e in root.iter(tag)]  # noqa: E731

    # periods -------------------------------------------------------------
    raw_periods = []
    for p in each("period"):
        no = _num(p.get("period"), _num(p.get("name")))
        if no is None:
            continue
        try:
            start, end = time_text(p.get("starttime")), time_text(p.get("endtime"))
        except ValueError:
            start = end = None
        raw_periods.append({"no": int(no), "start": start, "end": end, "name": clean(p.get("name"))})
    offset = 1 if raw_periods and min(p["no"] for p in raw_periods) == 0 else 0
    if offset:
        b.warn("في الملف حصة صفرية؛ رُقِّمت الحصص بدءاً من 1 (الحصة الصفرية صارت الأولى)",
               "The file has a period 0; periods were renumbered from 1")
    for p in sorted(raw_periods, key=lambda p: p["no"]):
        b.periods.append({**p, "no": p["no"] + offset})

    # days: every daysdef is a bit string ("10000"); the longest defines the week length
    day_defs = {d.get("id"): clean(d.get("days")).split(",") for d in each("daysdef")}
    b.days = max((len(x) for v in day_defs.values() for x in v), default=0)

    weeks_defs = {w.get("id"): clean(w.get("weeks")) for w in each("weeksdef")}
    cycle = max((len(x) for v in weeks_defs.values() for x in v.split(",")), default=1)
    if cycle > 1:
        b.warn("الجدول في aSc متعدد الأسابيع؛ استُوردت الحصص على أنها أسبوعية",
               "The aSc timetable has several weeks; lessons were imported as weekly")

    # resources -------------------------------------------------------------
    def names(a) -> tuple[str, str | None]:
        n = clean(a.get("name")) or " ".join(filter(None, (clean(a.get("firstname")), clean(a.get("lastname")))))
        n = n or clean(a.get("short"))
        return n, (n if n and not HAS_ARABIC.search(n) else None)

    for s in each("subject"):
        n, en = names(s)
        if n:
            b.subjects.append({"key": s.get("id"), "name": n, "name_en": en, "short": clean(s.get("short")) or None,
                               "color": clean(s.get("color")) or None})
    for t in each("teacher"):
        n, en = names(t)
        if not n:
            continue
        g = clean(t.get("gender")).upper()
        b.teachers.append({"key": t.get("id"), "name": n, "name_en": en, "short": clean(t.get("short")) or None,
                           "email": clean(t.get("email")) or None, "phone": clean(t.get("mobile")) or None,
                           "gender": {"M": "m", "F": "f"}.get(g), "color": clean(t.get("color")) or None})
    for r in each("classroom"):
        n, en = names(r)
        if n:
            cap = _num(r.get("capacity"))
            b.rooms.append({"key": r.get("id"), "name": n, "name_en": en, "short": clean(r.get("short")) or None,
                            "capacity": int(cap) if cap and cap > 0 else None})

    # classes → grade / section --------------------------------------------
    grade_names = {clean(g.get("grade")): clean(g.get("name")) or clean(g.get("short")) for g in each("grade")}
    for c in each("class"):
        n, en = names(c)
        if not n:
            continue
        grade_ref = clean(c.get("grade"))
        grade, sec = grade_names.get(grade_ref) or None, n
        if not grade:
            split = split_class_name(n)
            grade, sec = split if split else (n, n)
        rooms = _ids(c.get("classroomids"))
        b.sections.append({"key": c.get("id"), "stage": None, "grade": grade, "name": sec,
                           "name_en": sec if not HAS_ARABIC.search(sec) else None,
                           "class_teacher": clean(c.get("teacherid")) or None,
                           "home_room": rooms[0] if len(rooms) == 1 else None})

    # groups → divisions -------------------------------------------------------
    group_info: dict[str, dict] = {}
    divisions: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for gr in each("group"):
        gid, cid = gr.get("id"), gr.get("classid")
        entire = clean(gr.get("entireclass")).lower() in ("1", "true")
        group_info[gid] = {"class": cid, "entire": entire}
        if entire:
            continue
        cnt = _num(gr.get("studentcount"))
        divisions[(cid, clean(gr.get("divisiontag")) or "1")].append(
            {"key": gid, "name": clean(gr.get("name")) or gid, "student_count": int(cnt) if cnt else None})
    for (cid, _tag), groups in divisions.items():
        b.divisions.append({"section": cid, "name": " / ".join(g["name"] for g in groups), "groups": groups})

    # lessons -------------------------------------------------------------
    for les in each("lesson"):
        lid = les.get("id")
        classes = _ids(les.get("classids"))
        subject = clean(les.get("subjectid"))
        if not classes or not subject:
            b.warn(f"تُجوهِل درس في aSc بلا صف أو مبحث (المعرّف {lid})",
                   f"Skipped an aSc lesson without class or subject (id {lid})", "lessons")
            continue
        groups = [g for g in _ids(les.get("groupids")) if not group_info.get(g, {}).get("entire", True)]
        targets = []
        for cid in classes:
            mine = [g for g in groups if group_info[g]["class"] == cid]
            targets += [(cid, g) for g in mine] if mine else [(cid, None)]
        ppw_raw = _num(les.get("periodsperweek"), 0) or 0
        dur = int(_num(les.get("periodspercard"), 1) or 1)
        ppw = max(1, round(ppw_raw))
        if ppw_raw and ppw_raw != ppw:
            b.warn(f"عدد حصص درس في aSc غير صحيح ({ppw_raw:g})؛ قُرِّب إلى {ppw}",
                   f"A lesson has a fractional period count ({ppw_raw:g}); rounded to {ppw}", "lessons")
        if dur > 4:
            b.warn("طول بطاقة أكبر من 4 حصص؛ عُدّ 4", "Card length above 4 periods; capped at 4", "lessons")
            dur = 4
        rooms = _ids(les.get("classroomids"))
        b.lessons.append({"key": lid, "subject": subject, "targets": targets,
                          "teachers": _ids(les.get("teacherids")), "ppw": ppw, "duration": dur,
                          "room": rooms[0] if len(rooms) == 1 else None, "row": None})

    # cards (placements) ------------------------------------------------------
    for card in each("card"):
        period = _num(card.get("period"))
        days = clean(card.get("days"))
        if period is None or "1" not in days:
            continue
        rooms = _ids(card.get("classroomids"))
        b.cards.append({"lesson": card.get("lessonid"), "day": days.index("1"), "period": int(period) + offset,
                        "room": rooms[0] if rooms else None})
    return b
