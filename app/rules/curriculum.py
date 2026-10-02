"""Study plan checks: each section's lessons compared with its grade's plan, subject by subject.

A section's periods of a subject = its whole-section lessons + for split lessons (boys/girls, drama/music)
the busiest group of each division, because those groups are taught at the same time.
"""
from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import select

from app.arabic import count
from app.extensions import db
from app.models import (
    Card,
    CurriculumItem,
    Grade,
    Lesson,
    LessonTarget,
    LessonTeacher,
    Section,
    Stage,
    StudentGroup,
    Subject,
    Teacher,
    Timetable,
    Weekday,
)
from app.rules.bells import BellCache

STATUS_AR = {"ok": "مطابق للخطة", "missing": "غير موجود", "under": "أقل من الخطة", "over": "أكثر من الخطة",
             "extra": "ليس في الخطة"}
STATUS_EN = {"ok": "Matches the plan", "missing": "Missing", "under": "Below the plan", "over": "Above the plan",
             "extra": "Not in the plan"}


def plan_by_grade() -> dict[uuid.UUID, dict[uuid.UUID, CurriculumItem]]:
    out: dict = defaultdict(dict)
    for it in db.session.scalars(select(CurriculumItem)):
        out[it.grade_id][it.subject_id] = it
    return out


def section_subject_periods(lessons: list[Lesson]) -> tuple[dict, dict]:
    """(section, subject) -> weekly periods, and (section, subject) -> lessons."""
    whole = defaultdict(int)
    by_group = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))   # key -> division -> group -> n
    lessons_of = defaultdict(list)
    for l in lessons:
        if l.is_meeting:
            continue
        for t in l.targets:
            key = (t.section_id, l.subject_id)
            if l not in lessons_of[key]:
                lessons_of[key].append(l)
            if t.group_id is None:
                whole[key] += l.periods_per_week
            else:
                g = t.group or db.session.get(StudentGroup, t.group_id)
                by_group[key][g.division_id][t.group_id] += l.periods_per_week
    out = dict(whole)
    for key, divs in by_group.items():
        out[key] = out.get(key, 0) + sum(max(gs.values()) for gs in divs.values())
    return out, lessons_of


def _week_capacity(tt: Timetable, grades: list[Grade]) -> dict[uuid.UUID, int]:
    bells = BellCache(tt.term_id)
    days = db.session.scalars(select(Weekday).where(Weekday.is_school_day.is_(True))).all()
    return {g.id: sum(len(bells.periods(g, d.id) or {}) for d in days) for g in grades}


