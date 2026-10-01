"""Checks for the exam timetable and the duty roster: an invigilator or a room booked twice at the
same time, a teacher on two duties at once, or on duty while teaching a lesson."""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import time

from sqlalchemy import select

from app.arabic import teacher_title
from app.extensions import db
from app.models import Card, DutyAssignment, ExamSession, Lesson, Room, Section, Subject, Teacher, Timetable, Weekday
from app.rules.bells import resolve_schedule


def _overlap(a0: time | None, a1: time | None, b0: time | None, b1: time | None) -> bool | None:
    """True / False when both intervals are known, None when a time is missing."""
    if not (a0 and a1 and b0 and b1):
        return None
    return a0 < b1 and b0 < a1


def _fmt(t: time | None) -> str:
    return t.strftime("%H:%M") if t else ""


def _span(a: time | None, b: time | None) -> str:
    return f"{_fmt(a)}–{_fmt(b)}" if a and b else (_fmt(a) or "")


def _tname(t: Teacher | None, en=False) -> str:
    if t is None:
        return "?"
    return (t.name_en or t.name_ar) if en else f"{teacher_title(t.gender)} {t.name_ar}"


def _issue(out, code, message, message_en, **extra):
    out.append({"code": code, "message": message, "message_en": message_en,
                **{k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in extra.items()}})


def exam_label(e: ExamSession, subjects: dict) -> str:
    s = subjects.get(e.subject_id)
    return (s.name_ar if s else None) or e.title or "امتحان"


# ---------------------------------------------------------------------------
def check_exams(term_id: uuid.UUID) -> list[dict]:
    exams = list(db.session.scalars(select(ExamSession).where(ExamSession.term_id == term_id)))
    teachers = {t.id: t for t in db.session.scalars(select(Teacher))}
    rooms = {r.id: r for r in db.session.scalars(select(Room))}
    subjects = {s.id: s for s in db.session.scalars(select(Subject))}
    sections = {s.id: s for s in db.session.scalars(select(Section))}
    out: list[dict] = []
    by_date = defaultdict(list)
    for e in exams:
        by_date[e.exam_date].append(e)
    seen = set()
    for day, items in by_date.items():
        for i, a in enumerate(items):
            for b in items[i + 1:]:
                ov = _overlap(a.starts_at, a.ends_at, b.starts_at, b.ends_at)
                if ov is None:   # times not set: the same named session counts as the same time
                    ov = bool(a.session_label) and a.session_label == b.session_label
                if not ov:
                    continue
                la, lb = exam_label(a, subjects), exam_label(b, subjects)
                tid_a = {uuid.UUID(t) for r in a.rooms or [] for t in r.get("teacher_ids") or []}
                tid_b = {uuid.UUID(t) for r in b.rooms or [] for t in r.get("teacher_ids") or []}
                for tid in sorted(tid_a & tid_b, key=str):
                    key = ("inv", tid, frozenset({a.id, b.id}))
                    if key in seen:
                        continue
                    seen.add(key)
                    t = teachers.get(tid)
                    _issue(out, "invigilator_clash",
                           f"{_tname(t)}: مراقبة في امتحانَي {la} و{lb} في الوقت نفسه ({day.isoformat()})",
                           f"{_tname(t, True)}: invigilating {la} and {lb} at the same time ({day.isoformat()})",
                           teacher_id=tid, exam_ids=[str(a.id), str(b.id)])
                ra = {r.get("room_id") for r in a.rooms or [] if r.get("room_id")}
                rb = {r.get("room_id") for r in b.rooms or [] if r.get("room_id")}
                for rid in sorted(ra & rb):
                    room = rooms.get(uuid.UUID(rid))
                    if room is not None and room.is_shared:
                        continue
                    _issue(out, "exam_room_clash",
                           f"القاعة {room.name_ar if room else '?'}: محجوزة لامتحانَي {la} و{lb} في الوقت نفسه ({day.isoformat()})",
                           f"Room {(room.name_en or room.name_ar) if room else '?'}: booked for {la} and {lb} at once ({day.isoformat()})",
                           room_id=rid, exam_ids=[str(a.id), str(b.id)])
                sa = {s for r in a.rooms or [] for s in r.get("section_ids") or []}
                sb = {s for r in b.rooms or [] for s in r.get("section_ids") or []}
                for sid in sorted(sa & sb):
                    sec = sections.get(uuid.UUID(sid))
                    _issue(out, "exam_section_clash",
                           f"الشعبة {sec.name_ar if sec else '?'}: امتحانا {la} و{lb} في الوقت نفسه ({day.isoformat()})",
                           f"Section {(sec.name_en or sec.name_ar) if sec else '?'}: {la} and {lb} at the same time ({day.isoformat()})",
                           section_id=sid, exam_ids=[str(a.id), str(b.id)])
    for e in exams:
        for r in e.rooms or []:
            if not r.get("teacher_ids"):
                where = rooms.get(uuid.UUID(r["room_id"])).name_ar if r.get("room_id") and rooms.get(uuid.UUID(r["room_id"])) else (r.get("location") or "")
                _issue(out, "no_invigilator", f"امتحان {exam_label(e, subjects)} ({e.exam_date.isoformat()}){' — ' + where if where else ''}: لم يُحدَّد له مراقب",
                       f"Exam {exam_label(e, subjects)} ({e.exam_date.isoformat()}){' — ' + where if where else ''}: no invigilator",
                       exam_id=e.id)
    return out


