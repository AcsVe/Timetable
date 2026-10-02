"""Period plans: split a term into periods (whole term, months, weeks, days) using the school days and
the holiday calendar, fill a plan from the weekly study plan, and compare it with what the timetable
gives (after holidays), what was really taught (absences without the subject's teacher), and the load of
each teacher.

Numbers per section × subject:
  required   — the plan
  scheduled  — periods the timetable gives in the period's school days (holidays removed)
  lost       — periods the subject's teacher(s) were absent (covered by a substitute or not)
  covered    — of which a substitute was in class (حصة إشغال)
  due        — scheduled periods on days up to today
  delivered  — due − lost
"""
from __future__ import annotations

import math
import uuid
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select

from app.extensions import db
from app.models import (
    Card,
    CurriculumItem,
    Grade,
    Holiday,
    Lesson,
    PeriodPlan,
    Section,
    Stage,
    StudentGroup,
    Subject,
    Substitution,
    Teacher,
    TeacherAbsence,
    Term,
    Timetable,
    Weekday,
)

MONTHS_AR = ["كانون الثاني", "شباط", "آذار", "نيسان", "أيار", "حزيران", "تموز", "آب", "أيلول",
             "تشرين الأول", "تشرين الثاني", "كانون الأول"]
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
             "October", "November", "December"]


def week_start(d: date) -> date:
    return d - timedelta(days=d.isoweekday() % 7)     # Sunday


class Calendar:
    """School days of a term, per stage (a holiday may concern some stages only)."""

    def __init__(self, term: Term):
        if not term.start_date or not term.end_date:
            from app.errors import ApiError
            raise ApiError("validation", 400, details={"field": "term_id", "reason": "term_dates",
                                                        "message": "حدّد تاريخَي بداية الفصل ونهايته في صفحة «الفصول الدراسية» أولاً"})
        self.term = term
        self.weekdays = {w.iso_dow: w for w in db.session.scalars(select(Weekday).where(Weekday.is_school_day.is_(True)))}
        self.holidays = list(db.session.scalars(select(Holiday).where(Holiday.date_to >= term.start_date,
                                                                      Holiday.date_from <= term.end_date)))
        self._cache: dict = {}

    @property
    def days_per_week(self) -> int:
        return len(self.weekdays) or 5

    def all_days(self) -> list[date]:
        d, out = self.term.start_date, []
        while d <= self.term.end_date:
            if d.isoweekday() in self.weekdays:
                out.append(d)
            d += timedelta(days=1)
        return out

    def school_days(self, stage_id=None) -> list[date]:
        if stage_id not in self._cache:
            self._cache[stage_id] = [d for d in self.all_days() if not any(h.applies(d, stage_id) for h in self.holidays)]
        return self._cache[stage_id]

    def holiday_on(self, d: date, stage_id=None) -> Holiday | None:
        return next((h for h in self.holidays if h.applies(d, stage_id)), None)


def period_key(period_type: str, d: date) -> str:
    if period_type == "term":
        return "term"
    if period_type == "month":
        return d.strftime("%Y-%m")
    if period_type == "week":
        return week_start(d).isoformat()
    return d.isoformat()


def periods(plan: PeriodPlan, cal: Calendar, lang: str = "ar") -> list[dict]:
    """The plan's columns: key, label, first/last date, school days (for the plan's stage)."""
    days = cal.school_days(plan.stage_id)
    out: dict[str, dict] = {}
    for d in cal.all_days():
        k = period_key(plan.period_type, d)
        p = out.setdefault(k, {"key": k, "start": d, "end": d, "school_days": 0})
        p["end"] = d
    for d in days:
        out[period_key(plan.period_type, d)]["school_days"] += 1
    res = []
    for k, p in out.items():
        if plan.period_type == "term":
            label = cal.term.name_en if lang == "en" and cal.term.name_en else cal.term.name_ar
        elif plan.period_type == "month":
            m = p["start"].month - 1
            label = f"{(MONTHS_EN if lang == 'en' else MONTHS_AR)[m]} {p['start'].year}"
        elif plan.period_type == "week":
            label = f"{'Week of' if lang == 'en' else 'أسبوع'} {p['start'].strftime('%d/%m')}"
        else:
            wd = cal.weekdays.get(p["start"].isoweekday())
            label = f"{(wd.name_en or wd.name_ar) if lang == 'en' else wd.name_ar} {p['start'].strftime('%d/%m')}"
            h = cal.holiday_on(p["start"], plan.stage_id)
            if h:
                label += f" ({h.name_ar})"
        res.append({"key": k, "label": label, "start": p["start"].isoformat(), "end": p["end"].isoformat(),
                    "school_days": p["school_days"]})
    return res


