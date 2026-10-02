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
    "teacher-timetable", "section-timetable", "room-timetable", "subject-timetable",
    "stage-timetable", "teachers-master", "free-teachers",
    "teacher-sections", "teacher-subjects", "teacher-daily",
    "stats-teachers", "stats-subjects", "stats-sections", "load-status",
    "exam-schedule", "invigilation", "duty-roster", "duty-teachers",
    "cover-daily", "cover-stats", "absence-log",
)
# Tables that are a plain matrix (row label × column label) and can be turned on their side.
MATRIX_KINDS = {"teacher-sections", "teacher-daily", "duty-roster"}
SHOW_KEYS = ("teacher", "room", "times", "groups", "section", "footer")
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
    "subject-timetable": ("جدول حصص المبحث", "Subject timetable"),
    "stage-timetable": ("الجدول العام للمرحلة (الشعب)", "Master timetable (sections)"),
    "teachers-master": ("الجدول العام للمعلمين", "Master timetable (teachers)"),
    "free-teachers": ("المعلمون المتاحون في كل حصة (لحصص الإشغال)", "Free teachers per period (for cover)"),
    "teacher-daily": ("توزيع حصص المعلم على أيام الأسبوع", "Teacher periods per day"),
    "load-status": ("اكتمال النصاب حسب القواعد", "Load status by rule"),
    "exam-schedule": ("جدول الامتحانات", "Exam timetable"),
    "invigilation": ("جدول المراقبة على الامتحانات", "Invigilation schedule"),
    "duty-roster": ("جدول المناوبة", "Duty roster"),
    "duty-teachers": ("مناوبات كل معلم", "Duties per teacher"),
    "cover-daily": ("حصص الإشغال اليومية", "Daily cover sheet"),
    "cover-stats": ("حصص الإشغال والغياب لكل معلم", "Cover and absence per teacher"),
    "absence-log": ("سجل غياب المعلمين", "Teacher absence log"),
}
DATE_KEYS = ("date", "date_from", "date_to")


@dataclass
class Grid:
    title: str
    days: list[str]
    periods: list[tuple[int, str | None]]            # (period number, "07:45–08:30" or None)
    cells: dict = field(default_factory=dict)        # (day_idx, period_no) -> list[list[str]]
    missing: set = field(default_factory=set)        # (day_idx, period_no) that don't exist that day
    footer: str | None = None
    subtitle: str | None = None
    day_notes: list = field(default_factory=list)    # per day: own times when they differ from the header


def grid_matrix(g: "Grid", layout: str, rtl: bool, raw: bool = False):
    """Lay a grid out for printing. Returns (corner, column_headers, rows) where rows are
    (row_label, [cell_text | None, ...], [missing_flags]). layout "rows" = days as rows (ASC print style)."""
    period_label = lambda p, tl: f"{p}\n{tl}" if tl else str(p)  # noqa: E731
    if raw:   # entries kept separate so the renderer can style the subject line and the teacher line apart
        text = lambda d, p: g.cells.get((d, p)) or None  # noqa: E731
    else:
        text = lambda d, p: "\n".join("\n".join(x for x in e if x) for e in g.cells.get((d, p), [])) or None  # noqa: E731
    note = lambda d: g.day_notes[d] if d < len(g.day_notes) and g.day_notes[d] else None  # noqa: E731
    if layout == "cols":
        corner = "الحصة" if rtl else "Period"
        heads = [f"{day}\n{note(d)}" if note(d) else day for d, day in enumerate(g.days)]
        rows = [(period_label(p, tl), [text(d, p) for d in range(len(g.days))],
                 [(d, p) in g.missing for d in range(len(g.days))]) for p, tl in g.periods]
    else:
        corner = "اليوم" if rtl else "Day"
        heads = [period_label(p, tl) for p, tl in g.periods]
        rows = [(f"{day}\n{note(d)}" if note(d) else day, [text(d, p) for p, _ in g.periods],
                 [(d, p) in g.missing for p, _ in g.periods]) for d, day in enumerate(g.days)]
    return corner, heads, rows


@dataclass
class Table:
    title: str
    columns: list[str]
    rows: list[list]
    numeric: set[int] = field(default_factory=set)
    percent: set[int] = field(default_factory=set)
    totals: list | None = None
    group_header: list | None = None                  # [(label, span), …] row drawn above the column headers
    cell_colors: dict = field(default_factory=dict)   # (row, col) -> "#rrggbb", used only in the colour style
    compact: bool = False                             # many narrow columns (master timetables)
    subtitle: str | None = None
    row_groups: list = field(default_factory=list)    # row indices that start a new group (a new day)


def transpose(t: Table, total_label: str) -> Table:
    """Swap rows and columns of a matrix table; a «total» column becomes the totals row and back."""
    rows = [list(r) for r in t.rows]
    cols = list(t.columns)
    has_total_col = cols and cols[-1] == total_label
    new_cols = [cols[0]] + [r[0] for r in rows] + ([total_label] if t.totals else [])
    new_rows = []
    for j in range(1, len(cols)):
        new_rows.append([cols[j]] + [r[j] for r in rows] + ([t.totals[j]] if t.totals else []))
    totals = None
    if has_total_col and new_rows:
        totals = new_rows.pop()
        totals[0] = total_label
    colors = {(j - 1, i + 1): c for (i, j), c in t.cell_colors.items() if j >= 1}
    return Table(title=t.title, columns=new_cols, rows=new_rows, numeric=set(range(1, len(new_cols))) if t.numeric else set(),
                 totals=totals, cell_colors=colors, compact=t.compact, subtitle=t.subtitle)


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
    layout: str = "rows"   # timetables: "rows" = days as rows (ASC print style), "cols" = days as columns
    style: str = "plain"   # "plain": black on white, no shading (best for black-and-white printers); "color"
    signature: list = field(default_factory=list)   # signature boxes printed under every page's content
    notes: list = field(default_factory=list)       # lines printed after the tables
    orientable: bool = False                        # the screen may offer to turn this report on its side

    @property
    def rtl(self) -> bool:
        return self.lang == "ar"

    def to_json(self) -> dict:
        return {
            "kind": self.kind, "lang": self.lang, "layout": self.layout, "style": self.style, "title": self.title,
            "school_name": self.school_name, "signature": self.signature, "notes": self.notes,
            "orientable": self.orientable,
            "timetable_name": self.timetable_name, "filters": self.filters, "generated_at": self.generated_at,
            "grids": [{
                "title": g.title, "days": g.days, "periods": [{"no": n, "time": t} for n, t in g.periods],
                "cells": [{"day": d, "period": p, "entries": v} for (d, p), v in sorted(g.cells.items())],
                "missing": [{"day": d, "period": p} for d, p in sorted(g.missing)], "footer": g.footer,
                "subtitle": g.subtitle, "day_notes": g.day_notes,
            } for g in self.grids],
            "tables": [{"title": t.title, "columns": t.columns, "rows": t.rows, "numeric": sorted(t.numeric),
                        "percent": sorted(t.percent), "totals": t.totals,
                        "group_header": [{"label": a, "span": b} for a, b in t.group_header] if t.group_header else None,
                        "cell_colors": [{"row": r, "col": c, "color": v} for (r, c), v in sorted(t.cell_colors.items())]
                        if self.style == "color" else [],
                        "compact": t.compact, "subtitle": t.subtitle, "row_groups": t.row_groups} for t in self.tables],
        }


