"""Bundle → database. One code path for preview (rolled back) and commit.

Matching rules (so re-importing the same file never duplicates anything):
  stage / subject / teacher / room  → by Arabic or English name (or short code), ignoring diacritics, hamza forms…
  grade   → by name within its stage;  section → by name within its grade;  group → by name within its section
  lesson  → same subject + same sections/groups + same teachers in the target timetable
Fields present in the file overwrite stored values; fields the file leaves empty are kept.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.orm import selectinload

from app.api.scheduling import _sync_cards, card_durations, editable_timetable
from app.errors import ApiError
from app.extensions import db
from app.importing.asc import split_class_name
from app.importing.bundle import Bundle, Issue
from app.importing.text import norm
from app.models import (
    AcademicYear,
    BellAssignment,
    BellSchedule,
    BellSlot,
    Card,
    Division,
    Grade,
    Lesson,
    LessonTarget,
    LessonTeacher,
    Occupancy,
    Room,
    Section,
    Stage,
    StudentGroup,
    Subject,
    Teacher,
    Term,
    Timetable,
    Weekday,
)
from app.models.base import new_id

ENTITIES = ("stages", "grades", "sections", "divisions", "groups", "subjects", "teachers", "rooms",
            "bell_schedules", "lessons")
MAX_ISSUES = 300
ASC_STAGE = "مستورد من aSc"


def _digits(name: str) -> int:
    m = re.search(r"\d+", name or "")
    return int(m.group()) if m else 0


class Importer:
    def __init__(self, bundle: Bundle, *, stage_id=None, stage_name: str | None = None, timetable_id=None,
                 new_timetable_name: str | None = None, term_id=None):
        self.b = bundle
        self.stage_id, self.stage_name = stage_id, stage_name
        self.timetable_id, self.new_tt_name, self.term_id = timetable_id, new_timetable_name, term_id
        self.stats = {e: {"created": 0, "updated": 0, "unchanged": 0} for e in ENTITIES}
        self.created_names: dict[str, list[str]] = defaultdict(list)
        self.cards = {"placed": 0, "unplaced": 0}
        self.tt: Timetable | None = None
        self.tt_created = False
        # key (from the file) → object
        self.k_subject: dict[str, Subject] = {}
        self.k_teacher: dict[str, Teacher] = {}
        self.k_room: dict[str, Room] = {}
        self.k_section: dict[str, Section] = {}
        self.k_group: dict[str, StudentGroup] = {}
        self.k_lesson: dict[str, Lesson] = {}
        self._load()

    # ------------------------------------------------------------------ indexes
    def _load(self):
        q = lambda m: db.session.scalars(select(m)).all()  # noqa: E731
        self.stages = q(Stage)
        self.grades = q(Grade)
        self.sections = q(Section)
        self.divisions = q(Division)
        self.groups = q(StudentGroup)
        self.i_subject, self.i_teacher, self.i_room, self.i_stage = {}, {}, {}, {}
        for s in q(Subject):
            self._index(self.i_subject, s, s.name_ar, s.name_en, s.short_ar, s.short_en)
        for t in q(Teacher):
            self._index(self.i_teacher, t, t.name_ar, t.name_en, t.short)
        for r in q(Room):
            self._index(self.i_room, r, r.name_ar, r.name_en, r.short)
        for s in self.stages:
            self._index(self.i_stage, s, s.name_ar, s.name_en)

    @staticmethod
    def _index(idx: dict, obj, *names):
        for n in names:
            k = norm(n)
            if k and k not in idx:
                idx[k] = obj

    def _issue(self, kind: str, ar: str, en: str, rec: dict | None = None, where: str = ""):
        (self.b.errors if kind == "error" else self.b.warnings).append(
            Issue(ar, en, (rec or {}).get("where") or where, (rec or {}).get("row")))

    def _upsert(self, entity: str, obj, values: dict, created: bool, label: str):
        changed = False
        for k, v in values.items():
            if v is None:
                continue
            if getattr(obj, k) != v:
                setattr(obj, k, v)
                changed = True
        if created:
            db.session.add(obj)
            self.stats[entity]["created"] += 1
            if len(self.created_names[entity]) < 60:
                self.created_names[entity].append(label)
        else:
            self.stats[entity]["updated" if changed else "unchanged"] += 1
        return obj

    # ------------------------------------------------------------------ run
    def run(self) -> dict:
        b = self.b
        for s in b.subjects:
            self.k_subject[s["key"]] = self.subject(s["name"], s)
        for r in b.rooms:
            self.k_room[r["key"]] = self.room(r["name"], r)
        for t in b.teachers:
            self.k_teacher[t["key"]] = self.teacher(t["name"], t)
        db.session.flush()
        for t in b.teachers:  # links need the subjects/stages above
            obj = self.k_teacher[t["key"]]
            for sname in t.get("subjects") or []:
                s = self.find_subject(sname) or self.subject(sname, {})
                if s not in obj.subjects:
                    obj.subjects.append(s)
            for stname in t.get("stages") or []:
                st = self.stage(stname)
                if st not in obj.stages:
                    obj.stages.append(st)
        for s in b.sections:
            sec = self.section_row(s)
            if sec is not None:
                self.k_section[s["key"]] = sec
        db.session.flush()
        for d in b.divisions:
            self.division(d)
        if b.lessons:
            self.timetable()
            db.session.flush()
            self.lessons()
            db.session.flush()
        if b.cards and self.tt is not None:
            self.bells()
            db.session.flush()
            self.place_cards()
            db.session.flush()
        return self.report()

    def report(self) -> dict:
        return {
            "source": self.b.source,
            "summary": self.stats,
            "created": dict(self.created_names),
            "cards": self.cards,
            "timetable": ({"id": str(self.tt.id), "name": self.tt.name, "created": self.tt_created}
                          if self.tt is not None else None),
            "errors": [i.as_dict() for i in self.b.errors[:MAX_ISSUES]],
            "warnings": [i.as_dict() for i in self.b.warnings[:MAX_ISSUES]],
            "error_count": len(self.b.errors),
            "warning_count": len(self.b.warnings),
        }

    # ------------------------------------------------------------------ simple resources
    def find_subject(self, name):
        return self.k_subject.get(name) or self.i_subject.get(norm(name))

    def find_teacher(self, name):
        return self.k_teacher.get(name) or self.i_teacher.get(norm(name))

    def find_room(self, name):
        return self.k_room.get(name) or self.i_room.get(norm(name))

    def subject(self, name: str, rec: dict) -> Subject:
        obj = self.i_subject.get(norm(name))
        created = obj is None
        if created:
            obj = Subject(id=new_id(), name_ar=name, max_teachers_per_block=1)
        vals = {"name_en": rec.get("name_en") if rec else None, "short_ar": (rec or {}).get("short"),
                "short_en": (rec or {}).get("short_en"), "color": (rec or {}).get("color"),
                "requires_room_type": (rec or {}).get("room_type")}
        if vals["short_ar"]:
            vals["short_ar"] = vals["short_ar"][:20]
        if vals["short_en"]:
            vals["short_en"] = vals["short_en"][:20]
        if vals["color"] and not re.fullmatch(r"#[0-9A-Fa-f]{3,8}", vals["color"]):
            vals["color"] = None
        self._upsert("subjects", obj, vals, created, name)
        self._index(self.i_subject, obj, name, vals["name_en"], vals["short_ar"])
        return obj

    def room(self, name: str, rec: dict) -> Room:
        obj = self.i_room.get(norm(name))
        created = obj is None
        if created:
            obj = Room(id=new_id(), name_ar=name, is_shared=False)
        vals = {"name_en": rec.get("name_en"), "short": (rec.get("short") or None) and rec["short"][:20],
                "room_type": (rec.get("room_type") or None) and rec["room_type"][:30],
                "capacity": rec.get("capacity"), "is_shared": rec.get("shared")}
        self._upsert("rooms", obj, vals, created, name)
        self._index(self.i_room, obj, name, vals["name_en"], vals["short"])
        return obj

    def teacher(self, name: str, rec: dict) -> Teacher:
        obj = self.i_teacher.get(norm(name))
        created = obj is None
        if created:
            obj = Teacher(id=new_id(), name_ar=name)
        vals = {"name_en": rec.get("name_en"), "short": (rec.get("short") or None) and rec["short"][:20],
                "email": rec.get("email"), "phone": (rec.get("phone") or None) and rec["phone"][:30],
                "title": (rec.get("title") or None) and rec["title"][:40], "gender": rec.get("gender"),
                "color": rec.get("color") if rec.get("color") and re.fullmatch(r"#[0-9A-Fa-f]{3,8}", rec["color"]) else None,
                "target_weekly_periods": rec.get("target")}
        self._upsert("teachers", obj, vals, created, name)
        self._index(self.i_teacher, obj, name, vals["name_en"], vals["short"])
        return obj

    # ------------------------------------------------------------------ structure
    def stage(self, name: str) -> Stage:
        obj = self.i_stage.get(norm(name))
        if obj is None:
            obj = Stage(id=new_id(), name_ar=name, sort_order=len(self.stages) + 1)
            self._upsert("stages", obj, {}, True, name)
            self.stages.append(obj)
            self._index(self.i_stage, obj, name)
        return obj

    def default_stage(self, rec) -> Stage | None:
        if self.stage_id:
            st = next((s for s in self.stages if s.id == self.stage_id), None)
            if st:
                return st
        if self.stage_name:
            return self.stage(self.stage_name)
        if len(self.stages) == 1:
            return self.stages[0]
        if not self.stages:
            return self.stage("المرحلة الأولى")
        if not self.b.by_name:  # aSc has no stages: keep its classes together in one stage of their own
            if not any(norm(s.name_ar) == norm(ASC_STAGE) for s in self.stages):
                self._issue("warning", f"وُضعت صفوف aSc في مرحلة جديدة «{ASC_STAGE}»؛ يمكنك اختيار مرحلة قبل الاستيراد أو نقل الصفوف لاحقاً",
                            f"aSc grades were put in a new stage '{ASC_STAGE}'; choose a stage before importing or move the grades later")
            return self.stage(ASC_STAGE)
        label = (rec or {}).get("name") or ""
        self._issue("error", f"حدّد مرحلة الشعبة «{label}» (عمود «المرحلة» أو اختيار المرحلة قبل الاستيراد)",
                    f"Specify the stage of section '{label}' (a 'Stage' column or the stage choice before importing)", rec)
        return None

    def grade(self, stage_name: str | None, name: str, rec) -> Grade | None:
        k = norm(name)
        if stage_name:
            st = self.stage(stage_name)
            cands = [g for g in self.grades if g.stage_id == st.id and norm(g.name_ar) == k]
        else:
            cands = [g for g in self.grades if norm(g.name_ar) == k or norm(g.name_en) == k]
            if self.stage_id or self.stage_name:
                st = self.default_stage(rec)
                cands = [g for g in cands if g.stage_id == st.id] if st else cands
            if len(cands) > 1:
                self._issue("error", f"الصف «{name}» موجود في أكثر من مرحلة؛ أضف عمود «المرحلة»",
                            f"Grade '{name}' exists in several stages; add a 'Stage' column", rec)
                return None
            st = None if cands else self.default_stage(rec)
            if not cands and st is None:
                return None
        if cands:
            return cands[0]
        g = Grade(id=new_id(), stage_id=st.id, name_ar=name,
                  sort_order=_digits(name) or len([x for x in self.grades if x.stage_id == st.id]) + 1)
        self._upsert("grades", g, {}, True, name)
        self.grades.append(g)
        return g

    def section_row(self, s: dict) -> Section | None:
        g = self.grade(s.get("stage"), s["grade"], s)
        if g is None:
            return None
        obj = next((x for x in self.sections if x.grade_id == g.id and norm(x.name_ar) == norm(s["name"])), None)
        created = obj is None
        if created:
            obj = Section(id=new_id(), grade_id=g.id, name_ar=s["name"])
            self.sections.append(obj)
        teacher = self.find_teacher(s["class_teacher"]) if s.get("class_teacher") else None
        room = self.find_room(s["home_room"]) if s.get("home_room") else None
        if s.get("class_teacher") and teacher is None:
            self._issue("warning", f"مربي الصف «{s['class_teacher']}» غير موجود؛ تُرك فارغاً",
                        f"Class teacher '{s['class_teacher']}' not found; left empty", s)
        vals = {"name_en": s.get("name_en"), "student_count": s.get("student_count"),
                "class_teacher_id": teacher.id if teacher else None, "home_room_id": room.id if room else None}
        return self._upsert("sections", obj, vals, created, f"{g.name_ar} / {s['name']}")

    def division(self, d: dict):
        sec = self.k_section.get(d["section"])
        if sec is None:
            return
        wanted = {norm(gr["name"]) for gr in d["groups"]}
        div = next((x for x in self.divisions if x.section_id == sec.id and (
            norm(x.name) == norm(d["name"]) or wanted <= {norm(gg.name_ar) for gg in self.groups if gg.division_id == x.id})), None)
        created = div is None
        if created:
            div = Division(id=new_id(), section_id=sec.id, name=d["name"])
            self.divisions.append(div)
        self._upsert("divisions", div, {}, created, f"{sec.name_ar}: {d['name']}")
        for gr in d["groups"]:
            obj = next((x for x in self.groups if x.division_id == div.id and norm(x.name_ar) == norm(gr["name"])), None)
            gc = obj is None
            if gc:
                obj = StudentGroup(id=new_id(), division_id=div.id, name_ar=gr["name"])
                self.groups.append(obj)
            self._upsert("groups", obj, {"student_count": gr.get("student_count")}, gc, gr["name"])
            self.k_group[gr["key"]] = obj

    # ------------------------------------------------------------------ timetable & lessons
    def timetable(self):
        if self.timetable_id:
            self.tt = editable_timetable(self.timetable_id)
            return
        term = db.session.get(Term, self.term_id) if self.term_id else None
        if term is None:
            year = db.session.scalars(select(AcademicYear).where(AcademicYear.is_current.is_(True))).first() \
                or db.session.scalars(select(AcademicYear).order_by(AcademicYear.start_date.desc().nullslast())).first()
            if year is None:
                today = datetime.now().date()
                y = today.year if today.month >= 8 else today.year - 1
                year = AcademicYear(id=new_id(), name=f"{y}/{y + 1}", is_current=True)
                db.session.add(year)
                db.session.flush()
            term = db.session.scalars(select(Term).where(Term.academic_year_id == year.id).order_by(Term.ordinal)).first()
            if term is None:
                term = Term(id=new_id(), academic_year_id=year.id, name_ar="الفصل الأول", name_en="Term 1", ordinal=1)
                db.session.add(term)
                db.session.flush()
        self.tt = Timetable(id=new_id(), term_id=term.id, name=self.new_tt_name or "جدول مستورد", status="draft",
                            cycle_weeks=1)
        db.session.add(self.tt)
        self.tt_created = True

    def _resolve_target(self, ref, group_ref, rec) -> tuple[Section, StudentGroup | None] | None:
        if isinstance(ref, str):  # aSc key
            sec = self.k_section.get(ref)
            grp = self.k_group.get(group_ref) if group_ref else None
            return (sec, grp) if sec else None
        sec = None
        if ref.get("grade"):
            g = self.grade(ref.get("stage"), ref["grade"], rec)
            if g is None:
                return None
            sec = next((x for x in self.sections if x.grade_id == g.id and norm(x.name_ar) == norm(ref["name"])), None)
            if sec is None:
                sec = self.section_row({"stage": ref.get("stage"), "grade": ref["grade"], "name": ref["name"],
                                        "row": rec.get("row"), "where": rec.get("where")})
        else:
            k = norm(ref["name"])
            cands = [x for x in self.sections if norm(x.name_ar) == k or norm(x.name_en) == k]
            if not cands:
                split = split_class_name(ref["name"])
                if split:
                    gk, sk = norm(split[0]), norm(split[1])
                    gids = {g.id for g in self.grades if norm(g.name_ar) == gk}
                    cands = [x for x in self.sections if x.grade_id in gids and norm(x.name_ar) == sk]
            if len(cands) > 1:
                self._issue("error", f"الشعبة «{ref['text']}» غير محددة؛ اكتبها بصيغة «الصف / الشعبة» أو أضف عمود «الصف»",
                            f"Section '{ref['text']}' is ambiguous; write it as 'grade / section' or add a 'Grade' column", rec)
                return None
            sec = cands[0] if cands else None
        if sec is None:
            self._issue("error", f"الشعبة «{ref['text']}» غير موجودة", f"Section '{ref['text']}' not found", rec)
            return None
        grp = None
        if group_ref:
            div_ids = {d.id for d in self.divisions if d.section_id == sec.id}
            grp = next((x for x in self.groups if x.division_id in div_ids and
                        norm(group_ref) in (norm(x.name_ar), norm(x.name_en))), None)
            if grp is None:
                self._issue("error", f"المجموعة «{group_ref}» غير موجودة في الشعبة «{ref['text']}»؛ أنشئها من صفحة التقسيمات",
                            f"Group '{group_ref}' not found in section '{ref['text']}'; create it on the Divisions page", rec)
                return None
        return sec, grp

    def lessons(self):
        tt = self.tt
        existing = db.session.scalars(select(Lesson).where(Lesson.timetable_id == tt.id).options(
            selectinload(Lesson.teachers), selectinload(Lesson.targets), selectinload(Lesson.cards))).all()
        sig = lambda subj, targets, teachers: (subj, frozenset(targets), frozenset(teachers))  # noqa: E731
        by_sig = {sig(l.subject_id, [(t.section_id, t.group_id) for t in l.targets], l.teacher_ids): l for l in existing}
        asc = not self.b.by_name
        for rec in self.b.lessons:
            subj = self.k_subject.get(rec["subject"]) if asc else self.find_subject(rec["subject"])
            if subj is None:
                if asc:
                    self._issue("warning", "تُجوهل درس مبحثه غير معرّف في الملف", "Skipped a lesson with an unknown subject", rec)
                    continue
                subj = self.subject(rec["subject"], {})
            teachers, bad = [], False
            for tname in rec["teachers"]:
                t = self.k_teacher.get(tname) if asc else self.find_teacher(tname)
                if t is None:
                    if asc:
                        continue
                    t = self.teacher(tname, {})
                if t not in teachers:
                    teachers.append(t)
            targets = []
            for ref, gref in rec["targets"]:
                r = self._resolve_target(ref, gref, rec)
                if r is None:
                    bad = True
                    break
                if (r[0].id, r[1].id if r[1] else None) not in {(a.id, b.id if b else None) for a, b in targets}:
                    targets.append(r)
            if bad or not targets:
                continue
            room = None
            if rec.get("room"):
                room = self.k_room.get(rec["room"]) if asc else self.find_room(rec["room"])
                if room is None and not asc:
                    room = self.room(rec["room"], {})
            if len(teachers) > subj.max_teachers_per_block:
                subj.max_teachers_per_block = len(teachers)
                self._issue("warning", f"رُفع الحد الأقصى لمعلمي البطاقة في مبحث «{subj.name_ar}» إلى {len(teachers)}",
                            f"Raised max teachers per card for '{subj.name_ar}' to {len(teachers)}", rec)
            db.session.flush()
            key = sig(subj.id, [(s.id, g.id if g else None) for s, g in targets], [t.id for t in teachers])
            ppw, dur = rec["ppw"], min(rec["duration"], rec["ppw"])
            lesson = by_sig.get(key)
            label = f"{subj.name_ar} — {'، '.join(s.name_ar for s, _ in targets)}"
            if lesson is not None:
                live = [c for c in lesson.cards if c.deleted_at is None]
                if (lesson.periods_per_week, lesson.duration) == (ppw, dur):
                    self.stats["lessons"]["unchanged"] += 1
                else:
                    reset = dur != lesson.duration
                    lesson.periods_per_week, lesson.duration = ppw, dur
                    _sync_cards(lesson, tt, live, card_durations(ppw, dur), reset)
                    self.stats["lessons"]["updated"] += 1
                if room and lesson.preferred_room_id is None:
                    lesson.preferred_room_id = room.id
            else:
                lesson = Lesson(id=new_id(), timetable_id=tt.id, subject_id=subj.id, periods_per_week=ppw,
                                duration=dur, preferred_room_id=room.id if room else None, notes=rec.get("notes"))
                lesson.teachers = [LessonTeacher(teacher_id=t.id, role="main") for t in teachers]
                lesson.targets = [LessonTarget(section_id=s.id, group_id=g.id if g else None) for s, g in targets]
                self._upsert("lessons", lesson, {}, True, label)
                for d in card_durations(ppw, dur):
                    db.session.add(Card(id=new_id(), timetable_id=tt.id, lesson=lesson, duration=d))
                by_sig[key] = lesson
            if rec.get("key"):
                self.k_lesson[rec["key"]] = lesson
            # Teachers teach this subject in these stages (used by permissions and pickers).
            stage_ids = {next(g.stage_id for g in self.grades if g.id == s.grade_id) for s, _ in targets}
            for t in teachers:
                if subj not in t.subjects:
                    t.subjects.append(subj)
                for st in self.stages:
                    if st.id in stage_ids and st not in t.stages:
                        t.stages.append(st)

    # ------------------------------------------------------------------ aSc bells & placement
    def school_days(self) -> list[Weekday]:
        return db.session.scalars(select(Weekday).where(Weekday.is_school_day.is_(True)).order_by(Weekday.sort_order)).all()

    def bells(self):
        """A timing template from the aSc periods, assigned to every stage/day that has none yet."""
        periods = self.b.periods
        if not periods:
            return
        if not all(p["start"] and p["end"] for p in periods):
            start = datetime(2000, 1, 1, 7, 30)
            for p in periods:
                p["start"], p["end"] = start.strftime("%H:%M"), (start + timedelta(minutes=45)).strftime("%H:%M")
                start += timedelta(minutes=50)
            self._issue("warning", "لا توجد أوقات للحصص في الملف؛ وُضعت أوقات تقريبية فعدّلها من صفحة توقيت الحصص",
                        "No period times in the file; approximate times were used — adjust them on the Bell times page")
        name = "توقيت aSc"
        sched = db.session.scalars(select(BellSchedule).where(BellSchedule.name_ar == name)).first()
        if sched is None:
            sched = BellSchedule(id=new_id(), name_ar=name, name_en="aSc timing")
            prev_end = None
            slots, n = [], 0
            for p in periods:
                st = time.fromisoformat(p["start"])
                en = time.fromisoformat(p["end"])
                if en <= st or (prev_end and st < prev_end):
                    self._issue("warning", "أوقات الحصص في الملف متداخلة؛ لم يُنشأ قالب التوقيت",
                                "Period times in the file overlap; no timing template was created")
                    return
                if prev_end and st > prev_end:
                    n += 1
                    slots.append(BellSlot(slot_no=n, kind="break", starts_at=prev_end, ends_at=st, label_ar="استراحة",
                                          label_en="Break"))
                n += 1
                slots.append(BellSlot(slot_no=n, kind="lesson", period_no=p["no"], starts_at=st, ends_at=en))
                prev_end = en
            sched.slots = slots
            self._upsert("bell_schedules", sched, {}, True, name)
            db.session.flush()
        stage_ids = {g.stage_id for g in self.grades for s in self.k_section.values() if s.grade_id == g.id}
        days = self.school_days()[: self.b.days or None]
        existing = {(a.stage_id, a.weekday_id) for a in db.session.scalars(select(BellAssignment).where(
            BellAssignment.term_id == self.tt.term_id, BellAssignment.grade_id.is_(None)))}
        for sid in stage_ids:
            for d in days:
                if (sid, d.id) not in existing:
                    db.session.add(BellAssignment(id=new_id(), term_id=self.tt.term_id, weekday_id=d.id,
                                                  stage_id=sid, bell_schedule_id=sched.id))

    def place_cards(self):
        from app.rules.bells import BellCache
        tt = self.tt
        days = self.school_days()
        if self.b.days > len(days):
            self._issue("warning", f"في ملف aSc {self.b.days} أيام وفي النظام {len(days)} أيام دراسية؛ لم تُوزَّع حصص الأيام الزائدة",
                        f"The aSc file has {self.b.days} days but the system has {len(days)} school days; extra days were skipped")
        bells = BellCache(tt.term_id)
        grade_of = {g.id: g for g in self.grades}
        section_of = {s.id: s for s in self.sections}
        group_div = {g.id: g.division_id for g in self.groups}

        busy: dict[tuple, set[int]] = defaultdict(set)            # (type, id, day) → periods
        class_busy: dict[tuple, list] = defaultdict(list)          # (section, day) → [(period, group_id)]
        for o in db.session.scalars(select(Occupancy).where(Occupancy.timetable_id == tt.id)):
            busy[(o.resource_type, o.resource_id, o.weekday_id)].update(range(o.periods.lower, o.periods.upper))
        placed = db.session.scalars(select(Card).where(Card.timetable_id == tt.id, Card.weekday_id.is_not(None))
                                    .options(selectinload(Card.lesson).selectinload(Lesson.targets))).all()
        for c in placed:
            for t in c.lesson.targets:
                for p in range(c.period_no, c.period_no + c.duration):
                    class_busy[(t.section_id, c.weekday_id)].append((p, t.group_id))

        by_lesson: dict[str, list[dict]] = defaultdict(list)
        for c in self.b.cards:
            by_lesson[c["lesson"]].append(c)
        rooms = {r.id: r for r in db.session.scalars(select(Room))}
        for lkey, cards in by_lesson.items():
            lesson = self.k_lesson.get(lkey)
            if lesson is None:
                continue
            free = [c for c in lesson.cards if c.deleted_at is None and c.weekday_id is None]
            if not free:
                continue
            dur = lesson.duration
            per_block = dur > 1 and len(cards) == len(card_durations(lesson.periods_per_week, dur)) \
                and len(cards) != lesson.periods_per_week
            blocks = []
            per_day = defaultdict(list)
            for c in cards:
                per_day[c["day"]].append(c)
            for day, cs in per_day.items():
                cs.sort(key=lambda c: c["period"])
                if per_block:
                    blocks += [(day, c["period"], None, c["room"]) for c in cs]
                    continue
                run = [cs[0]]
                for c in cs[1:] + [None]:
                    if c is not None and c["period"] == run[-1]["period"] + 1:
                        run.append(c)
                        continue
                    for i in range(0, len(run), dur):
                        chunk = run[i:i + dur]
                        blocks.append((day, chunk[0]["period"], len(chunk), chunk[0]["room"]))
                    if c is not None:
                        run = [c]
            teacher_ids = lesson.teacher_ids
            for day_idx, start, length, room_key in blocks:
                if day_idx >= len(days):
                    self.cards["unplaced"] += 1
                    continue
                card = next((c for c in free if length is None or c.duration == length), None)
                if card is None:
                    self.cards["unplaced"] += 1
                    continue
                wd = days[day_idx].id
                periods = set(range(start, start + card.duration))
                room = self.k_room.get(room_key) if room_key else None
                room = room or (rooms.get(lesson.preferred_room_id) if lesson.preferred_room_id else None)
                reason = self._conflict(lesson, wd, periods, teacher_ids, room, busy, class_busy,
                                        bells, grade_of, section_of, group_div)
                if reason:
                    self.cards["unplaced"] += 1
                    self._issue("warning", f"بقيت حصة غير موزعة ({reason[0]})", f"A card was left unplaced ({reason[1]})",
                                where=f"{db.session.get(Subject, lesson.subject_id).name_ar}")
                    continue
                free.remove(card)
                card.weekday_id, card.period_no = wd, start
                card.room_id = room.id if room else None
                rng = Range(start, start + card.duration)
                weeks = Range(*tt.weeks_range(card.week_no))
                rows = [("teacher", t) for t in teacher_ids]
                if room and not room.is_shared:
                    rows.append(("room", room.id))
                for rtype, rid in rows:
                    db.session.add(Occupancy(timetable_id=tt.id, card_id=card.id, resource_type=rtype, resource_id=rid,
                                             weekday_id=wd, periods=rng, weeks=weeks))
                    busy[(rtype, rid, wd)].update(periods)
                for t in lesson.targets:
                    for p in periods:
                        class_busy[(t.section_id, wd)].append((p, t.group_id))
                self.cards["placed"] += 1

    @staticmethod
    def _conflict(lesson, wd, periods, teacher_ids, room, busy, class_busy, bells, grade_of, section_of, group_div):
        for t in teacher_ids:
            if busy[("teacher", t, wd)] & periods:
                return "تعارض معلم", "teacher clash"
        if room and not room.is_shared and busy[("room", room.id, wd)] & periods:
            return "تعارض قاعة", "room clash"
        for t in lesson.targets:
            sec = section_of.get(t.section_id)
            allowed = bells.periods(grade_of[sec.grade_id], wd) if sec else None
            if allowed is not None and not periods <= set(allowed):
                return "الحصة خارج توقيت الصف", "period outside the grade's bell times"
            for p, gid in class_busy[(t.section_id, wd)]:
                if p in periods:
                    same_div = gid and t.group_id and gid != t.group_id and group_div.get(gid) == group_div.get(t.group_id)
                    if not same_div:
                        return "تعارض شعبة", "class clash"
        return None


def run_import(bundle: Bundle, **opts) -> dict:
    if bundle.is_empty():
        raise ApiError("validation", 400, details={"reason": "empty_import"},
                       message="لم يُعثر في الملف على بيانات يمكن استيرادها",
                       message_en="No importable data was found in the file")
    return Importer(bundle, **opts).run()
