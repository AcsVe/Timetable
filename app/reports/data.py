"""Report data: builds language-aware Grid / Table structures that the JSON, Excel and PDF
renderers all share, so the three outputs always contain exactly the same numbers."""
from __future__ import annotations

import os
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.extensions import db
from app.models import (
    Card,
    Grade,
    Lesson,
    Room,
    School,
    Section,
    Stage,
    StudentGroup,
    Subject,
    Teacher,
    Timetable,
    Weekday,
)
from app.rules.bells import BellCache, resolve_schedule

KINDS = (
    "teacher-timetable", "section-timetable", "room-timetable",
    "teacher-sections", "teacher-subjects",
    "stats-teachers", "stats-subjects", "stats-sections",
)
FILTER_KEYS = ("stage_id", "grade_id", "section_id", "teacher_id", "subject_id", "room_id")

TITLES = {
    "teacher-timetable": ("جدول حصص المعلم", "Teacher timetable"),
    "section-timetable": ("الجدول الأسبوعي للشعبة", "Section weekly timetable"),
    "room-timetable": ("جدول إشغال القاعة", "Room timetable"),
    "teacher-sections": ("توزيع المعلمين على الشعب", "Teachers by section"),
    "teacher-subjects": ("توزيع المعلمين على المباحث", "Teachers by subject"),
    "stats-teachers": ("إحصائيات المعلمين والنصاب", "Teacher load statistics"),
    "stats-subjects": ("إحصائيات المباحث", "Subject statistics"),
    "stats-sections": ("تغطية الحصص في الشعب", "Section coverage"),
}


@dataclass
class Grid:
    title: str
    days: list[str]
    periods: list[tuple[int, str | None]]            # (period number, "07:45–08:30" or None)
    cells: dict = field(default_factory=dict)        # (day_idx, period_no) -> list[list[str]]
    missing: set = field(default_factory=set)        # (day_idx, period_no) that don't exist that day
    footer: str | None = None


@dataclass
class Table:
    title: str
    columns: list[str]
    rows: list[list]
    numeric: set[int] = field(default_factory=set)
    percent: set[int] = field(default_factory=set)
    totals: list | None = None


@dataclass
class Report:
    kind: str
    lang: str
    title: str
    school_name: str
    timetable_name: str
    filters: str
    generated_at: str
    grids: list[Grid] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)

    @property
    def rtl(self) -> bool:
        return self.lang == "ar"

    def to_json(self) -> dict:
        return {
            "kind": self.kind, "lang": self.lang, "title": self.title, "school_name": self.school_name,
            "timetable_name": self.timetable_name, "filters": self.filters, "generated_at": self.generated_at,
            "grids": [{
                "title": g.title, "days": g.days, "periods": [{"no": n, "time": t} for n, t in g.periods],
                "cells": [{"day": d, "period": p, "entries": v} for (d, p), v in sorted(g.cells.items())],
                "missing": [{"day": d, "period": p} for d, p in sorted(g.missing)], "footer": g.footer,
            } for g in self.grids],
            "tables": [{"title": t.title, "columns": t.columns, "rows": t.rows, "numeric": sorted(t.numeric),
                        "percent": sorted(t.percent), "totals": t.totals} for t in self.tables],
        }