# ---------------------------------------------------------------------------
class Ctx:
    """Everything a report needs, loaded once."""

    def __init__(self, tt: Timetable, lang: str, filters: dict, show: set | None = None):
        self.tt, self.lang, self.f = tt, lang, filters
        self.show = set(SHOW_KEYS) if show is None else show
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
        if not s:
            return "?"
        grade, sec = self.name(self.grades.get(s.grade_id)), self.name(s)
        # aSc-style section names already contain the grade ("10 A"): don't print "10 / 10 A"
        return sec if grade and sec.replace(" ", "").startswith(grade.replace(" ", "")) else f"{grade} / {sec}"

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
        if f.get("date"):
            parts.append(f"{self.L('التاريخ', 'Date')}: {f['date'].isoformat()}")
        if f.get("date_from") or f.get("date_to"):
            parts.append(f"{self.L('من', 'From')} {f['date_from'].isoformat() if f.get('date_from') else '…'} "
                         f"{self.L('إلى', 'to')} {f['date_to'].isoformat() if f.get('date_to') else '…'}")
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
    spans: list[str | None] = []
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
                lessons_ = [s for s in sched.slots if s.kind == "lesson"]
                spans.append(f"{lessons_[0].starts_at.strftime('%H:%M')}–{lessons_[-1].ends_at.strftime('%H:%M')}"
                             if lessons_ else None)
            else:
                spans.append(None)
        per_day.append(slots)
    all_p = sorted({p for d in per_day for p in d})
    periods = []
    for p in all_p:
        times = [d[p] for d in per_day if d.get(p)]
        periods.append((p, max(set(times), key=times.count) if times else None))
    grid = Grid(title=title, days=day_names, periods=periods)
    # A day whose times differ from the header (e.g. a short Tuesday) shows its own start–end.
    if spans:
        header = {p: tl for p, tl in periods}
        grid.day_notes = [spans[i] if any(d.get(p) and d.get(p) != header.get(p) for p in d) else None
                          for i, d in enumerate(per_day)]
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
    if "times" not in ctx.show:
        grid.periods = [(p, None) for p, _t in grid.periods]
        grid.day_notes = []
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
            lines = [ctx.name(ctx.subjects.get(l.subject_id))]
            if "section" in ctx.show:
                lines.append(ctx.sep.join(ctx.target_label(x) if "groups" in ctx.show else ctx.section_label(x.section_id)
                                          for x in l.targets))
            if c.room_id and "room" in ctx.show:
                lines.append(ctx.name(ctx.rooms.get(c.room_id)))
            return lines
        title = f"{ctx.L('المعلمة' if t.gender == 'f' else 'المعلم', 'Teacher')}: {ctx.name(t)}"
        grid = _grid_for(ctx, title, cards, entry, None)
        mine = [l for l in ctx.lessons if t.id in l.teacher_ids]
        assigned = sum(l.periods_per_week for l in mine)
        placed = sum(c.duration for c in cards if c.weekday_id)
        subjects = sorted({ctx.name(ctx.subjects.get(l.subject_id)) for l in mine if ctx.subjects.get(l.subject_id)})
        parts = [ctx.L(f"النصاب الأسبوعي: {t.target_weekly_periods}", f"Weekly load: {t.target_weekly_periods}")
                 if t.target_weekly_periods else None,
                 ctx.L(f"الحصص المُسنَدة: {assigned}", f"Assigned periods: {assigned}"),
                 ctx.L(f"الموزَّعة في الجدول: {placed}", f"Placed: {placed}")]
        if t.target_weekly_periods:
            diff = assigned - t.target_weekly_periods
            if diff:
                parts.append(ctx.L(f"{'زيادة' if diff > 0 else 'نقص'}: {abs(diff)}", f"{'Over' if diff > 0 else 'Under'}: {abs(diff)}"))
        grid.footer = " — ".join(x for x in parts if x)
        if subjects:
            grid.subtitle = f"{ctx.L('المباحث', 'Subjects')}: {ctx.sep.join(subjects)}"
        grids.append(grid)
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
            lines = [f"{subj} ({ctx.sep.join(groups)})" if groups and "groups" in ctx.show else subj]
            if "teacher" in ctx.show:
                lines.append(ctx.sep.join(ctx.short_teacher(ctx.teachers[x]) for x in l.teacher_ids if x in ctx.teachers))
            if c.room_id and "room" in ctx.show:
                lines.append(ctx.name(ctx.rooms.get(c.room_id)))
            return lines
        title = f"{ctx.L('الشعبة', 'Section')}: {ctx.section_label(sid)}"
        grid = _grid_for(ctx, title, cards, entry, [ctx.sections[sid].grade_id])
        ct = ctx.teachers.get(ctx.sections[sid].class_teacher_id)
        if ct:
            grid.subtitle = f"{ctx.L('مربي الصف', 'Class teacher')}: {ctx.name(ct)}"
        grids.append(grid)
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
            lines = [ctx.name(ctx.subjects.get(l.subject_id))]
            if "section" in ctx.show:
                lines.append(ctx.sep.join(ctx.target_label(x) for x in l.targets))
            if "teacher" in ctx.show:
                lines.append(ctx.sep.join(ctx.short_teacher(ctx.teachers[x]) for x in l.teacher_ids if x in ctx.teachers))
            return lines
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
    from app.rules.loads import statuses_by_teacher
    status = statuses_by_teacher(ctx.tt)
    colors = {}
    for tid in sorted((i for i in ids if i in ctx.teachers), key=lambda i: ctx.name(ctx.teachers[i])):
        t = ctx.teachers[tid]
        target = t.target_weekly_periods
        st = status.get(str(tid))
        label = ((st["label_en"] if ctx.lang == "en" else st["label"]) if st else "") or ""
        if st and st["status"] in ("under", "over"):
            label = f"{label} ({st['delta']})"
        rows.append([ctx.name(t), sep.join(sorted(ctx.name(s) for s in t.stages)), sep.join(sorted(subs[tid])),
                     len(secs[tid]), assigned[tid], placed[tid], target,
                     (assigned[tid] - target) if target is not None else None,
                     (assigned[tid] / target) if target else None, label])
        if st and st.get("color"):
            colors[(len(rows) - 1, 9)] = st["color"]
    total = lambda i: sum(r[i] or 0 for r in rows)  # noqa: E731
    return Table(title=ctx.L("النصاب المُسنَد مقارنةً بالنصاب المطلوب", "Assigned load vs. target"),
                 columns=[ctx.L("المعلم", "Teacher"), ctx.L("المراحل", "Stages"), ctx.L("المباحث", "Subjects"),
                          ctx.L("عدد الشعب", "Sections"), ctx.L("المُسنَد", "Assigned"), ctx.L("المُدرَج في الجدول", "Placed"),
                          ctx.L("النصاب", "Target"), ctx.L("الفرق", "Difference"), ctx.L("نسبة النصاب", "Load %"),
                          ctx.L("حالة النصاب", "Load status")],
                 rows=rows, numeric={3, 4, 5, 6, 7}, percent={8}, cell_colors=colors,
                 totals=[ctx.L("المجموع", "Total"), "", "", None, total(4), total(5), total(6), None, None, ""])


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