def check(tt: Timetable) -> dict:
    plan = plan_by_grade()
    lessons = list(db.session.scalars(select(Lesson).where(Lesson.timetable_id == tt.id)))
    actual, lessons_of = section_subject_periods(lessons)
    subjects = {s.id: s for s in db.session.scalars(select(Subject))}
    grades = {g.id: g for g in db.session.scalars(select(Grade))}
    stages = {s.id: s for s in db.session.scalars(select(Stage))}
    sections = sorted(db.session.scalars(select(Section)),
                      key=lambda s: (stages[grades[s.grade_id].stage_id].sort_order if grades[s.grade_id].stage_id in stages else 0,
                                     grades[s.grade_id].sort_order or 0, grades[s.grade_id].name_ar, s.name_ar))
    capacity = _week_capacity(tt, list(grades.values()))
    rows, totals = [], []
    summary = defaultdict(int)
    no_plan_grades = set()
    for sec in sections:
        g = grades[sec.grade_id]
        gp = plan.get(g.id, {})
        if not gp:
            no_plan_grades.add(g.id)
            continue
        subject_ids = set(gp) | {sid for (s_id, sid) in actual if s_id == sec.id}
        plan_total = actual_total = 0
        for sid in sorted(subject_ids, key=lambda i: subjects[i].name_ar if i in subjects else ""):
            want = gp[sid].periods_per_week if sid in gp else 0
            have = actual.get((sec.id, sid), 0)
            ls = lessons_of.get((sec.id, sid), [])
            status = ("extra" if not want else "missing" if not have else "ok" if have == want
                      else "under" if have < want else "over")
            summary[status] += 1
            plan_total += want
            actual_total += have
            no_teacher = [l for l in ls if not l.teacher_ids]
            # a single lesson of this section alone can be corrected automatically
            own = [l for l in ls if len(l.targets) == 1 and l.targets[0].group_id is None]
            fixable = status == "missing" or (status in ("under", "over") and len(ls) == 1 and len(own) == 1)
            rows.append({
                "id": f"{sec.id}:{sid}", "section_id": str(sec.id), "grade_id": str(g.id), "stage_id": str(g.stage_id),
                "subject_id": str(sid), "section": section_label(sec, g), "subject": subjects[sid].name_ar if sid in subjects else "?",
                "subject_en": (subjects[sid].name_en or subjects[sid].name_ar) if sid in subjects else "?",
                "plan": want, "actual": have, "diff": have - want, "status": status,
                "label": STATUS_AR[status], "label_en": STATUS_EN[status],
                "lesson_ids": [str(l.id) for l in ls], "no_teacher": len(no_teacher),
                "shared": any(len(l.targets) > 1 for l in ls), "fixable": fixable,
            })
        cap = capacity.get(g.id, 0)
        totals.append({"section_id": str(sec.id), "section": section_label(sec, g), "plan": plan_total,
                       "actual": actual_total, "capacity": cap,
                       "status": "over_capacity" if plan_total > cap and cap else "ok"})
    no_teacher = sum(r["no_teacher"] for r in rows)
    return {"rows": rows, "sections": totals, "summary": dict(summary, no_teacher=no_teacher,
                                                                 issues=sum(v for k, v in summary.items() if k != "ok")),
            "no_plan_grades": [{"id": str(i), "name": grades[i].name_ar} for i in sorted(no_plan_grades, key=lambda i: grades[i].name_ar)],
            "plan_items": sum(len(v) for v in plan.values())}


def section_label(sec: Section, g: Grade) -> str:
    return sec.name_ar if sec.name_ar.replace(" ", "").startswith(g.name_ar.replace(" ", "")) else f"{g.name_ar} / {sec.name_ar}"


def issues_for_validation(tt: Timetable) -> list[dict]:
    """Warnings for the validation page: every subject of every section that does not match the plan."""
    rep = check(tt)
    out = []
    for r in rep["rows"]:
        if r["status"] == "ok" and not r["no_teacher"]:
            continue
        if r["status"] == "missing":
            msg = f"{r['section']}: لا يوجد درس {r['subject']}، والخطة {count(r['plan'], 'period')} أسبوعياً"
        elif r["status"] == "under":
            msg = f"{r['section']}: حصص {r['subject']} {r['actual']}، والخطة {r['plan']} (نقص {r['plan'] - r['actual']})"
        elif r["status"] == "over":
            msg = f"{r['section']}: حصص {r['subject']} {r['actual']}، والخطة {r['plan']} (زيادة {r['actual'] - r['plan']})"
        elif r["status"] == "extra":
            msg = f"{r['section']}: مبحث {r['subject']} ليس في الخطة الدراسية لهذا الصف"
        else:
            msg = None
        if msg:
            out.append({"code": f"curriculum_{r['status']}", "message": msg,
                        "message_en": f"{r['section']}: {r['subject_en']} — {r['label_en']} ({r['actual']}/{r['plan']})",
                        "section_id": r["section_id"], "subject_id": r["subject_id"]})
        if r["no_teacher"]:
            out.append({"code": "lesson_no_teacher", "message": f"{r['section']}: درس {r['subject']} بلا معلم",
                        "message_en": f"{r['section']}: {r['subject_en']} has no teacher",
                        "section_id": r["section_id"], "subject_id": r["subject_id"]})
    for s in rep["sections"]:
        if s["status"] == "over_capacity":
            out.append({"code": "curriculum_over_capacity",
                        "message": f"{s['section']}: الخطة الدراسية {count(s['plan'], 'period')}، وأسبوع الشعبة {count(s['capacity'], 'slot')} فقط",
                        "message_en": f"{s['section']}: plan has {s['plan']} periods, the week only {s['capacity']}",
                        "section_id": s["section_id"]})
    return out