# ---------------------------------------------------------------------------
class Ctx:
    """Everything a report needs, loaded once."""

    def __init__(self, tt: Timetable, lang: str, filters: dict):
        self.tt, self.lang, self.f = tt, lang, filters
        self.stages = {s.id: s for s in db.session.scalars(select(Stage))}
        self.grades = {g.id: g for g in db.session.scalars(select(Grade))}
        self.sections = {s.id: s for s in db.session.scalars(select(Section))}
        self.groups = {g.id: g for g in db.session.scalars(select(StudentGroup))}
        self.subjects = {s.id: s for s in db.session.scalars(select(Subject))}
        self.teachers = {t.id: t for t in db.session.scalars(select(Teacher))}
        self.rooms = {r.id: r for r in db.session.scalars(select(Room))}
        self.days = list(db.session.scalars(
            select(Weekday).where(Weekday.is_school_day.is_(True)).order_by(Weekday.sort_order)))
        self.lessons = list(db.session.scalars(select(Lesson).where(Lesson.timetable_id == tt.id)))
        self.cards = list(db.session.scalars(select(Card).where(Card.timetable_id == tt.id)))
        self.lesson = {l.id: l for l in self.lessons}
        self.bells = BellCache(tt.term_id)

    # -- labels ------------------------------------------------------------
    def L(self, ar: str, en: str) -> str:
        return en if self.lang == "en" else ar

    def name(self, obj) -> str:
        if obj is None:
            return ""
        if self.lang == "en" and getattr(obj, "name_en", None):
            return obj.name_en
        return getattr(obj, "name_ar", None) or getattr(obj, "name", "")

    @property
    def sep(self) -> str:
        return "، " if self.lang == "ar" else ", "

    def short_teacher(self, t: Teacher) -> str:
        return t.short or self.name(t)

    def section_label(self, sid) -> str:
        s = self.sections.get(sid)
        return f"{self.name(self.grades.get(s.grade_id))} / {self.name(s)}" if s else "?"

    def target_label(self, tg) -> str:
        base = self.section_label(tg.section_id)
        return f"{base} ({self.name(self.groups.get(tg.group_id))})" if tg.group_id else base

    def stage_of_section(self, sid):
        s = self.sections.get(sid)
        g = self.grades.get(s.grade_id) if s else None
        return g.stage_id if g else None

    def section_sort_key(self, sid):
        s = self.sections[sid]
        g = self.grades.get(s.grade_id)
        st = self.stages.get(g.stage_id) if g else None
        return (st.sort_order if st else 0, g.sort_order if g else 0, s.name_ar)

    # -- filters -------------------------------------------------------------
    def section_in_scope(self, sid) -> bool:
        f = self.f
        if f.get("section_id") and sid != f["section_id"]:
            return False
        s = self.sections.get(sid)
        if s is None:
            return False
        if f.get("grade_id") and s.grade_id != f["grade_id"]:
            return False
        if f.get("stage_id") and self.stage_of_section(sid) != f["stage_id"]:
            return False
        return True

    def lesson_in_scope(self, l: Lesson) -> bool:
        f = self.f
        if f.get("subject_id") and l.subject_id != f["subject_id"]:
            return False
        if f.get("teacher_id") and f["teacher_id"] not in l.teacher_ids:
            return False
        if any(f.get(k) for k in ("section_id", "grade_id", "stage_id")):
            return any(self.section_in_scope(t.section_id) for t in l.targets)
        return True

    def scoped_lessons(self) -> list[Lesson]:
        return [l for l in self.lessons if self.lesson_in_scope(l)]

    def describe_filters(self) -> str:
        parts = []
        f = self.f
        if f.get("stage_id"):
            parts.append(f"{self.L('المرحلة', 'Stage')}: {self.name(self.stages.get(f['stage_id']))}")
        if f.get("grade_id"):
            parts.append(f"{self.L('الصف', 'Grade')}: {self.name(self.grades.get(f['grade_id']))}")
        if f.get("section_id"):
            parts.append(f"{self.L('الشعبة', 'Section')}: {self.section_label(f['section_id'])}")
        if f.get("teacher_id"):
            parts.append(f"{self.L('المعلم', 'Teacher')}: {self.name(self.teachers.get(f['teacher_id']))}")
        if f.get("subject_id"):
            parts.append(f"{self.L('المبحث', 'Subject')}: {self.name(self.subjects.get(f['subject_id']))}")
        if f.get("room_id"):
            parts.append(f"{self.L('القاعة', 'Room')}: {self.name(self.rooms.get(f['room_id']))}")
        return self.sep.join(parts)

    # -- loads ------------------------------------------------------------------
    def section_loads(self, lessons, weight) -> dict:
        """Whole-section lessons add up; groups of one division run in parallel,
        so a division counts with the load of its busiest group."""
        whole = defaultdict(int)
        by_group = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
        for l in lessons:
            for t in l.targets:
                w = weight(l)
                if t.group_id is None:
                    whole[t.section_id] += w
                else:
                    grp = self.groups.get(t.group_id)
                    by_group[t.section_id][grp.division_id if grp else None][t.group_id] += w
        out = dict(whole)
        for sid, divs in by_group.items():
            out[sid] = out.get(sid, 0) + sum(max(g.values()) for g in divs.values())
        return out

    def placed_periods(self, lesson: Lesson) -> int:
        return sum(c.duration for c in lesson.cards if c.deleted_at is None and c.weekday_id)