def subject_grids(ctx: Ctx) -> list[Grid]:
    ids = [ctx.f["subject_id"]] if ctx.f.get("subject_id") else sorted(
        {l.subject_id for l in ctx.scoped_lessons()}, key=lambda i: ctx.name(ctx.subjects.get(i)))
    grids = []
    for sub_id in ids:
        subj = ctx.subjects.get(sub_id)
        if subj is None:
            continue
        lessons = {l.id for l in ctx.scoped_lessons() if l.subject_id == sub_id}
        cards = [c for c in ctx.cards if c.lesson_id in lessons]

        def entry(c, l):
            lines = [ctx.sep.join(ctx.target_label(x) if "groups" in ctx.show else ctx.section_label(x.section_id)
                                  for x in l.targets)]
            if "teacher" in ctx.show:
                lines.append(ctx.sep.join(ctx.short_teacher(ctx.teachers[x]) for x in l.teacher_ids if x in ctx.teachers))
            if c.room_id and "room" in ctx.show:
                lines.append(ctx.name(ctx.rooms.get(c.room_id)))
            return lines
        grid = _grid_for(ctx, f"{ctx.L('المبحث', 'Subject')}: {ctx.name(subj)}", cards, entry, None)
        teachers = sorted({ctx.name(ctx.teachers[t]) for l in ctx.lessons if l.id in lessons for t in l.teacher_ids
                           if t in ctx.teachers})
        if teachers:
            grid.subtitle = f"{ctx.L('المعلمون', 'Teachers')}: {ctx.sep.join(teachers)}"
        grids.append(grid)
    return grids


def _slot_columns(ctx: Ctx, grade_ids=None):
    """[(day_index, day, period_no)] for every lesson period of the school week (union over the grades)."""
    grades = [ctx.grades[g] for g in grade_ids] if grade_ids else list(ctx.grades.values())
    out = []
    for di, d in enumerate(ctx.days):
        ps = set()
        for g in grades:
            ps.update((ctx.bells.periods(g, d.id) or {}).keys())
        out += [(di, d, p) for p in sorted(ps)]
    return out


def _cell_text(ctx: Ctx, cards, slot, line):
    di, d, p = slot
    texts = []
    for c in cards:
        if c.weekday_id == d.id and c.period_no <= p < c.period_no + c.duration:
            l = ctx.lesson.get(c.lesson_id)
            if l is not None:
                texts.append(line(c, l))
    return "\n".join(t for t in texts if t) or None


def _short_subject(ctx: Ctx, sid) -> str:
    s = ctx.subjects.get(sid)
    if s is None:
        return ""
    short = s.short_en if ctx.lang == "en" else s.short_ar
    if short:
        return short
    name = ctx.name(s)
    if ctx.lang != "en":   # «اللغة العربية» → «العربية»، «التربية الإسلامية» → «الإسلامية» for the narrow master sheet
        for prefix in ("اللغة ", "التربية ", "مبحث "):
            if name.startswith(prefix) and len(name) > len(prefix) + 2:
                return name[len(prefix):]
    return name


def master_table(ctx: Ctx, who: str, layout: str) -> Table:
    """The whole stage on one sheet, like ASC's main screen: one line per section (or teacher)
    and one column per day × period — or, turned on its side, one line per day × period."""
    if who == "sections":
        entities = sorted((sid for sid in ctx.sections if ctx.section_in_scope(sid)), key=ctx.section_sort_key)
        label = ctx.section_label
        grade_ids = list({ctx.sections[s].grade_id for s in entities}) or None

        def cards_of(sid):
            ls = {l.id for l in ctx.lessons if any(t.section_id == sid for t in l.targets) and ctx.lesson_in_scope(l)}
            return [c for c in ctx.cards if c.lesson_id in ls]

        def line(c, l):
            parts = [_short_subject(ctx, l.subject_id)]
            if "teacher" in ctx.show:
                parts.append("/".join(ctx.short_teacher(ctx.teachers[x]) for x in l.teacher_ids if x in ctx.teachers))
            return "\n".join(x for x in parts if x)
        corner = ctx.L("الشعبة", "Section")
    else:
        ids = {tid for l in ctx.scoped_lessons() for tid in l.teacher_ids}
        if ctx.f.get("teacher_id"):
            ids = {ctx.f["teacher_id"]}
        entities = sorted((i for i in ids if i in ctx.teachers), key=lambda i: ctx.name(ctx.teachers[i]))
        label = lambda i: ctx.short_teacher(ctx.teachers[i]) if layout == "cols" else ctx.name(ctx.teachers[i])  # noqa: E731
        grade_ids = None

        def cards_of(tid):
            return [c for c in ctx.cards if tid in ctx.lesson[c.lesson_id].teacher_ids]

        def line(c, l):
            secs = ctx.sep.join(ctx.section_label(x.section_id) for x in l.targets)
            return f"{secs} · {_short_subject(ctx, l.subject_id)}" if "section" in ctx.show else _short_subject(ctx, l.subject_id)
        corner = ctx.L("المعلم", "Teacher")
    slots = _slot_columns(ctx, grade_ids)
    cards = {e: cards_of(e) for e in entities}
    title = ctx.describe_filters() or ctx.L("جميع المراحل", "All stages")
    if layout == "cols":
        cols = [ctx.L("اليوم / الحصة", "Day / period")] + [label(e) for e in entities]
        rows = [[f"{ctx.name(d)} — {p}"] + [_cell_text(ctx, cards[e], (di, d, p), line) for e in entities]
                for di, d, p in slots]
        starts = [i for i, (di, _d, _p) in enumerate(slots) if i == 0 or slots[i - 1][0] != di]
        return Table(title=title, columns=cols, rows=rows, compact=True, row_groups=starts)
    group = []
    for di, d in enumerate(ctx.days):
        n = sum(1 for x in slots if x[0] == di)
        if n:
            group.append((ctx.name(d), n))
    cols = [corner] + [str(p) for _di, _d, p in slots]
    rows = [[label(e)] + [_cell_text(ctx, cards[e], sl, line) for sl in slots] for e in entities]
    return Table(title=title, columns=cols, rows=rows, group_header=[("", 1)] + group, compact=True)