# ---------------------------------------------------------------------------
def teacher_lesson_times(tt: Timetable) -> dict:
    """teacher_id -> weekday_id -> [(start, end, subject name)] of the lessons they teach."""
    out = defaultdict(lambda: defaultdict(list))
    lessons = {l.id: l for l in db.session.scalars(select(Lesson).where(Lesson.timetable_id == tt.id))}
    cache: dict = {}
    for c in db.session.scalars(select(Card).where(Card.timetable_id == tt.id, Card.weekday_id.is_not(None))):
        l = lessons.get(c.lesson_id)
        if l is None or not l.targets:
            continue
        grade = l.targets[0].section.grade
        key = (grade.id, c.weekday_id)
        if key not in cache:
            sched = resolve_schedule(tt.term_id, grade, c.weekday_id)
            cache[key] = {s.period_no: (s.starts_at, s.ends_at) for s in sched.slots if s.kind == "lesson"} if sched else {}
        slots = [cache[key].get(p) for p in range(c.period_no, c.period_no + c.duration)]
        slots = [s for s in slots if s]
        if not slots:
            continue
        for tid in l.teacher_ids:
            out[tid][c.weekday_id].append((slots[0][0], slots[-1][1], l.subject.name_ar))
    return out


def check_duties(term_id: uuid.UUID, tt: Timetable | None) -> list[dict]:
    duties = list(db.session.scalars(select(DutyAssignment).where(DutyAssignment.term_id == term_id)))
    teachers = {t.id: t for t in db.session.scalars(select(Teacher))}
    days = list(db.session.scalars(select(Weekday).where(Weekday.is_school_day.is_(True)).order_by(Weekday.sort_order)))
    day_name = {d.id: d.name_ar for d in days}
    day_name_en = {d.id: d.name_en or d.name_ar for d in days}
    out: list[dict] = []

    def days_of(d: DutyAssignment):
        return [d.weekday_id] if d.weekday_id else [x.id for x in days]

    seen = set()
    for i, a in enumerate(duties):
        for b in duties[i + 1:]:
            common_days = set(days_of(a)) & set(days_of(b))
            if not common_days:
                continue
            ov = _overlap(a.starts_at, a.ends_at, b.starts_at, b.ends_at)
            if ov is None:
                ov = bool(a.time_label) and a.time_label == b.time_label
            if not ov:
                continue
            for tid in set(a.teacher_ids or []) & set(b.teacher_ids or []):
                for wd in sorted(common_days, key=lambda x: [d.id for d in days].index(x) if x in day_name else 99):
                    key = (tid, wd, frozenset({a.id, b.id}))
                    if key in seen:
                        continue
                    seen.add(key)
                    t = teachers.get(tid)
                    _issue(out, "duty_clash",
                           f"{_tname(t)}: مناوبتان في الوقت نفسه يوم {day_name.get(wd, '')} ({a.duty_type} / {b.duty_type})",
                           f"{_tname(t, True)}: two duties at the same time on {day_name_en.get(wd, '')} ({a.duty_type} / {b.duty_type})",
                           teacher_id=tid, weekday_id=wd, duty_ids=[str(a.id), str(b.id)])
    if tt is not None:
        busy = teacher_lesson_times(tt)
        for d in duties:
            if not (d.starts_at and d.ends_at):
                continue
            for tid in d.teacher_ids or []:
                for wd in days_of(d):
                    for s, e, subj in busy.get(tid, {}).get(wd, []):
                        if s < d.ends_at and d.starts_at < e:
                            t = teachers.get(tid)
                            _issue(out, "duty_during_lesson",
                                   f"{_tname(t)}: مناوبة ({d.duty_type}، {_span(d.starts_at, d.ends_at)}) يوم {day_name.get(wd, '')} في أثناء حصة {subj} ({_span(s, e)})",
                                   f"{_tname(t, True)}: duty ({d.duty_type}, {_span(d.starts_at, d.ends_at)}) on {day_name_en.get(wd, '')} during a {subj} lesson ({_span(s, e)})",
                                   teacher_id=tid, weekday_id=wd, duty_id=d.id)
    for d in duties:
        if not d.teacher_ids:
            _issue(out, "duty_no_teacher", f"مناوبة {d.duty_type}{' — ' + d.location if d.location else ''}"
                   f"{' يوم ' + day_name[d.weekday_id] if d.weekday_id in day_name else ''}: لم يُحدَّد لها معلم",
                   f"Duty {d.duty_type}{' — ' + d.location if d.location else ''}: no teacher", duty_id=d.id)
    return out