# ---------------------------------------------------------------------------
# Timetable grids
# ---------------------------------------------------------------------------
def _grid_for(ctx: Ctx, title: str, cards: list[Card], entry, grade_ids: list | None) -> Grid:
    day_names = [ctx.name(d) for d in ctx.days]
    per_day: list[dict[int, str | None]] = []
    grades = [ctx.grades[g] for g in grade_ids] if grade_ids else list(ctx.grades.values())
    for d in ctx.days:
        slots: dict[int, str | None] = {}
        for g in grades:
            for p, _slot in (ctx.bells.periods(g, d.id) or {}).items():
                slots.setdefault(p, None)
        if grade_ids and len(grade_ids) == 1:
            sched = resolve_schedule(ctx.tt.term_id, grades[0], d.id)
            if sched:
                for s in sched.slots:
                    if s.kind == "lesson":
                        slots[s.period_no] = f"{s.starts_at.strftime('%H:%M')}–{s.ends_at.strftime('%H:%M')}"
        per_day.append(slots)
    all_p = sorted({p for d in per_day for p in d})
    periods = []
    for p in all_p:
        times = [d[p] for d in per_day if d.get(p)]
        periods.append((p, max(set(times), key=times.count) if times else None))
    grid = Grid(title=title, days=day_names, periods=periods)
    for di, d in enumerate(per_day):
        for p in all_p:
            if p not in d:
                grid.missing.add((di, p))
    day_idx = {d.id: i for i, d in enumerate(ctx.days)}
    for c in cards:
        if not c.weekday_id or c.weekday_id not in day_idx:
            continue
        l = ctx.lesson.get(c.lesson_id)
        if l is None:
            continue
        for p in range(c.period_no, c.period_no + c.duration):
            grid.cells.setdefault((day_idx[c.weekday_id], p), []).append(entry(c, l))
    total = sum(c.duration for c in cards if c.weekday_id)
    grid.footer = ctx.L(f"مجموع الحصص: {total}", f"Total periods: {total}")
    return grid


def teacher_grids(ctx: Ctx) -> list[Grid]:
    if ctx.f.get("teacher_id"):
        ids = [ctx.f["teacher_id"]]
    else:
        ids = {tid for l in ctx.scoped_lessons() for tid in l.teacher_ids}
    teachers = sorted((ctx.teachers[i] for i in ids if i in ctx.teachers), key=lambda t: ctx.name(t))
    grids = []
    for t in teachers:
        cards = [c for c in ctx.cards if t.id in ctx.lesson[c.lesson_id].teacher_ids]

        def entry(c, l):
            lines = [ctx.name(ctx.subjects.get(l.subject_id)), ctx.sep.join(ctx.target_label(x) for x in l.targets)]
            if c.room_id:
                lines.append(ctx.name(ctx.rooms.get(c.room_id)))
            return lines
        title = f"{ctx.L('المعلمة' if t.gender == 'f' else 'المعلم', 'Teacher')}: {ctx.name(t)}"
        grids.append(_grid_for(ctx, title, cards, entry, None))
    return grids