def free_teacher_grid(ctx: Ctx) -> list[Grid]:
    """Who is free at each period (not teaching and not marked unavailable) — the list to pick a
    substitute from. Only teachers of the filtered stage / subject when a filter is set."""
    from app.models import Availability
    pool = [t for t in ctx.teachers.values()
            if (not ctx.f.get("stage_id") or ctx.f["stage_id"] in {s.id for s in t.stages})
            and (not ctx.f.get("subject_id") or ctx.f["subject_id"] in {s.id for s in t.subjects}
                 or any(ctx.f["subject_id"] == l.subject_id and t.id in l.teacher_ids for l in ctx.lessons))]
    pool = [t for t in pool if any(t.id in l.teacher_ids for l in ctx.lessons) or t.target_weekly_periods]
    pool.sort(key=lambda t: ctx.name(t))
    busy = defaultdict(set)
    for c in ctx.cards:
        if c.weekday_id:
            for tid in ctx.lesson[c.lesson_id].teacher_ids:
                for p in range(c.period_no, c.period_no + c.duration):
                    busy[(c.weekday_id, p)].add(tid)
    for a in db.session.scalars(select(Availability).where(Availability.timetable_id == ctx.tt.id,
                                                           Availability.entity_type == "teacher")):
        busy[(a.weekday_id, a.period_no)].add(a.entity_id)
    day_only = None
    if ctx.f.get("date"):   # one school day: absent teachers and those already covering are not free either
        from app.models import Substitution, TeacherAbsence
        from app.rules.cover import school_weekday
        d0 = ctx.f["date"]
        wd = school_weekday(d0)
        day_only = wd.id if wd else None
        if wd:
            for a in db.session.scalars(select(TeacherAbsence).where(TeacherAbsence.date_from <= d0, TeacherAbsence.date_to >= d0)):
                for p in range(1, 20):
                    if a.covers(d0, p):
                        busy[(wd.id, p)].add(a.teacher_id)
            for sub in db.session.scalars(select(Substitution).where(Substitution.timetable_id == ctx.tt.id,
                                                                     Substitution.date == d0, Substitution.kind == "cover")):
                busy[(wd.id, sub.period_no)].add(sub.substitute_teacher_id)
    grid = _grid_for(ctx, ctx.L("المعلمون المتاحون في كل حصة", "Teachers free in each period"), [], lambda c, l: [], None)
    if day_only is not None or ctx.f.get("date"):
        keep = [i for i, d in enumerate(ctx.days) if d.id == day_only]
        grid.days = [grid.days[i] for i in keep]
        grid.missing = {(keep.index(di), p) for di, p in grid.missing if di in keep}
        grid.day_notes = [grid.day_notes[i] for i in keep] if grid.day_notes else []
        days = [ctx.days[i] for i in keep]
    else:
        days = ctx.days
    for di, d in enumerate(days):
        for p, _tl in grid.periods:
            if (di, p) in grid.missing:
                continue
            free = [ctx.short_teacher(t) for t in pool if t.id not in busy[(d.id, p)]]
            if free:
                grid.cells[(di, p)] = [[ctx.L(f"المتاحون: {len(free)}", f"Free: {len(free)}"), ctx.sep.join(free)]]
    grid.footer = ctx.L(f"عدد المعلمين في القائمة: {len(pool)}", f"Teachers considered: {len(pool)}")
    return [grid]


def teacher_daily(ctx: Ctx) -> Table:
    per = defaultdict(lambda: defaultdict(set))
    for c in ctx.cards:
        if not c.weekday_id:
            continue
        l = ctx.lesson[c.lesson_id]
        if not ctx.lesson_in_scope(l):
            continue
        for tid in l.teacher_ids:
            per[tid][c.weekday_id].update(range(c.period_no, c.period_no + c.duration))
    ids = [ctx.f["teacher_id"]] if ctx.f.get("teacher_id") else [t for t in per]
    rows, colors = [], {}
    for i, tid in enumerate(sorted((x for x in ids if x in ctx.teachers), key=lambda x: ctx.name(ctx.teachers[x]))):
        counts = [len(per[tid].get(d.id, ())) or None for d in ctx.days]
        gaps = 0
        for d in ctx.days:
            ps = sorted(per[tid].get(d.id, ()))
            if ps:
                gaps += (ps[-1] - ps[0] + 1) - len(ps)
        t = ctx.teachers[tid]
        busiest = max([c or 0 for c in counts] or [0])
        if t.max_periods_per_day is not None and busiest > t.max_periods_per_day:
            for j, c in enumerate(counts):
                if (c or 0) > t.max_periods_per_day:
                    colors[(i, j + 1)] = "#fde68a"
        rows.append([ctx.name(t), *counts, sum(c or 0 for c in counts), gaps,
                     sum(1 for c in counts if c)])
    n = len(ctx.days)
    totals = [ctx.L("المجموع", "Total"), *[sum(r[j + 1] or 0 for r in rows) or None for j in range(n)],
              sum(r[n + 1] for r in rows), sum(r[n + 2] for r in rows), None]
    return Table(title=ctx.L("عدد الحصص في كل يوم والفجوات", "Periods per day and gaps"),
                 columns=[ctx.L("المعلم", "Teacher"), *[ctx.name(d) for d in ctx.days], ctx.L("المجموع", "Total"),
                          ctx.L("الفجوات", "Gaps"), ctx.L("أيام الدوام", "Days")],
                 rows=rows, numeric=set(range(1, n + 4)), totals=totals, cell_colors=colors)