def plan_grades(plan: PeriodPlan) -> list[Grade]:
    q = select(Grade)
    if plan.stage_id:
        q = q.where(Grade.stage_id == plan.stage_id)
    return sorted(db.session.scalars(q), key=lambda g: (g.sort_order, g.name_ar))


def fill_from_weekly(plan: PeriodPlan, grade_ids: list[uuid.UUID] | None, overwrite: bool) -> int:
    """Required periods of each period = weekly plan × school days of the period ÷ school days a week
    (rounded), per grade and subject of the weekly study plan."""
    cal = Calendar(db.session.get(Term, plan.term_id))
    grades = {g.id: g for g in plan_grades(plan) if grade_ids is None or g.id in grade_ids}
    targets = {k: dict(v) for k, v in (plan.targets or {}).items()}
    n = 0
    for it in db.session.scalars(select(CurriculumItem).where(CurriculumItem.grade_id.in_(list(grades)))):
        stage = grades[it.grade_id].stage_id
        days = cal.school_days(stage)
        per: dict[str, int] = defaultdict(int)
        for d in days:
            per[period_key(plan.period_type, d)] += 1
        key = f"{it.grade_id}:{it.subject_id}"
        row = targets.setdefault(key, {})
        for pk, nd in per.items():
            if overwrite or pk not in row:
                row[pk] = round(it.periods_per_week * nd / cal.days_per_week)
                n += 1
    plan.targets = targets
    return n


# ---------------------------------------------------------------------------- analysis
def _section_label(sec: Section, g: Grade) -> str:
    return sec.name_ar if sec.name_ar.replace(" ", "").startswith(g.name_ar.replace(" ", "")) else f"{g.name_ar} / {sec.name_ar}"