def section_grids(ctx: Ctx) -> list[Grid]:
    ids = sorted((sid for sid in ctx.sections if ctx.section_in_scope(sid)), key=ctx.section_sort_key)
    grids = []
    for sid in ids:
        lessons = {l.id for l in ctx.lessons if any(t.section_id == sid for t in l.targets)}
        cards = [c for c in ctx.cards if c.lesson_id in lessons]

        def entry(c, l, sid=sid):
            groups = [ctx.name(ctx.groups.get(t.group_id)) for t in l.targets if t.section_id == sid and t.group_id]
            subj = ctx.name(ctx.subjects.get(l.subject_id))
            lines = [f"{subj} ({ctx.sep.join(groups)})" if groups else subj,
                     ctx.sep.join(ctx.short_teacher(ctx.teachers[x]) for x in l.teacher_ids if x in ctx.teachers)]
            if c.room_id:
                lines.append(ctx.name(ctx.rooms.get(c.room_id)))
            return lines
        title = f"{ctx.L('الشعبة', 'Section')}: {ctx.section_label(sid)}"
        grids.append(_grid_for(ctx, title, cards, entry, [ctx.sections[sid].grade_id]))
    return grids


def room_grids(ctx: Ctx) -> list[Grid]:
    ids = [ctx.f["room_id"]] if ctx.f.get("room_id") else sorted(
        {c.room_id for c in ctx.cards if c.room_id and c.weekday_id}, key=lambda r: ctx.name(ctx.rooms.get(r)))
    grids = []
    for rid in ids:
        room = ctx.rooms.get(rid)
        if room is None:
            continue
        cards = [c for c in ctx.cards if c.room_id == rid]

        def entry(c, l):
            return [ctx.name(ctx.subjects.get(l.subject_id)),
                    ctx.sep.join(ctx.target_label(x) for x in l.targets),
                    ctx.sep.join(ctx.short_teacher(ctx.teachers[x]) for x in l.teacher_ids if x in ctx.teachers)]
        grids.append(_grid_for(ctx, f"{ctx.L('القاعة', 'Room')}: {ctx.name(room)}", cards, entry, None))
    return grids


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------
def teacher_sections(ctx: Ctx) -> Table:
    lessons = ctx.scoped_lessons()
    matrix = defaultdict(lambda: defaultdict(int))
    sections = set()
    for l in lessons:
        for sid in {t.section_id for t in l.targets if ctx.section_in_scope(t.section_id)}:
            sections.add(sid)
            for tid in l.teacher_ids:
                if ctx.f.get("teacher_id") and tid != ctx.f["teacher_id"]:
                    continue
                matrix[tid][sid] += l.periods_per_week
    cols = sorted(sections, key=ctx.section_sort_key)
    teachers = sorted((t for t in matrix if t in ctx.teachers), key=lambda t: ctx.name(ctx.teachers[t]))
    rows = []
    for tid in teachers:
        vals = [matrix[tid].get(sid) or None for sid in cols]
        rows.append([ctx.name(ctx.teachers[tid]), *vals, sum(v or 0 for v in vals)])
    totals = [ctx.L("المجموع", "Total"), *[sum(matrix[t].get(s, 0) for t in teachers) or None for s in cols],
              sum(sum(matrix[t].values()) for t in teachers)]
    return Table(title=ctx.L("عدد الحصص الأسبوعية لكل معلم في كل شعبة", "Weekly periods per teacher and section"),
                 columns=[ctx.L("المعلم", "Teacher"), *[ctx.section_label(s) for s in cols], ctx.L("المجموع", "Total")],
                 rows=rows, numeric=set(range(1, len(cols) + 2)), totals=totals)