def load_status_tables(ctx: Ctx) -> tuple[list[Table], list[str]]:
    from app.rules.loads import evaluate
    data = evaluate(ctx.tt)
    en = ctx.lang == "en"
    rows, colors = [], {}
    want = ctx.f.get("teacher_id")
    for r in data["teachers"]:
        if want and r["teacher_id"] != str(want):
            continue
        t = ctx.teachers.get(uuid.UUID(r["teacher_id"]))
        if ctx.f.get("stage_id") and t and ctx.f["stage_id"] not in {s.id for s in t.stages}:
            continue
        if ctx.f.get("subject_id") and ctx.name(ctx.subjects.get(ctx.f["subject_id"])) not in r["subjects"] \
                and not (t and ctx.f["subject_id"] in {s.id for s in t.subjects}):
            continue
        status = (r["label_en"] if en else r["label"]) or "—"
        diff = (-r["delta"] if r["status"] == "under" else r["delta"]) if r["status"] in ("under", "over") else 0
        rows.append([ctx.name(t) if t else r["name"], ctx.sep.join(r["subjects"]), r["assigned"], r["placed"],
                     r["expected_en"] if en else r["expected"], status, diff if r["status"] != "none" else None,
                     r["rule_name"] or (ctx.L("نصاب المعلم", "Teacher's own target") if r["default_rule"] else "")])
        if r["color"]:
            colors[(len(rows) - 1, 5)] = r["color"]
    t1 = Table(title=ctx.L("حالة النصاب لكل معلم", "Load status per teacher"),
               columns=[ctx.L("المعلم", "Teacher"), ctx.L("المباحث", "Subjects"), ctx.L("المُسنَد", "Assigned"),
                        ctx.L("المُدرَج في الجدول", "Placed"), ctx.L("النصاب المطلوب", "Expected"),
                        ctx.L("الحالة", "Status"), ctx.L("الفرق", "Difference"), ctx.L("القاعدة", "Rule")],
               rows=rows, numeric={2, 3, 6}, cell_colors=colors)
    tables = [t1]
    if data["groups"]:
        g_rows, g_colors = [], {}
        for i, gr in enumerate(data["groups"]):
            g_rows.append([gr["name"] or (gr["scope_en"] if en else gr["scope"]), gr["teachers"], gr["actual"],
                           gr["expected"], gr["counts"]["ok"], gr["counts"]["under"], gr["counts"]["over"],
                           gr["label"] or "—"])
            if gr["color"]:
                g_colors[(i, 7)] = gr["color"]
        tables.append(Table(title=ctx.L("ملخص القواعد (المبحث / المرحلة / المعلمون)", "Summary per rule"),
                            columns=[ctx.L("القاعدة", "Rule"), ctx.L("عدد المعلمين", "Teachers"),
                                     ctx.L("مجموع الحصص", "Periods"), ctx.L("المطلوب", "Expected"),
                                     ctx.L("مكتمل", "Complete"), ctx.L("نقص", "Under"), ctx.L("زيادة", "Over"),
                                     ctx.L("الحالة", "Status")],
                            rows=g_rows, numeric={1, 2, 4, 5, 6}, cell_colors=g_colors))
    s = data["summary"]
    note = ctx.L(f"مكتمل: {s['ok']} — نقص: {s['under']} — زيادة: {s['over']} — بلا نصاب محدد: {s['none']}",
                 f"Complete: {s['ok']} — under: {s['under']} — over: {s['over']} — no target: {s['none']}")
    return tables, [note]


# ---------------------------------------------------------------------------
# Exams and duties (per term of the timetable)
# ---------------------------------------------------------------------------
def _module(ctx: Ctx, name: str) -> dict:
    from app.rules.modules import load_module
    return load_module(name)


def _lab(ctx: Ctx, mod: dict, field_: str) -> str:
    lab = mod["labels"][field_]
    return (lab.get("en") or lab["ar"]) if ctx.lang == "en" else lab["ar"]


def _extra_cols(ctx: Ctx, mod: dict, level: str):
    return [f for f in mod["extra_fields"] if f.get("level", "session") == level and f.get("show_in_report", True)]


def _extra_value(ctx: Ctx, f: dict, v):
    if v in (None, "", []):
        return ""
    if f["type"] == "teachers":
        ids = v if isinstance(v, list) else [v]
        return ctx.sep.join(ctx.name(ctx.teachers.get(uuid.UUID(x))) for x in ids if _is_uuid(x) and uuid.UUID(x) in ctx.teachers)
    if f["type"] == "bool":
        return "✓" if v else ""
    return str(v)


def _is_uuid(x) -> bool:
    try:
        uuid.UUID(str(x))
        return True
    except ValueError:
        return False


def _day_name(ctx: Ctx, d) -> str:
    names_ar = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
    names_en = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return (names_en if ctx.lang == "en" else names_ar)[d.weekday()]


def _time_span(a, b) -> str:
    if a and b:
        return f"{a.strftime('%H:%M')}\u200e–\u200e{b.strftime('%H:%M')}"   # LRM: keeps «from–to» in order inside Arabic text
    return a.strftime("%H:%M") if a else ""


def _exams(ctx: Ctx):
    from app.models import ExamSession
    q = select(ExamSession).where(ExamSession.term_id == ctx.tt.term_id).order_by(ExamSession.exam_date, ExamSession.starts_at)
    out = []
    for e in db.session.scalars(q):
        if ctx.f.get("stage_id") and e.stage_id and e.stage_id != ctx.f["stage_id"]:
            continue
        if ctx.f.get("grade_id") and e.grade_ids and ctx.f["grade_id"] not in e.grade_ids:
            continue
        if ctx.f.get("subject_id") and e.subject_id != ctx.f["subject_id"]:
            continue
        out.append(e)
    return out