def _cycle(tt: Timetable, term: Term, d: date) -> int | None:
    if tt.cycle_weeks <= 1 or not term.start_date:
        return None
    return ((week_start(d) - week_start(term.start_date)).days // 7) % tt.cycle_weeks + 1


def analyze(plan: PeriodPlan, tt: Timetable, period: str | None = None, today: date | None = None) -> dict:
    """Compare a plan with a timetable over the whole plan (period=None) or one period key."""
    today = today or date.today()
    term = db.session.get(Term, plan.term_id)
    cal = Calendar(term)
    grades = {g.id: g for g in plan_grades(plan)}
    sections = [s for s in db.session.scalars(select(Section)) if s.grade_id in grades]
    subjects = {s.id: s for s in db.session.scalars(select(Subject))}
    teachers = {t.id: t for t in db.session.scalars(select(Teacher))}
    weekday_by_id = {w.id: w for w in cal.weekdays.values()}
    lessons = [l for l in db.session.scalars(select(Lesson).where(Lesson.timetable_id == tt.id))]
    lesson_by_id = {l.id: l for l in lessons}
    cards = [c for c in db.session.scalars(select(Card).where(Card.timetable_id == tt.id, Card.weekday_id.is_not(None)))
             if c.lesson_id in lesson_by_id]
    in_period = (lambda d: True) if not period else (lambda d: period_key(plan.period_type, d) == period)

    # periods per (section, subject) on one weekday / cycle week; split groups count once (busiest group)
    def daily(cw):
        whole = defaultdict(int)
        groups = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
        for c in cards:
            if c.week_no is not None and cw is not None and c.week_no != cw:
                continue
            l = lesson_by_id[c.lesson_id]
            if l.is_meeting:
                continue
            for t in l.targets:
                key = (t.section_id, l.subject_id, c.weekday_id)
                if t.group_id is None:
                    whole[key] += c.duration
                else:
                    g = t.group or db.session.get(StudentGroup, t.group_id)
                    groups[key][g.division_id][t.group_id] += c.duration
        flat = dict(whole)
        for key, divs in groups.items():
            flat[key] = flat.get(key, 0) + sum(max(v.values()) for v in divs.values())
        out = defaultdict(list)          # (section, weekday) -> [(subject, periods)]
        for (sid, subj, wid), n in flat.items():
            out[(sid, wid)].append((subj, n))
        return out
    daily_cache: dict = {}

    def per_day(d):
        cw = _cycle(tt, term, d)
        if cw not in daily_cache:
            daily_cache[cw] = daily(cw)
        return daily_cache[cw]

    sched = defaultdict(int)
    due = defaultdict(int)
    for sec in sections:
        stage = grades[sec.grade_id].stage_id
        for d in cal.school_days(stage):
            if not in_period(d):
                continue
            wd = cal.weekdays.get(d.isoweekday())
            for subj, n in per_day(d).get((sec.id, wd.id), []):
                sched[(sec.id, subj)] += n
                if d <= today:
                    due[(sec.id, subj)] += n

    # absences: periods of a lesson when all its teachers were away (counted per section once)
    lost, covered = defaultdict(int), defaultdict(int)
    t_lost, t_covered = defaultdict(int), defaultdict(int)
    subs = {(s.date, s.card_id, s.period_no): s for s in db.session.scalars(
        select(Substitution).where(Substitution.timetable_id == tt.id))}
    absences = [a for a in db.session.scalars(select(TeacherAbsence).where(
        TeacherAbsence.date_to >= term.start_date, TeacherAbsence.date_from <= min(term.end_date, today)))]
    by_teacher = defaultdict(list)
    for a in absences:
        by_teacher[a.teacher_id].append(a)
    cards_by_wd = defaultdict(list)
    for c in cards:
        cards_by_wd[c.weekday_id].append(c)
    absent_days = sorted({d for a in absences for d in _dates(a.date_from, a.date_to)
                          if term.start_date <= d <= min(term.end_date, today) and in_period(d)})
    for d in absent_days:
        wd = cal.weekdays.get(d.isoweekday())
        if wd is None:
            continue
        cw = _cycle(tt, term, d)
        for c in cards_by_wd.get(wd.id, []):
            if c.week_no is not None and cw is not None and c.week_no != cw:
                continue
            l = lesson_by_id[c.lesson_id]
            if l.is_meeting or not l.teacher_ids:
                continue
            stages = {grades[s.grade_id].stage_id for s in sections if any(t.section_id == s.id for t in l.targets)}
            if stages and all(cal.holiday_on(d, st) for st in stages):
                continue
            for p in range(c.period_no, c.period_no + c.duration):
                away = [tid for tid in l.teacher_ids if any(a.covers(d, p) for a in by_teacher.get(tid, []))]
                for tid in away:
                    t_lost[tid] += 1
                    sub = subs.get((d, c.id, p))
                    if sub is not None and sub.kind == "cover":
                        t_covered[tid] += 1
                if len(away) < len(l.teacher_ids):
                    continue                 # a co-teacher was there: the class was taught
                sub = subs.get((d, c.id, p))
                for t in {t.section_id for t in l.targets}:
                    lost[(t, l.subject_id)] += 1
                    if sub is not None and sub.kind == "cover":
                        covered[(t, l.subject_id)] += 1

    # rows: section × subject
    targets = plan.targets or {}

    def required(grade_id, subject_id) -> int:
        row = targets.get(f"{grade_id}:{subject_id}") or {}
        if period:
            return int(row.get(period) or 0)
        return sum(int(v or 0) for v in row.values())

    # school days of each period per stage, and how many of them have passed — the plan due to date is pro rata
    span: dict = {}

    def days_of(stage_id):
        if stage_id not in span:
            tot, past = defaultdict(int), defaultdict(int)
            for d in cal.school_days(stage_id):
                k = period_key(plan.period_type, d)
                tot[k] += 1
                if d <= today:
                    past[k] += 1
            span[stage_id] = (tot, past)
        return span[stage_id]

    def required_due(grade_id, subject_id) -> int:
        row = targets.get(f"{grade_id}:{subject_id}") or {}
        tot, past = days_of(grades[grade_id].stage_id)
        total = 0.0
        for k, v in row.items():
            if period and k != period:
                continue
            if tot.get(k):
                total += int(v or 0) * past.get(k, 0) / tot[k]
        return round(total)

    rows = []
    stages = {s.id: s for s in db.session.scalars(select(Stage))}
    for sec in sorted(sections, key=lambda s: (grades[s.grade_id].sort_order, grades[s.grade_id].name_ar, s.name_ar)):
        g = grades[sec.grade_id]
        subj_ids = {uuid.UUID(k.split(":")[1]) for k in targets if k.startswith(f"{g.id}:")}
        subj_ids |= {subj for (sid, subj) in sched if sid == sec.id}
        for subj in sorted(subj_ids, key=lambda i: subjects[i].name_ar if i in subjects else ""):
            req = required(g.id, subj)
            sc = sched.get((sec.id, subj), 0)
            ls, cv = lost.get((sec.id, subj), 0), covered.get((sec.id, subj), 0)
            du = due.get((sec.id, subj), 0)
            status = "none" if not req and not sc else "extra" if not req else "under" if sc < req else "over" if sc > req else "ok"
            rows.append({
                "id": f"{sec.id}:{subj}", "section_id": str(sec.id), "grade_id": str(g.id), "subject_id": str(subj),
                "stage": stages[g.stage_id].name_ar if g.stage_id in stages else "",
                "section": _section_label(sec, g), "subject": subjects[subj].name_ar if subj in subjects else "?",
                "subject_en": (subjects[subj].name_en or subjects[subj].name_ar) if subj in subjects else "?",
                "required": req, "scheduled": sc, "diff": sc - req, "lost": ls, "covered": cv,
                "due": du, "delivered": max(0, du - ls), "required_due": required_due(g.id, subj),
                "status": status,
            })

    # teachers: what the plan asks of their lessons, what the timetable gives them, their load
    t_rows = []
    by_teacher_req = defaultdict(int)
    by_teacher_sched = defaultdict(int)
    by_teacher_due = defaultdict(int)
    sec_by_id = {s.id: s for s in sections}
    for l in lessons:
        if l.is_meeting or not l.targets:
            continue
        first = sec_by_id.get(l.targets[0].section_id)
        if first is None:
            continue
        for tid in l.teacher_ids:
            by_teacher_req[tid] += required(first.grade_id, l.subject_id)
    all_days = [d for d in cal.school_days(None) if in_period(d)]
    for c in cards:
        l = lesson_by_id[c.lesson_id]
        if not l.counts_load:
            continue
        stage_list = {grades[sec_by_id[t.section_id].grade_id].stage_id for t in l.targets if t.section_id in sec_by_id}
        if l.targets and not stage_list:
            continue                         # a lesson of another stage
        st = next(iter(stage_list)) if len(stage_list) == 1 else None
        days = [d for d in (cal.school_days(st) if st else all_days) if in_period(d)]
        wd = weekday_by_id.get(c.weekday_id)
        for d in days:
            if wd is None or d.isoweekday() != wd.iso_dow:
                continue
            cw = _cycle(tt, term, d)
            if c.week_no is not None and cw is not None and c.week_no != cw:
                continue
            for tid in l.teacher_ids:
                by_teacher_sched[tid] += c.duration
                if d <= today:
                    by_teacher_due[tid] += c.duration
    weeks = len(all_days) / cal.days_per_week if cal.days_per_week else 0
    for tid in set(by_teacher_req) | set(by_teacher_sched):
        t = teachers.get(tid)
        if t is None:
            continue
        quota = round(t.target_weekly_periods * weeks) if t.target_weekly_periods else None
        sc = by_teacher_sched.get(tid, 0)
        req = by_teacher_req.get(tid, 0)
        status = "none" if quota is None else "under" if sc < quota else "over" if sc > quota else "ok"
        t_rows.append({
            "id": str(tid), "teacher_id": str(tid), "name": t.name_ar, "name_en": t.name_en or t.name_ar,
            "required": req, "scheduled": sc, "quota": quota, "weekly_target": t.target_weekly_periods,
            "lost": t_lost.get(tid, 0), "covered": t_covered.get(tid, 0), "due": by_teacher_due.get(tid, 0),
            "delivered": max(0, by_teacher_due.get(tid, 0) - t_lost.get(tid, 0)),
            "plan_status": "none" if not req else "under" if sc < req else "over" if sc > req else "ok",
            "status": status,
        })
    t_rows.sort(key=lambda r: r["name"])
    summary = defaultdict(int)
    for r in rows:
        summary[r["status"]] += 1
    summary["lost"] = sum(r["lost"] for r in rows)
    summary["covered"] = sum(r["covered"] for r in rows)
    return {"rows": rows, "teachers": t_rows, "summary": dict(summary), "school_days": len(all_days),
            "weeks": round(weeks, 1), "today": today.isoformat(), "period": period}


def _dates(a: date, b: date):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)
