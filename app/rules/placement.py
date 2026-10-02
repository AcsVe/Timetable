"""Single rule engine for card placement (ERD §12).

The same function answers three callers: the save endpoint (reject), the
drag-and-drop pre-check / allowed-slots grid (colour cells before the drop)
and the validation report (re-check everything already placed). The generator
will reuse it too, so nothing can be accepted by one path and rejected by another.

Conflicts are evaluated by period number (decision #1). The database EXCLUDE
constraint on `occupancy` is a second, independent guard for teachers/rooms.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.dialects.postgresql import Range

from app.extensions import db
from app.models import (
    Availability,
    Card,
    Grade,
    Lesson,
    LessonTarget,
    Occupancy,
    Room,
    Section,
    StudentGroup,
    Subject,
    Teacher,
    Timetable,
    Weekday,
)
from app.arabic import g, teacher_title
from app.rules.bells import BellCache


@dataclass
class Conflict:
    code: str
    message: str
    message_en: str
    other_card_id: uuid.UUID | None = None
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        out = {"code": self.code, "message": self.message, "message_en": self.message_en}
        if self.other_card_id:
            out["other_card_id"] = str(self.other_card_id)
        if self.extra:
            out.update({k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in self.extra.items()})
        return out


@dataclass
class Target:
    section_id: uuid.UUID
    group_id: uuid.UUID | None


def groups_compatible(g1: StudentGroup | None, g2: StudentGroup | None) -> bool:
    """Two lessons of the same section can share a period only if they teach
    different groups of the same division (e.g. boys/girls PE, drama/music halves)."""
    if g1 is None or g2 is None:
        return False
    return g1.id != g2.id and g1.division_id == g2.division_id


def _section_label(section: Section) -> str:
    return f"{section.grade.name_ar} / {section.name_ar}"


class PlacementChecker:
    def __init__(self, timetable: Timetable):
        self.tt = timetable
        self.bells = BellCache(timetable.term_id)
        self._weekdays: dict[uuid.UUID, Weekday] = {}

    # -- public -----------------------------------------------------------
    def check(
        self,
        lesson: Lesson,
        weekday_id: uuid.UUID,
        period_no: int,
        duration: int,
        week_no: int | None,
        room_id: uuid.UUID | None,
        *,
        teacher_ids: list[uuid.UUID] | None = None,
        targets: list[Target] | None = None,
        exclude_card_ids: set[uuid.UUID] | frozenset = frozenset(),
        stop_at_first: bool = False,
    ) -> list[Conflict]:
        teacher_ids = list(lesson.teacher_ids) if teacher_ids is None else teacher_ids
        targets = [Target(t.section_id, t.group_id) for t in lesson.targets] if targets is None else targets
        out: list[Conflict] = []
        steps = (
            lambda: self._check_day(weekday_id),
            (lambda: self._check_meeting_bells(lesson, weekday_id, period_no, duration)) if lesson.is_meeting
            else (lambda: self._check_bells(targets, weekday_id, period_no, duration)),
            lambda: self._check_availability(lesson, teacher_ids, targets, room_id, weekday_id, period_no, duration),
            lambda: self._check_busy("teacher", teacher_ids, weekday_id, period_no, duration, week_no, exclude_card_ids),
            lambda: self._check_room(lesson, room_id, weekday_id, period_no, duration, week_no, exclude_card_ids),
            lambda: self._check_classes(targets, weekday_id, period_no, duration, week_no, exclude_card_ids),
        )
        for step in steps:
            out.extend(step())
            if stop_at_first and out:
                break
        return out

    # -- individual rules -------------------------------------------------
    def _check_day(self, weekday_id):
        wd = self._weekdays.get(weekday_id) or db.session.get(Weekday, weekday_id)
        if wd is None:
            return [Conflict("unknown_weekday", "يوم غير معروف", "Unknown weekday")]
        self._weekdays[weekday_id] = wd
        if not wd.is_school_day:
            return [Conflict("not_school_day", f"يوم {wd.name_ar} ليس يوماً دراسياً", f"{wd.name_en or wd.name_ar} is not a school day")]
        return []

    def _check_bells(self, targets, weekday_id, period_no, duration):
        out = []
        grades = {}
        for t in targets:
            sec = db.session.get(Section, t.section_id)
            grades[sec.grade_id] = sec.grade
        for grade in grades.values():
            periods = self.bells.periods(grade, weekday_id)
            if periods is None:
                out.append(Conflict("no_bell_schedule",
                                    f"لم يُحدَّد توقيت حصص للصف {grade.name_ar} في هذا اليوم",
                                    f"No bell schedule for grade {grade.name_en or grade.name_ar} on this day",
                                    extra={"grade_id": grade.id}))
                continue
            needed = range(period_no, period_no + duration)
            missing = [p for p in needed if p not in periods]
            if missing:
                out.append(Conflict("period_not_in_schedule",
                                    f"لا توجد الحصة {missing[0]} في توقيت الصف {grade.name_ar} لهذا اليوم",
                                    f"Period {missing[0]} does not exist for grade {grade.name_en or grade.name_ar} on this day",
                                    extra={"grade_id": grade.id, "period_no": missing[0]}))
                continue
            first = periods[period_no]
            if any(periods[p] != first + i for i, p in enumerate(needed)):
                out.append(Conflict("crosses_break", "لا يجوز أن تتخلّل الاستراحةُ الحصةَ المزدوجة",
                                    "A double lesson cannot span a break", extra={"grade_id": grade.id}))
        return out

    def _check_meeting_bells(self, lesson, weekday_id, period_no, duration):
        periods = self.bells.meeting_periods(lesson, weekday_id)
        if not periods:
            return [Conflict("no_bell_schedule", "لا يوجد توقيت حصص لهذا اليوم", "No bell times on this day")]
        needed = range(period_no, period_no + duration)
        missing = [p for p in needed if p not in periods]
        if missing:
            return [Conflict("period_not_in_schedule", f"لا توجد الحصة {missing[0]} في توقيت الاجتماع لهذا اليوم",
                             f"Period {missing[0]} does not exist in the meeting's timing on this day",
                             extra={"period_no": missing[0]})]
        if lesson.bell_schedule_id and any(periods[p] != periods[period_no] + i for i, p in enumerate(needed)):
            return [Conflict("crosses_break", "لا يجوز أن تتخلّل الاستراحةُ الاجتماعَ الممتد لأكثر من حصة",
                             "A meeting cannot span a break")]
        return []

    def _check_availability(self, lesson, teacher_ids, targets, room_id, weekday_id, period_no, duration):
        entities = [("teacher", t) for t in teacher_ids] + [("section", t.section_id) for t in targets]
        entities.append(("subject", lesson.subject_id))
        if room_id:
            entities.append(("room", room_id))
        rows = db.session.scalars(
            select(Availability).where(
                Availability.timetable_id == self.tt.id,
                Availability.weekday_id == weekday_id,
                Availability.status == "unavailable",
                Availability.period_no >= period_no,
                Availability.period_no < period_no + duration,
                or_(*[and_(Availability.entity_type == k, Availability.entity_id == i) for k, i in entities]),
            )
        ).all()
        out = []
        for r in rows:
            name = self._entity_name(r.entity_type, r.entity_id)
            out.append(Conflict("unavailable", f"{name}: {self._unavailable_word(r.entity_type, r.entity_id)} في الحصة {r.period_no}",
                                f"{name}: unavailable in period {r.period_no}",
                                extra={"entity_type": r.entity_type, "entity_id": r.entity_id, "period_no": r.period_no}))
        return out

    def _occ_query(self, rtype, ids, weekday_id, period_no, duration, week_no, exclude):
        weeks = self.tt.weeks_range(week_no)
        q = select(Occupancy).where(
            Occupancy.timetable_id == self.tt.id,
            Occupancy.weekday_id == weekday_id,
            Occupancy.resource_type == rtype,
            Occupancy.resource_id.in_(ids),
            Occupancy.periods.overlaps(Range(period_no, period_no + duration)),
            Occupancy.weeks.overlaps(Range(*weeks)),
        )
        if exclude:
            q = q.where(Occupancy.card_id.notin_(list(exclude)))
        return db.session.scalars(q).all()

    def _check_busy(self, rtype, ids, weekday_id, period_no, duration, week_no, exclude):
        if not ids:
            return []
        out = []
        for occ in self._occ_query(rtype, ids, weekday_id, period_no, duration, week_no, exclude):
            t = db.session.get(Teacher, occ.resource_id)
            desc = self._card_desc(occ.card_id)
            out.append(Conflict("teacher_busy", f"{teacher_title(t.gender)} {t.name_ar} {g(t.gender, 'مشغول', 'مشغولة')} في هذه الحصة ({desc})",
                                f"Teacher {t.name_en or t.name_ar} is busy at this time ({desc})",
                                other_card_id=occ.card_id, extra={"teacher_id": t.id}))
        return out

    def _check_room(self, lesson, room_id, weekday_id, period_no, duration, week_no, exclude):
        if not room_id:
            return []
        room = db.session.get(Room, room_id)
        if room is None:
            return [Conflict("unknown_room", "قاعة غير معروفة", "Unknown room")]
        out = []
        subject = db.session.get(Subject, lesson.subject_id)
        if subject.requires_room_type and room.room_type != subject.requires_room_type:
            out.append(Conflict("room_type_mismatch",
                                f"يتطلّب مبحث {subject.name_ar} قاعةً من نوع {subject.requires_room_type}",
                                f"{subject.name_en or subject.name_ar} requires a {subject.requires_room_type} room"))
        if subject.rooms and room not in subject.rooms:
            out.append(Conflict("room_not_allowed", f"القاعة {room.name_ar} غير مخصّصة لمبحث {subject.name_ar}",
                                f"Room {room.name_en or room.name_ar} is not allowed for this subject"))
        if not room.is_shared:
            for occ in self._occ_query("room", [room_id], weekday_id, period_no, duration, week_no, exclude):
                out.append(Conflict("room_busy", f"القاعة {room.name_ar} محجوزة في هذه الحصة ({self._card_desc(occ.card_id)})",
                                    f"Room {room.name_en or room.name_ar} is taken at this time",
                                    other_card_id=occ.card_id, extra={"room_id": room.id}))
        return out

    def _check_classes(self, targets, weekday_id, period_no, duration, week_no, exclude):
        section_ids = {t.section_id for t in targets}
        q = (
            select(Card, LessonTarget)
            .join(Lesson, Lesson.id == Card.lesson_id)
            .join(LessonTarget, LessonTarget.lesson_id == Lesson.id)
            .where(
                Card.timetable_id == self.tt.id,
                Card.weekday_id == weekday_id,
                Card.period_no < period_no + duration,
                Card.period_no + Card.duration > period_no,
                LessonTarget.section_id.in_(section_ids),
            )
        )
        if week_no is not None:  # a card for "all weeks" overlaps every week
            q = q.where(or_(Card.week_no.is_(None), Card.week_no == week_no))
        if exclude:
            q = q.where(Card.id.notin_(list(exclude)))
        mine: dict[uuid.UUID, list[StudentGroup | None]] = {}
        for t in targets:
            mine.setdefault(t.section_id, []).append(db.session.get(StudentGroup, t.group_id) if t.group_id else None)
        out, seen = [], set()
        for card, tgt in db.session.execute(q).all():
            other_group = db.session.get(StudentGroup, tgt.group_id) if tgt.group_id else None
            if all(groups_compatible(g, other_group) for g in mine[tgt.section_id]):
                continue
            key = (card.id, tgt.section_id)
            if key in seen:
                continue
            seen.add(key)
            sec = db.session.get(Section, tgt.section_id)
            label = _section_label(sec)
            if other_group is not None:
                label += f" ({other_group.name_ar})"
            out.append(Conflict("class_busy", f"لدى الشعبة {label} حصة أخرى في هذا الوقت ({self._card_desc(card.id)})",
                                f"Section {label} already has a lesson at this time",
                                other_card_id=card.id, extra={"section_id": sec.id}))
        return out

    # -- helpers ------------------------------------------------------------
    def _card_desc(self, card_id) -> str:
        card = db.session.get(Card, card_id)
        lesson = db.session.get(Lesson, card.lesson_id)
        return lesson.label

    def _entity_name(self, kind, id_) -> str:
        model = {"teacher": Teacher, "section": Section, "subject": Subject, "room": Room}[kind]
        obj = db.session.get(model, id_)
        if obj is None:
            return kind
        if isinstance(obj, Section):
            return "الشعبة " + _section_label(obj)
        if isinstance(obj, Teacher):
            return f"{teacher_title(obj.gender)} {obj.name_ar}"
        prefix = {"subject": "المبحث ", "room": "القاعة "}[kind]
        return prefix + obj.name_ar

    def _unavailable_word(self, kind, id_) -> str:
        """Agreement: المعلم غير متاح / المعلمة غير متاحة / الشعبة غير متاحة / القاعة غير متاحة."""
        if kind == "teacher":
            t = db.session.get(Teacher, id_)
            return g(t.gender if t else None, "غير متاح", "غير متاحة")
        return "غير متاح" if kind == "subject" else "غير متاحة"


# ---------------------------------------------------------------------------
# Occupancy maintenance
# ---------------------------------------------------------------------------
def rebuild_occupancy(card: Card, lesson: Lesson | None = None, tt: Timetable | None = None) -> None:
    db.session.execute(delete(Occupancy).where(Occupancy.card_id == card.id))
    if not card.is_placed or card.deleted_at is not None:
        return
    lesson = lesson or db.session.get(Lesson, card.lesson_id)
    tt = tt or db.session.get(Timetable, card.timetable_id)
    periods = Range(card.period_no, card.period_no + card.duration)
    weeks = Range(*tt.weeks_range(card.week_no))
    rows = [("teacher", tid) for tid in lesson.teacher_ids]
    if card.room_id:
        room = db.session.get(Room, card.room_id)
        if room and not room.is_shared:
            rows.append(("room", room.id))
    for rtype, rid in rows:
        db.session.add(Occupancy(timetable_id=tt.id, card_id=card.id, resource_type=rtype, resource_id=rid,
                                 weekday_id=card.weekday_id, periods=periods, weeks=weeks))


def grid_periods(checker: PlacementChecker, lesson: Lesson, weekday_id) -> list[int]:
    """Union of lesson period numbers across the lesson's grades for one day."""
    nums: set[int] = set()
    if lesson.is_meeting:
        return sorted((checker.bells.meeting_periods(lesson, weekday_id) or {}).keys())
    for t in lesson.targets:
        sec = db.session.get(Section, t.section_id)
        p = checker.bells.periods(sec.grade, weekday_id)
        if p:
            nums.update(p.keys())
    return sorted(nums)