def exam_schedule(ctx: Ctx) -> Table:
    mod = _module(ctx, "exams")
    ex_s, ex_r = _extra_cols(ctx, mod, "session"), _extra_cols(ctx, mod, "room")
    cols = [_lab(ctx, mod, "exam_date"), ctx.L("اليوم", "Day"), _lab(ctx, mod, "session_label"),
            ctx.L("الوقت", "Time"), _lab(ctx, mod, "stage_id"), _lab(ctx, mod, "grade_ids"), _lab(ctx, mod, "subject_id"),
            *[(f["label_en"] or f["label_ar"]) if ctx.lang == "en" else f["label_ar"] for f in ex_s],
            _lab(ctx, mod, "room_id"), _lab(ctx, mod, "location"), _lab(ctx, mod, "section_ids"),
            _lab(ctx, mod, "teacher_ids"),
            *[(f["label_en"] or f["label_ar"]) if ctx.lang == "en" else f["label_ar"] for f in ex_r]]
    rows = []
    for e in _exams(ctx):
        subject = ctx.name(ctx.subjects.get(e.subject_id)) if e.subject_id else ""
        if e.title:
            subject = f"{subject} — {e.title}" if subject else e.title
        head = [e.exam_date.isoformat(), _day_name(ctx, e.exam_date), e.session_label or "",
                _time_span(e.starts_at, e.ends_at), ctx.name(ctx.stages.get(e.stage_id)) if e.stage_id else "",
                ctx.sep.join(ctx.name(ctx.grades.get(g)) for g in e.grade_ids or [] if g in ctx.grades), subject,
                *[_extra_value(ctx, f, (e.extra or {}).get(f["key"])) for f in ex_s]]
        rooms = e.rooms or [{}]
        for r in rooms:
            if ctx.f.get("teacher_id") and str(ctx.f["teacher_id"]) not in (r.get("teacher_ids") or []):
                continue
            if ctx.f.get("room_id") and r.get("room_id") != str(ctx.f["room_id"]):
                continue
            room = ctx.rooms.get(uuid.UUID(r["room_id"])) if r.get("room_id") else None
            rows.append(head + [ctx.name(room) if room else "", r.get("location") or "",
                                ctx.sep.join(ctx.section_label(uuid.UUID(x)) for x in r.get("section_ids") or []
                                             if uuid.UUID(x) in ctx.sections),
                                ctx.sep.join(ctx.name(ctx.teachers.get(uuid.UUID(x))) for x in r.get("teacher_ids") or []
                                             if uuid.UUID(x) in ctx.teachers),
                                *[_extra_value(ctx, f, (r.get("extra") or {}).get(f["key"])) for f in ex_r]])
    title = mod["title"]["en"] if ctx.lang == "en" else mod["title"]["ar"]
    return Table(title=title, columns=cols, rows=rows)


def invigilation(ctx: Ctx) -> Table:
    mod = _module(ctx, "exams")
    per = defaultdict(list)
    for e in _exams(ctx):
        subject = ctx.name(ctx.subjects.get(e.subject_id)) if e.subject_id else (e.title or "")
        for r in e.rooms or []:
            room = ctx.rooms.get(uuid.UUID(r["room_id"])) if r.get("room_id") else None
            where = ctx.name(room) if room else (r.get("location") or "")
            for x in r.get("teacher_ids") or []:
                if not _is_uuid(x) or uuid.UUID(x) not in ctx.teachers:
                    continue
                per[uuid.UUID(x)].append(" ".join(v for v in (
                    e.exam_date.isoformat(), _day_name(ctx, e.exam_date), e.session_label or "",
                    _time_span(e.starts_at, e.ends_at), "—", subject, f"({where})" if where else "") if v))
    ids = [ctx.f["teacher_id"]] if ctx.f.get("teacher_id") else list(per)
    rows = [[ctx.name(ctx.teachers[t]), len(per[t]), "\n".join(per[t])]
            for t in sorted((i for i in ids if i in ctx.teachers), key=lambda i: ctx.name(ctx.teachers[i]))]
    return Table(title=ctx.L("عدد المراقبات ومواعيدها لكل معلم", "Invigilation duties per teacher"),
                 columns=[ctx.L("المعلم", "Teacher"), ctx.L("عدد المراقبات", "Count"), _lab(ctx, mod, "exam_date")],
                 rows=rows, numeric={1}, totals=[ctx.L("المجموع", "Total"), sum(r[1] for r in rows), ""])


def _duties(ctx: Ctx):
    from app.models import DutyAssignment
    out = []
    for d in db.session.scalars(select(DutyAssignment).where(DutyAssignment.term_id == ctx.tt.term_id)
                                .order_by(DutyAssignment.sort_order, DutyAssignment.starts_at)):
        if ctx.f.get("stage_id") and d.stage_id and d.stage_id != ctx.f["stage_id"]:
            continue
        if ctx.f.get("teacher_id") and ctx.f["teacher_id"] not in (d.teacher_ids or []):
            continue
        out.append(d)
    return out


def duty_roster(ctx: Ctx) -> Table:
    """Rows: each duty (time slot · purpose · location); columns: the school days; cells: teachers."""
    mod = _module(ctx, "duties")
    duties = _duties(ctx)
    keyed = {}
    for d in duties:
        key = (d.time_label or "", _time_span(d.starts_at, d.ends_at), d.duty_type, d.location or "",
               ctx.name(ctx.stages.get(d.stage_id)) if d.stage_id else "")
        keyed.setdefault(key, {"order": (d.sort_order, d.starts_at.isoformat() if d.starts_at else "99"), "days": defaultdict(list)})
        for wd in ([d.weekday_id] if d.weekday_id else [x.id for x in ctx.days]):
            keyed[key]["days"][wd] += [ctx.short_teacher(ctx.teachers[t]) if ctx.lang == "en" else ctx.name(ctx.teachers[t])
                                       for t in d.teacher_ids or [] if t in ctx.teachers]
    rows = []
    for key, v in sorted(keyed.items(), key=lambda kv: kv[1]["order"]):
        label = "\n".join(x for x in (" ".join(y for y in key[:2] if y), key[2], key[3], key[4]) if x)
        rows.append([label] + ["\n".join(v["days"].get(d.id, [])) or None for d in ctx.days])
    title = mod["title"]["en"] if ctx.lang == "en" else mod["title"]["ar"]
    corner = f"{_lab(ctx, mod, 'time_label')} / {_lab(ctx, mod, 'duty_type')} / {_lab(ctx, mod, 'location')}"
    return Table(title=title, columns=[corner] + [ctx.name(d) for d in ctx.days], rows=rows)


def duty_teachers(ctx: Ctx) -> Table:
    mod = _module(ctx, "duties")
    per = defaultdict(list)
    days = {d.id: ctx.name(d) for d in ctx.days}
    for d in _duties(ctx):
        when = days.get(d.weekday_id, ctx.L("كل الأيام", "Every day")) if d.weekday_id else ctx.L("كل الأيام", "Every day")
        text = " — ".join(x for x in (when, " ".join(y for y in (d.time_label or "", _time_span(d.starts_at, d.ends_at)) if y),
                                      d.duty_type, d.location or "") if x)
        n = 1 if d.weekday_id else len(ctx.days)
        for t in d.teacher_ids or []:
            if t in ctx.teachers:
                per[t].append((text, n))
    ids = [ctx.f["teacher_id"]] if ctx.f.get("teacher_id") else list(per)
    rows = [[ctx.name(ctx.teachers[t]), sum(n for _x, n in per[t]), "\n".join(x for x, _n in per[t])]
            for t in sorted((i for i in ids if i in ctx.teachers), key=lambda i: ctx.name(ctx.teachers[i]))]
    return Table(title=ctx.L("عدد المناوبات الأسبوعية ومواعيدها لكل معلم", "Weekly duties per teacher"),
                 columns=[ctx.L("المعلم", "Teacher"), ctx.L("عدد المناوبات أسبوعياً", "Duties per week"),
                          _lab(ctx, mod, "duty_type")],
                 rows=rows, numeric={1}, totals=[ctx.L("المجموع", "Total"), sum(r[1] for r in rows), ""])