def teacher_subjects(ctx: Ctx) -> Table:
    agg = defaultdict(lambda: {"periods": 0, "sections": set()})
    for l in ctx.scoped_lessons():
        for tid in l.teacher_ids:
            if ctx.f.get("teacher_id") and tid != ctx.f["teacher_id"]:
                continue
            a = agg[(l.subject_id, tid)]
            a["periods"] += l.periods_per_week
            a["sections"].update(ctx.target_label(t) for t in l.targets)
    sep = ctx.sep
    rows = []
    for (sid, tid), a in sorted(agg.items(), key=lambda kv: (ctx.name(ctx.subjects.get(kv[0][0])), ctx.name(ctx.teachers.get(kv[0][1])))):
        rows.append([ctx.name(ctx.subjects.get(sid)), ctx.name(ctx.teachers.get(tid)), sep.join(sorted(a["sections"])),
                     len(a["sections"]), a["periods"]])
    return Table(title=ctx.L("المعلمون المسندون إلى كل مبحث", "Teachers assigned to each subject"),
                 columns=[ctx.L("المبحث", "Subject"), ctx.L("المعلم", "Teacher"), ctx.L("الشعب", "Sections"),
                          ctx.L("عدد الشعب", "Sections"), ctx.L("الحصص أسبوعياً", "Periods/week")],
                 rows=rows, numeric={3, 4}, totals=[ctx.L("المجموع", "Total"), "", "", None, sum(r[4] for r in rows)])


def stats_teachers(ctx: Ctx) -> Table:
    assigned, placed, secs, subs = defaultdict(int), defaultdict(int), defaultdict(set), defaultdict(set)
    for l in ctx.scoped_lessons():
        for tid in l.teacher_ids:
            assigned[tid] += l.periods_per_week
            placed[tid] += ctx.placed_periods(l)
            secs[tid].update(t.section_id for t in l.targets)
            subs[tid].add(ctx.name(ctx.subjects.get(l.subject_id)))
    ids = [ctx.f["teacher_id"]] if ctx.f.get("teacher_id") else list(assigned)
    sep = ctx.sep
    rows = []
    for tid in sorted((i for i in ids if i in ctx.teachers), key=lambda i: ctx.name(ctx.teachers[i])):
        t = ctx.teachers[tid]
        target = t.target_weekly_periods
        rows.append([ctx.name(t), sep.join(sorted(ctx.name(s) for s in t.stages)), sep.join(sorted(subs[tid])),
                     len(secs[tid]), assigned[tid], placed[tid], target,
                     (assigned[tid] - target) if target is not None else None,
                     (assigned[tid] / target) if target else None])
    total = lambda i: sum(r[i] or 0 for r in rows)  # noqa: E731
    return Table(title=ctx.L("النصاب المُسنَد مقارنةً بالنصاب المطلوب", "Assigned load vs. target"),
                 columns=[ctx.L("المعلم", "Teacher"), ctx.L("المراحل", "Stages"), ctx.L("المباحث", "Subjects"),
                          ctx.L("عدد الشعب", "Sections"), ctx.L("المُسنَد", "Assigned"), ctx.L("المُدرَج في الجدول", "Placed"),
                          ctx.L("النصاب", "Target"), ctx.L("الفرق", "Difference"), ctx.L("نسبة النصاب", "Load %")],
                 rows=rows, numeric={3, 4, 5, 6, 7}, percent={8},
                 totals=[ctx.L("المجموع", "Total"), "", "", None, total(4), total(5), total(6), None, None])