def qualified_teacher(subject_id, stage_id) -> Teacher | None:
    """The only teacher registered for this subject in this stage, if there is exactly one."""
    rows = [t for t in db.session.scalars(select(Teacher))
            if any(s.id == subject_id for s in t.subjects) and any(st.id == stage_id for st in t.stages)]
    return rows[0] if len(rows) == 1 else None


def apply(tt: Timetable, keys: list[str] | None, assign_teacher: bool, can_write) -> dict:
    """Create the missing lessons, and set the weekly periods of a section's own single lesson to the plan.
    keys: ["<section_id>:<subject_id>", …] (None = every fixable row). Shared lessons are left alone."""
    from app.api.scheduling import _sync_cards, card_durations
    from app.models import Occupancy
    from app.rules.placement import rebuild_occupancy
    rep = check(tt)
    plan = plan_by_grade()
    wanted = set(keys) if keys is not None else None
    created, adjusted, skipped, assigned = 0, 0, [], 0
    for r in rep["rows"]:
        if wanted is not None and r["id"] not in wanted:
            continue
        if r["status"] not in ("missing", "under", "over"):
            continue
        if not r["fixable"]:
            skipped.append({"id": r["id"], "reason": "shared",
                            "message": f"{r['section']} — {r['subject']}: درس مشترك أو مقسّم، عدّله يدوياً"})
            continue
        sec_id, sub_id = uuid.UUID(r["section_id"]), uuid.UUID(r["subject_id"])
        item = plan[uuid.UUID(r["grade_id"])][sub_id]
        if r["status"] == "missing":
            lesson = Lesson(timetable_id=tt.id, subject_id=sub_id, periods_per_week=item.periods_per_week,
                            duration=item.duration, kind="lesson", counts_load=True)
            lesson.targets = [LessonTarget(section_id=sec_id, group_id=None)]
            if assign_teacher:
                t = qualified_teacher(sub_id, uuid.UUID(r["stage_id"]))
                if t is not None:
                    lesson.teachers = [LessonTeacher(teacher_id=t.id, role="main")]
                    assigned += 1
            if not can_write(lesson):
                skipped.append({"id": r["id"], "reason": "forbidden", "message": f"{r['section']}: ليست ضمن مراحلك"})
                continue
            db.session.add(lesson)
            for d in card_durations(item.periods_per_week, item.duration):
                db.session.add(Card(timetable_id=tt.id, lesson=lesson, duration=d, week_no=None))
            created += 1
        else:
            lesson = db.session.get(Lesson, uuid.UUID(r["lesson_ids"][0]))
            if not can_write(lesson):
                skipped.append({"id": r["id"], "reason": "forbidden", "message": f"{r['section']}: ليست ضمن مراحلك"})
                continue
            live = [c for c in lesson.cards if c.deleted_at is None]
            lesson.periods_per_week = item.periods_per_week
            _sync_cards(lesson, tt, live, card_durations(item.periods_per_week, lesson.duration), False)
            db.session.flush()
            for c in lesson.cards:
                if c.deleted_at is None:
                    rebuild_occupancy(c, lesson, tt)
                else:
                    db.session.query(Occupancy).filter(Occupancy.card_id == c.id).delete()
            adjusted += 1
    db.session.flush()
    return {"created": created, "adjusted": adjusted, "assigned": assigned, "skipped": skipped}