# ---------------------------------------------------------------------------
# Absences and cover
# ---------------------------------------------------------------------------
def _today():
    return datetime.now(ZoneInfo(os.environ.get("APP_TIMEZONE", "Asia/Amman"))).date()


def _cover_kind(ctx: Ctx, kind: str) -> str:
    from app.rules.cover import KIND_LABELS
    a, e = KIND_LABELS.get(kind, (kind, kind))
    return ctx.L(a, e)


def cover_daily(ctx: Ctx) -> tuple[list[Table], list[str], str]:
    from app.rules.cover import CoverDay
    d = ctx.f.get("date") or _today()
    day = CoverDay(ctx.tt, d)
    rows = []
    want_t = ctx.f.get("teacher_id")
    for n in day.needs():
        if n.stale:
            continue
        s = n.substitution
        if want_t and want_t not in (n.teacher_id, s.substitute_teacher_id if s else None):
            continue
        if ctx.f.get("stage_id") and not any(ctx.stage_of_section(t.section_id) == ctx.f["stage_id"] for t in n.lesson.targets):
            continue
        if s is None:
            action = ctx.L("لم يُحدَّد بعد", "Not decided")
        elif s.kind == "cover":
            action = ctx.name(ctx.teachers.get(s.substitute_teacher_id))
        else:
            action = _cover_kind(ctx, s.kind) + (f" — {ctx.name(ctx.teachers.get(s.substitute_teacher_id))}"
                                                 if s.substitute_teacher_id else "")
        room = (s.room_id if s and s.room_id else n.card.room_id)
        when = f"{n.starts_at.strftime('%H:%M')}\u200e–\u200e{n.ends_at.strftime('%H:%M')}" if n.starts_at else ""
        rows.append([n.period_no, when, ctx.sep.join(ctx.target_label(t) for t in n.lesson.targets),
                     ctx.name(ctx.subjects.get(n.lesson.subject_id)), ctx.name(ctx.teachers.get(n.teacher_id)), action,
                     ctx.name(ctx.rooms.get(room)) if room else "", (s.note if s else "") or "", ""])
    t1 = Table(title="", columns=[ctx.L("الحصة", "Period"), ctx.L("الوقت", "Time"), ctx.L("الشعبة", "Section"),
                                  ctx.L("المبحث", "Subject"), ctx.L("المعلم الغائب", "Absent teacher"),
                                  ctx.L("المعلم البديل / الإجراء", "Substitute / action"), ctx.L("القاعة", "Room"),
                                  ctx.L("ملاحظات", "Notes"), ctx.L("توقيع البديل", "Signature")],
               rows=rows, numeric={0})
    abs_rows = []
    for a in sorted(day.absences, key=lambda a: ctx.name(ctx.teachers.get(a.teacher_id))):
        if want_t and a.teacher_id != want_t:
            continue
        span = ctx.L("اليوم كاملاً", "Whole day") if a.period_from is None else \
            ctx.L(f"من الحصة {a.period_from} إلى الحصة {a.period_to}", f"Periods {a.period_from}–{a.period_to}")
        abs_rows.append([ctx.name(ctx.teachers.get(a.teacher_id)), span, a.reason or "",
                         f"{a.date_from.isoformat()} — {a.date_to.isoformat()}" if a.date_to != a.date_from else a.date_from.isoformat()])
    t2 = Table(title=ctx.L("المعلمون الغائبون", "Absent teachers"),
               columns=[ctx.L("المعلم", "Teacher"), ctx.L("الحصص", "Periods"), ctx.L("السبب", "Reason"), ctx.L("المدة", "Dates")],
               rows=abs_rows)
    sm = day.summary(day.needs())
    dayname = ctx.name(day.weekday) if day.weekday else ""
    sub = ctx.L(f"{dayname} {d.isoformat()}", f"{dayname} {d.isoformat()}")
    t1.subtitle = sub
    note = ctx.L(f"الحصص التي تحتاج إلى قرار: {sm['needs']} — حُسم منها: {sm['decided']} — بمعلم بديل: {sm['covered']}",
                 f"Periods needing a decision: {sm['needs']} — decided: {sm['decided']} — covered: {sm['covered']}")
    if day.weekday is None:
        note = ctx.L("هذا التاريخ ليس يوم دوام", "This date is not a school day")
    return [t1, t2], [note], sub


def _range(ctx: Ctx):
    from datetime import timedelta
    d1 = ctx.f.get("date_to") or ctx.f.get("date") or _today()
    d0 = ctx.f.get("date_from") or ctx.f.get("date")
    if d0 is None:   # default: from the start of the timetable's term
        from app.models import Term
        term = db.session.get(Term, ctx.tt.term_id)
        d0 = term.start_date if term and term.start_date else d1 - timedelta(days=90)
    return d0, d1


def _school_days_between(ctx: Ctx, a, b) -> int:
    from datetime import timedelta
    dows = {d.iso_dow for d in ctx.days}
    n, x = 0, a
    while x <= b:
        if x.isoweekday() in dows:
            n += 1
        x += timedelta(days=1)
    return n