def stats_subjects(ctx: Ctx) -> Table:
    agg = defaultdict(lambda: {"teachers": set(), "sections": set(), "periods": 0, "placed": 0})
    for l in ctx.scoped_lessons():
        a = agg[l.subject_id]
        a["teachers"].update(l.teacher_ids)
        a["sections"].update(t.section_id for t in l.targets)
        a["periods"] += l.periods_per_week
        a["placed"] += ctx.placed_periods(l)
    rows = [[ctx.name(ctx.subjects.get(sid)), len(a["teachers"]), len(a["sections"]), a["periods"], a["placed"],
             (a["placed"] / a["periods"]) if a["periods"] else None]
            for sid, a in sorted(agg.items(), key=lambda kv: ctx.name(ctx.subjects.get(kv[0])))]
    return Table(title=ctx.L("المعلمون والحصص لكل مبحث", "Teachers and periods per subject"),
                 columns=[ctx.L("المبحث", "Subject"), ctx.L("عدد المعلمين", "Teachers"), ctx.L("عدد الشعب", "Sections"),
                          ctx.L("الحصص أسبوعياً", "Periods/week"), ctx.L("المُدرَج في الجدول", "Placed"),
                          ctx.L("نسبة الإدراج", "Placed %")],
                 rows=rows, numeric={1, 2, 3, 4}, percent={5},
                 totals=[ctx.L("المجموع", "Total"), None, None, sum(r[3] for r in rows), sum(r[4] for r in rows), None])


def stats_sections(ctx: Ctx) -> Table:
    lessons = ctx.scoped_lessons()
    required = ctx.section_loads(lessons, lambda l: l.periods_per_week)
    placed = ctx.section_loads(lessons, ctx.placed_periods)
    rows = []
    for sid in sorted((s for s in ctx.sections if ctx.section_in_scope(s)), key=ctx.section_sort_key):
        grade = ctx.grades[ctx.sections[sid].grade_id]
        cap = sum(len(ctx.bells.periods(grade, d.id) or {}) for d in ctx.days)
        req, pl = required.get(sid, 0), placed.get(sid, 0)
        rows.append([ctx.section_label(sid), ctx.name(ctx.stages.get(grade.stage_id)), cap, req, pl,
                     (pl / req) if req else None, cap - req])
    return Table(title=ctx.L("الحصص المطلوبة والمُدرَجة لكل شعبة", "Required and placed periods per section"),
                 columns=[ctx.L("الشعبة", "Section"), ctx.L("المرحلة", "Stage"), ctx.L("الخانات الأسبوعية", "Weekly slots"),
                          ctx.L("الحصص المطلوبة", "Required"), ctx.L("المُدرَج في الجدول", "Placed"),
                          ctx.L("نسبة التغطية", "Coverage"), ctx.L("الخانات الفائضة", "Spare slots")],
                 rows=rows, numeric={2, 3, 4, 6}, percent={5},
                 totals=[ctx.L("المجموع", "Total"), "", sum(r[2] for r in rows), sum(r[3] for r in rows),
                         sum(r[4] for r in rows), None, sum(r[6] for r in rows)])


def build_report(tt: Timetable, kind: str, lang: str, filters: dict) -> Report:
    ctx = Ctx(tt, lang, filters)
    school = db.session.scalars(select(School)).first()
    rep = Report(
        kind=kind, lang=lang, title=TITLES[kind][1 if lang == "en" else 0],
        school_name=(school.name_en if lang == "en" and school and school.name_en else (school.name_ar if school else "")),
        timetable_name=tt.name, filters=ctx.describe_filters(),
        generated_at=datetime.now(ZoneInfo(os.environ.get("APP_TIMEZONE", "Asia/Amman"))).strftime("%Y-%m-%d %H:%M"),
    )
    if kind == "teacher-timetable":
        rep.grids = teacher_grids(ctx)
    elif kind == "section-timetable":
        rep.grids = section_grids(ctx)
    elif kind == "room-timetable":
        rep.grids = room_grids(ctx)
    elif kind == "teacher-sections":
        rep.tables = [teacher_sections(ctx)]
    elif kind == "teacher-subjects":
        rep.tables = [teacher_subjects(ctx)]
    elif kind == "stats-teachers":
        rep.tables = [stats_teachers(ctx)]
    elif kind == "stats-subjects":
        rep.tables = [stats_subjects(ctx)]
    elif kind == "stats-sections":
        rep.tables = [stats_sections(ctx)]
    return rep


def parse_filters(args) -> dict:
    out = {}
    for k in FILTER_KEYS:
        v = args.get(k)
        if v:
            out[k] = uuid.UUID(v)
    return out
