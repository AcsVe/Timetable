"""Timetable validation report ("Advisor" in ASC), plus arithmetic feasibility
checks that expose impossible inputs before anyone tries to place cards."""
from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import select

from app.arabic import count, g, teacher_title
from app.extensions import db
from app.models import Availability, Card, Lesson, Occupancy, Section, Teacher, Timetable, Weekday
from app.rules.placement import PlacementChecker


def _issue(level_list, code, message, message_en, **extra):
    item = {"code": code, "message": message, "message_en": message_en}
    item.update({k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in extra.items()})
    level_list.append(item)


def _longest_run(nums: list[int]) -> int:
    best = run = 0
    prev = None
    for n in sorted(nums):
        run = run + 1 if prev is not None and n == prev + 1 else 1
        best = max(best, run)
        prev = n
    return best


def validate_timetable(tt: Timetable) -> dict:
    errors: list[dict] = []
    warnings: list[dict] = []
    checker = PlacementChecker(tt)
    lessons = db.session.scalars(select(Lesson).where(Lesson.timetable_id == tt.id)).all()
    lesson_by_id = {l.id: l for l in lessons}
    cards = db.session.scalars(select(Card).where(Card.timetable_id == tt.id)).all()
    school_days = db.session.scalars(
        select(Weekday).where(Weekday.is_school_day.is_(True)).order_by(Weekday.sort_order)
    ).all()

    # 1. Unplaced cards
    unplaced = defaultdict(int)
    for c in cards:
        if not c.is_placed:
            unplaced[c.lesson_id] += c.duration
    for lid, n in unplaced.items():
        l = lesson_by_id[lid]
        _issue(warnings, "unplaced", f"{l.label}: {count(n, 'period')} لم تُدرَج في الجدول بعد",
               f"{l.label_en}: {n} period(s) not placed", lesson_id=lid, periods=n)

    # 2. Re-check every placed card with the same rule engine used on save
    seen = set()
    for c in cards:
        if not c.is_placed:
            continue
        l = lesson_by_id[c.lesson_id]
        for conf in checker.check(l, c.weekday_id, c.period_no, c.duration, c.week_no, c.room_id,
                                  exclude_card_ids={c.id}):
            key = (conf.code, frozenset({c.id, conf.other_card_id}), str(conf.extra.get("grade_id", "")))
            if key in seen:
                continue
            seen.add(key)
            _issue(errors, conf.code, conf.message, conf.message_en, card_id=c.id,
                   **({"other_card_id": conf.other_card_id} if conf.other_card_id else {}))

    # 3. Teacher loads and daily constraints
    required = defaultdict(int)     # periods counted in the teaching load
    busy = defaultdict(int)         # every period the teacher must attend (meetings included)
    for l in lessons:
        for tid in l.teacher_ids:
            busy[tid] += l.periods_per_week
            if l.counts_load:
                required[tid] += l.periods_per_week
        subj_limit = l.subject.max_teachers_per_block
        if len(l.teacher_ids) > subj_limit:
            _issue(errors, "too_many_teachers", f"{l.subject.name_ar}: عدد المعلمين يتجاوز الحد المسموح ({subj_limit})",
                   f"{l.subject.name_en or l.subject.name_ar}: more teachers than allowed ({subj_limit})", lesson_id=l.id)
    per_day: dict[uuid.UUID, dict[uuid.UUID, set[int]]] = defaultdict(lambda: defaultdict(set))
    for occ in db.session.scalars(
        select(Occupancy).where(Occupancy.timetable_id == tt.id, Occupancy.resource_type == "teacher")
    ):
        per_day[occ.resource_id][occ.weekday_id].update(range(occ.periods.lower, occ.periods.upper))

    teachers = db.session.scalars(select(Teacher)).all()
    unavailable = defaultdict(int)
    for a in db.session.scalars(select(Availability).where(
            Availability.timetable_id == tt.id, Availability.entity_type == "teacher",
            Availability.status == "unavailable")):
        unavailable[a.entity_id] += 1
    max_periods_any_day = _max_periods_per_day(checker, lessons, school_days)
    from app.rules.loads import statuses_by_teacher
    load_status = statuses_by_teacher(tt)
    for t in teachers:
        req = required.get(t.id, 0)
        name, name_en = f"{teacher_title(t.gender)} {t.name_ar}", t.name_en or t.name_ar
        him = g(t.gender, "إليه", "إليها")
        status = load_status.get(str(t.id))
        if status and not status["default_rule"]:
            if status["status"] in ("under", "over"):
                _issue(warnings, f"load_rule_{status['status']}", status["message"], status["message_en"],
                       teacher_id=t.id, rule_id=status["rule_id"])
        elif t.target_weekly_periods is not None and req:
            if req > t.target_weekly_periods:
                _issue(warnings, "teacher_over_target", f"{name}: أُسنِدت {him} {count(req, 'period')}، و{g(t.gender, 'نصابه', 'نصابها')} الأسبوعي {t.target_weekly_periods}",
                       f"{name_en}: assigned {req} periods, target {t.target_weekly_periods}", teacher_id=t.id)
            elif req < t.target_weekly_periods:
                _issue(warnings, "teacher_under_target", f"{name}: لم يُسنَد {him} إلا {count(req, 'period')}، و{g(t.gender, 'نصابه', 'نصابها')} الأسبوعي {t.target_weekly_periods}",
                       f"{name_en}: only {req} periods assigned, target {t.target_weekly_periods}", teacher_id=t.id)
        # Feasibility: more periods than free slots in the week
        req = busy.get(t.id, 0)
        if req:
            capacity = max_periods_any_day * len(school_days) - unavailable.get(t.id, 0)
            if t.max_periods_per_day is not None:
                capacity = min(capacity, t.max_periods_per_day * len(school_days))
            if t.max_days_per_week is not None:
                capacity = min(capacity, t.max_days_per_week * (t.max_periods_per_day or max_periods_any_day))
            if req > capacity:
                _issue(errors, "teacher_infeasible", f"{name}: المطلوب {count(req, 'period')}، والمتاح {count(capacity, 'slot')} فقط",
                       f"{name_en}: {req} periods required but only {capacity} slots available",
                       teacher_id=t.id, required=req, available=capacity)
        days = per_day.get(t.id, {})
        gaps_week = 0
        for wd_id, periods in days.items():
            wd = db.session.get(Weekday, wd_id)
            ps = sorted(periods)
            gaps = (ps[-1] - ps[0] + 1) - len(ps)
            gaps_week += gaps
            if t.max_periods_per_day is not None and len(ps) > t.max_periods_per_day:
                _issue(warnings, "teacher_max_per_day", f"{name}: {count(len(ps), 'period')} يوم {wd.name_ar} (الحد الأقصى {t.max_periods_per_day})",
                       f"{name_en}: {len(ps)} periods on {wd.name_en or wd.name_ar} (max {t.max_periods_per_day})", teacher_id=t.id)
            if t.max_gaps_per_day is not None and gaps > t.max_gaps_per_day:
                _issue(warnings, "teacher_gaps_day", f"{name}: {count(gaps, 'gap')} يوم {wd.name_ar} (الحد الأقصى {t.max_gaps_per_day})",
                       f"{name_en}: {gaps} gaps on {wd.name_en or wd.name_ar} (max {t.max_gaps_per_day})", teacher_id=t.id)
            run = _longest_run(ps)
            if t.max_consecutive is not None and run > t.max_consecutive:
                _issue(warnings, "teacher_consecutive", f"{name}: {count(run, 'period')} متتالية يوم {wd.name_ar} (الحد الأقصى {t.max_consecutive})",
                       f"{name_en}: {run} consecutive periods on {wd.name_en or wd.name_ar} (max {t.max_consecutive})", teacher_id=t.id)
        if t.max_gaps_per_week is not None and gaps_week > t.max_gaps_per_week:
            _issue(warnings, "teacher_gaps_week", f"{name}: {count(gaps_week, 'gap')} في الأسبوع (الحد الأقصى {t.max_gaps_per_week})",
                   f"{name_en}: {gaps_week} gaps per week (max {t.max_gaps_per_week})", teacher_id=t.id)
        if t.max_days_per_week is not None and len(days) > t.max_days_per_week:
            _issue(warnings, "teacher_days", f"{name}: {g(t.gender, 'يداوم', 'تداوم')} {count(len(days), 'day')} (الحد الأقصى {t.max_days_per_week})",
                   f"{name_en}: teaches on {len(days)} days (max {t.max_days_per_week})", teacher_id=t.id)

    # 4. Qualification (only when the teacher has a declared subject list)
    teacher_by_id = {t.id: t for t in teachers}
    for l in lessons:
        for tid in l.teacher_ids:
            t = teacher_by_id.get(tid)
            if t and t.subjects and not l.is_meeting and l.subject not in t.subjects:
                _issue(warnings, "teacher_not_qualified", f"{teacher_title(t.gender)} {t.name_ar} {g(t.gender, 'غير مسجّل', 'غير مسجّلة')} لتدريس مبحث {l.subject.name_ar}",
                       f"{t.name_en or t.name_ar} is not registered for {l.subject.name_en or l.subject.name_ar}",
                       teacher_id=t.id, lesson_id=l.id)

    # 5. Section capacity: required periods vs. lesson slots in its week
    section_load = _section_loads(lessons)
    for sid, req in section_load.items():
        sec = db.session.get(Section, sid)
        cap = 0
        for wd in school_days:
            p = checker.bells.periods(sec.grade, wd.id)
            cap += len(p) if p else 0
        label = f"{sec.grade.name_ar} / {sec.name_ar}"
        if cap == 0:
            _issue(errors, "no_bell_schedule", f"الشعبة {label}: لم يُحدَّد لها توقيت حصص في أي يوم",
                   f"Section {label}: no bell schedule on any day", section_id=sid)
        elif req > cap:
            _issue(errors, "section_overloaded", f"الشعبة {label}: المطلوب {count(req, 'period')}، وفي أسبوعها {count(cap, 'slot')} فقط",
                   f"Section {label}: {req} periods required but only {cap} slots per week",
                   section_id=sid, required=req, available=cap)

    placed = sum(c.duration for c in cards if c.is_placed)
    total = sum(c.duration for c in cards)
    return {
        "timetable_id": str(tt.id),
        "ok": not errors,
        "summary": {
            "errors": len(errors),
            "warnings": len(warnings),
            "periods_total": total,
            "periods_placed": placed,
            "placed_ratio": round(placed / total, 4) if total else None,
        },
        "errors": errors,
        "warnings": warnings,
    }


def _section_loads(lessons) -> dict[uuid.UUID, int]:
    """Whole-section lessons add up; groups of one division run in parallel, so a
    division contributes the load of its busiest group."""
    whole = defaultdict(int)
    by_group = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))  # section -> division -> group -> n
    for l in lessons:
        for t in l.targets:
            if t.group_id is None:
                whole[t.section_id] += l.periods_per_week
            else:
                by_group[t.section_id][t.group.division_id][t.group_id] += l.periods_per_week
    out = dict(whole)
    for sid, divs in by_group.items():
        out[sid] = out.get(sid, 0) + sum(max(g.values()) for g in divs.values())
    return out


def _max_periods_per_day(checker, lessons, school_days) -> int:
    best = 0
    grades = {}
    for l in lessons:
        for t in l.targets:
            grades[t.section.grade_id] = t.section.grade
    for g in grades.values():
        for wd in school_days:
            p = checker.bells.periods(g, wd.id)
            if p:
                best = max(best, len(p))
    return best