def cover_stats(ctx: Ctx) -> Table:
    from app.models import Substitution, TeacherAbsence
    d0, d1 = _range(ctx)
    given, missed, decided_missed = defaultdict(int), defaultdict(int), defaultdict(int)
    for s in db.session.scalars(select(Substitution).where(Substitution.timetable_id == ctx.tt.id,
                                                           Substitution.date >= d0, Substitution.date <= d1)):
        decided_missed[s.original_teacher_id] += 1
        if s.kind == "cover" and s.substitute_teacher_id:
            given[s.substitute_teacher_id] += 1
    absent_days = defaultdict(int)
    for a in db.session.scalars(select(TeacherAbsence).where(TeacherAbsence.date_from <= d1, TeacherAbsence.date_to >= d0)):
        absent_days[a.teacher_id] += _school_days_between(ctx, max(a.date_from, d0), min(a.date_to, d1))
    ids = set(given) | set(decided_missed) | set(absent_days)
    if ctx.f.get("teacher_id"):
        ids = {ctx.f["teacher_id"]}
    if ctx.f.get("stage_id"):
        ids = {i for i in ids if i in ctx.teachers and ctx.f["stage_id"] in {s.id for s in ctx.teachers[i].stages}}
    rows = [[ctx.name(ctx.teachers[i]), given[i], absent_days[i], decided_missed[i]]
            for i in sorted((i for i in ids if i in ctx.teachers), key=lambda i: (-given[i], ctx.name(ctx.teachers[i])))]
    return Table(title=ctx.L(f"من {d0.isoformat()} إلى {d1.isoformat()}", f"{d0.isoformat()} to {d1.isoformat()}"),
                 columns=[ctx.L("المعلم", "Teacher"), ctx.L("حصص الإشغال التي غطّاها", "Covers given"),
                          ctx.L("أيام الغياب", "Days absent"), ctx.L("حصصه التي غُطّيت أو حُسمت", "Own periods covered")],
                 rows=rows, numeric={1, 2, 3},
                 totals=[ctx.L("المجموع", "Total"), sum(r[1] for r in rows), sum(r[2] for r in rows), sum(r[3] for r in rows)])


def absence_log(ctx: Ctx) -> Table:
    from app.models import TeacherAbsence
    d0, d1 = _range(ctx)
    rows = []
    for a in db.session.scalars(select(TeacherAbsence).where(TeacherAbsence.date_from <= d1, TeacherAbsence.date_to >= d0)
                                .order_by(TeacherAbsence.date_from)):
        t = ctx.teachers.get(a.teacher_id)
        if t is None or (ctx.f.get("teacher_id") and a.teacher_id != ctx.f["teacher_id"]):
            continue
        if ctx.f.get("stage_id") and ctx.f["stage_id"] not in {s.id for s in t.stages}:
            continue
        span = ctx.L("اليوم كاملاً", "Whole day") if a.period_from is None else \
            ctx.L(f"من الحصة {a.period_from} إلى الحصة {a.period_to}", f"Periods {a.period_from}–{a.period_to}")
        rows.append([ctx.name(t), a.date_from.isoformat(), a.date_to.isoformat(), span,
                     _school_days_between(ctx, a.date_from, a.date_to), a.reason or "", a.note or ""])
    return Table(title=ctx.L(f"من {d0.isoformat()} إلى {d1.isoformat()}", f"{d0.isoformat()} to {d1.isoformat()}"),
                 columns=[ctx.L("المعلم", "Teacher"), ctx.L("من تاريخ", "From"), ctx.L("إلى تاريخ", "To"),
                          ctx.L("الحصص", "Periods"), ctx.L("أيام الدوام", "School days"), ctx.L("السبب", "Reason"),
                          ctx.L("ملاحظات", "Notes")],
                 rows=rows, numeric={4}, totals=[ctx.L("المجموع", "Total"), "", "", "", sum(r[4] for r in rows), "", ""])


def build_report(tt: Timetable, kind: str, lang: str, filters: dict, layout: str = "rows", style: str = "plain",
                 show: set | None = None, signature: list | None = None) -> Report:
    ctx = Ctx(tt, lang, filters, show)
    school = db.session.scalars(select(School)).first()
    rep = Report(
        kind=kind, lang=lang, title=TITLES[kind][1 if lang == "en" else 0],
        school_name=(school.name_en if lang == "en" and school and school.name_en else (school.name_ar if school else "")),
        timetable_name=tt.name, filters=ctx.describe_filters(), layout=layout if layout in ("rows", "cols") else "rows",
        generated_at=datetime.now(ZoneInfo(os.environ.get("APP_TIMEZONE", "Asia/Amman"))).strftime("%Y-%m-%d %H:%M"),
        style=style if style in ("plain", "color") else "plain", signature=[x for x in (signature or []) if x],
    )
    rep.orientable = kind.endswith("-timetable") or kind in ("teachers-master", "free-teachers") or kind in MATRIX_KINDS
    if kind == "teacher-timetable":
        rep.grids = teacher_grids(ctx)
    elif kind == "section-timetable":
        rep.grids = section_grids(ctx)
    elif kind == "room-timetable":
        rep.grids = room_grids(ctx)
    elif kind == "subject-timetable":
        rep.grids = subject_grids(ctx)
    elif kind == "free-teachers":
        rep.grids = free_teacher_grid(ctx)
    elif kind == "stage-timetable":
        rep.tables = [master_table(ctx, "sections", rep.layout)]
    elif kind == "teachers-master":
        rep.tables = [master_table(ctx, "teachers", rep.layout)]
    elif kind == "teacher-sections":
        rep.tables = [teacher_sections(ctx)]
    elif kind == "teacher-subjects":
        rep.tables = [teacher_subjects(ctx)]
    elif kind == "teacher-daily":
        rep.tables = [teacher_daily(ctx)]
    elif kind == "stats-teachers":
        rep.tables = [stats_teachers(ctx)]
    elif kind == "stats-subjects":
        rep.tables = [stats_subjects(ctx)]
    elif kind == "stats-sections":
        rep.tables = [stats_sections(ctx)]
    elif kind == "load-status":
        rep.tables, rep.notes = load_status_tables(ctx)
    elif kind == "exam-schedule":
        rep.tables = [exam_schedule(ctx)]
    elif kind == "invigilation":
        rep.tables = [invigilation(ctx)]
    elif kind == "duty-roster":
        rep.tables = [duty_roster(ctx)]
    elif kind == "duty-teachers":
        rep.tables = [duty_teachers(ctx)]
    elif kind == "cover-daily":
        rep.tables, rep.notes, _sub = cover_daily(ctx)
    elif kind == "cover-stats":
        rep.tables = [cover_stats(ctx)]
    elif kind == "absence-log":
        rep.tables = [absence_log(ctx)]
    if kind in MATRIX_KINDS and rep.layout == "cols":
        rep.tables = [transpose(t, ctx.L("المجموع", "Total")) for t in rep.tables]
    if "footer" not in ctx.show:
        for g_ in rep.grids:
            g_.footer = None
    return rep


def parse_show(raw: str | None) -> set | None:
    if raw is None:
        return None
    return {x for x in raw.split(",") if x in SHOW_KEYS}


def parse_filters(args) -> dict:
    from datetime import date as _date
    out = {}
    for k in FILTER_KEYS:
        v = args.get(k)
        if v:
            out[k] = uuid.UUID(v)
    for k in DATE_KEYS:
        v = args.get(k)
        if v:
            out[k] = _date.fromisoformat(v)
    return out
