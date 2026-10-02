"""Lessons, cards, timetable copy/publish, validation and bulk bell assignment."""
from __future__ import annotations

import uuid
from collections import Counter

from flask import jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import delete, select

from app.api import api_bp
from app.api.crud import check_version
from app.api.idempotency import write_endpoint
from app.api.serialize import parse_uuid, require_int
from app.auth.permissions import require_admin, require_write
from app.arabic import count
from app.errors import ApiError
from app.extensions import db
from app.models import (
    Availability,
    BellAssignment,
    BellSchedule,
    Card,
    ConstraintRule,
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
from app.models.base import new_id, utcnow
from app.rules.placement import PlacementChecker, Target, grid_periods, rebuild_occupancy
from app.rules.validate import validate_timetable


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _json() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("validation", 400, details={"reason": "json object required"})
    return data


def _get(model, id_, field="id"):
    obj = db.session.get(model, parse_uuid(id_, field))
    if obj is None:
        raise ApiError("not_found", 404, details={"field": field})
    return obj


def _ref(model, id_, field):
    obj = db.session.get(model, parse_uuid(id_, field))
    if obj is None:
        raise ApiError("validation", 400, details={"field": field, "reason": "unknown_reference", "id": str(id_)})
    return obj


def editable_timetable(tt_id) -> Timetable:
    tt = db.session.get(Timetable, tt_id)
    if tt is None:
        raise ApiError("validation", 400, details={"field": "timetable_id", "reason": "unknown_reference"})
    if tt.status == "archived":
        raise ApiError("timetable_readonly", 409)
    return tt


def card_durations(periods_per_week: int, duration: int) -> list[int]:
    """5 periods as doubles → [2, 2, 1] (two doubles and a single, like ASC)."""
    full, rest = divmod(periods_per_week, duration)
    return [duration] * full + ([rest] if rest else [])


def serialize_card(c: Card) -> dict:
    return c.to_dict()


def serialize_lesson(l: Lesson, with_cards: bool = True) -> dict:
    out = l.to_dict()
    out["teachers"] = [{"teacher_id": str(t.teacher_id), "role": t.role} for t in l.teachers]
    out["targets"] = [{"section_id": str(t.section_id), "group_id": str(t.group_id) if t.group_id else None}
                      for t in l.targets]
    if with_cards:
        out["cards"] = [serialize_card(c) for c in l.cards if c.deleted_at is None]
    return out


def _parse_teachers(data, subject: Subject) -> list[tuple[uuid.UUID, str]]:
    raw = data.get("teachers", [])
    if not isinstance(raw, list):
        raise ApiError("validation", 400, details={"field": "teachers", "reason": "must be a list"})
    out, seen = [], set()
    for i, item in enumerate(raw):
        if isinstance(item, str):
            item = {"teacher_id": item}
        t = _ref(Teacher, item.get("teacher_id"), f"teachers[{i}].teacher_id")
        role = item.get("role", "main")
        if role not in ("main", "assistant"):
            raise ApiError("validation", 400, details={"field": f"teachers[{i}].role"})
        if t.id in seen:
            raise ApiError("validation", 400, details={"field": "teachers", "reason": "duplicate teacher"})
        seen.add(t.id)
        out.append((t.id, role))
    if len(out) > subject.max_teachers_per_block:
        raise ApiError("validation", 400, details={
            "field": "teachers", "reason": "too_many_teachers", "max": subject.max_teachers_per_block,
            "message": f"يسمح مبحث {subject.name_ar} بـ{count(subject.max_teachers_per_block, 'teacher')} في البطاقة الواحدة؛ "
                       f"ولحصص الأولاد والبنات استخدم مجموعتين من التقسيم نفسه",
        })
    return out


def _parse_targets(data) -> list[Target]:
    raw = data.get("targets")
    if not isinstance(raw, list) or not raw:
        raise ApiError("validation", 400, details={"field": "targets", "reason": "at least one section required"})
    out, seen = [], set()
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ApiError("validation", 400, details={"field": f"targets[{i}]"})
        sec = _ref(Section, item.get("section_id"), f"targets[{i}].section_id")
        gid = None
        if item.get("group_id"):
            grp = _ref(StudentGroup, item["group_id"], f"targets[{i}].group_id")
            if grp.division.section_id != sec.id:
                raise ApiError("validation", 400, details={"field": f"targets[{i}].group_id",
                                                             "reason": "group does not belong to this section"})
            gid = grp.id
        key = (sec.id, gid)
        if key in seen:
            raise ApiError("validation", 400, details={"field": "targets", "reason": "duplicate target"})
        seen.add(key)
        out.append(Target(sec.id, gid))
    return out


MEETING_SUBJECT = "اجتماع"


def meeting_subject() -> Subject:
    """Meetings are lessons of one built-in subject «اجتماع» (its colour is the meetings' colour in the grid)."""
    s = db.session.scalars(select(Subject).where(Subject.name_ar == MEETING_SUBJECT)).first()
    if s is None:
        s = Subject(name_ar=MEETING_SUBJECT, name_en="Meeting", short_ar="اجتماع", short_en="Meeting",
                    color="#cbd5e1", max_teachers_per_block=200)
        db.session.add(s)
        db.session.flush()
    elif s.max_teachers_per_block < 200:
        s.max_teachers_per_block = 200
    return s


def _meeting_fields(data, lesson: Lesson | None) -> dict:
    """Validated meeting-only fields (title, load flag, timing template)."""
    from app.models import BellSchedule
    out = {}
    if lesson is None or "title" in data:
        title = (data.get("title") or "").strip()
        if not title:
            raise ApiError("validation", 400, details={"field": "title", "reason": "required",
                                                        "message": "اكتب عنوان الاجتماع، مثل: اجتماع قسم الحاسوب"})
        if len(title) > 120:
            raise ApiError("validation", 400, details={"field": "title", "reason": "max length 120"})
        out["title"] = title
    if "counts_load" in data:
        out["counts_load"] = bool(data["counts_load"])
    elif lesson is None:
        out["counts_load"] = False
    if "bell_schedule_id" in data:
        out["bell_schedule_id"] = _ref(BellSchedule, data["bell_schedule_id"], "bell_schedule_id").id if data["bell_schedule_id"] else None
    return out


def _conflict_error(conflicts) -> ApiError:
    first = conflicts[0]
    return ApiError("placement_conflict", 409, details=[c.as_dict() for c in conflicts],
                    message=first.message, message_en=first.message_en)


# ---------------------------------------------------------------------------
# Lessons
# ---------------------------------------------------------------------------
@api_bp.get("/timetables/<tt_id>/lessons")
@login_required
def list_lessons(tt_id):
    tt = _get(Timetable, tt_id)
    lessons = db.session.scalars(select(Lesson).where(Lesson.timetable_id == tt.id).order_by(Lesson.created_at)).all()
    return jsonify(items=[serialize_lesson(l) for l in lessons])


@api_bp.get("/lessons/<id_>")
@login_required
def get_lesson(id_):
    return jsonify(serialize_lesson(_get(Lesson, id_)))


@api_bp.post("/lessons")
@write_endpoint
def create_lesson():
    data = _json()
    tt = editable_timetable(parse_uuid(data.get("timetable_id"), "timetable_id"))
    kind = data.get("kind") or "lesson"
    if kind not in ("lesson", "meeting"):
        raise ApiError("validation", 400, details={"field": "kind", "reason": "lesson or meeting"})
    meeting = kind == "meeting"
    if meeting:
        require_admin(current_user)
        extra = _meeting_fields(data, None)
        subject = meeting_subject()
    else:
        extra = {"counts_load": True}
        subject = _ref(Subject, data.get("subject_id"), "subject_id")
    ppw = require_int(data, "periods_per_week", 1)
    duration = data.get("duration", 1)
    if isinstance(duration, bool) or not isinstance(duration, int) or not 1 <= duration <= 4:
        raise ApiError("validation", 400, details={"field": "duration", "reason": "1..4"})
    week_no = _week_no(data, tt)
    teachers = _parse_teachers(data, subject)
    if meeting and not teachers:
        raise ApiError("validation", 400, details={"field": "teachers", "reason": "required",
                                                    "message": "اختر أعضاء الاجتماع (معلماً واحداً على الأقل)"})
    targets = [] if meeting else _parse_targets(data)
    lesson = Lesson(kind=kind, **extra,
        id=parse_uuid(data["id"]) if data.get("id") else new_id(),
        timetable_id=tt.id, subject_id=subject.id, periods_per_week=ppw, duration=duration, week_no=week_no,
        preferred_room_id=_ref(Room, data["preferred_room_id"], "preferred_room_id").id if data.get("preferred_room_id") else None,
        notes=data.get("notes"),
    )
    lesson.teachers = [LessonTeacher(teacher_id=tid, role=role) for tid, role in teachers]
    lesson.targets = [LessonTarget(section_id=t.section_id, group_id=t.group_id) for t in targets]
    if not meeting:
        require_write(current_user, lesson)
    db.session.add(lesson)
    for d in card_durations(ppw, duration):
        db.session.add(Card(timetable_id=tt.id, lesson=lesson, duration=d, week_no=week_no))
    db.session.flush()
    db.session.refresh(lesson)
    return serialize_lesson(lesson), 201


def _week_no(data, tt: Timetable):
    w = data.get("week_no")
    if w is None:
        return None
    if isinstance(w, bool) or not isinstance(w, int) or not 1 <= w <= tt.cycle_weeks:
        raise ApiError("validation", 400, details={"field": "week_no", "reason": f"1..{tt.cycle_weeks}"})
    return w


@api_bp.patch("/lessons/<id_>")
@write_endpoint
def update_lesson(id_):
    data = _json()
    lesson = _get(Lesson, id_)
    tt = editable_timetable(lesson.timetable_id)
    meeting = lesson.is_meeting
    if meeting:
        require_admin(current_user)
        if data.get("kind") not in (None, "meeting"):
            raise ApiError("validation", 400, details={"field": "kind", "reason": "cannot change"})
        data.pop("subject_id", None)
        data.pop("targets", None)
    else:
        require_write(current_user, lesson)
        if data.get("kind") not in (None, "lesson"):
            raise ApiError("validation", 400, details={"field": "kind", "reason": "cannot change"})
    check_version(lesson, data.get("version"))
    extra = _meeting_fields(data, lesson) if meeting else {}

    subject = _ref(Subject, data["subject_id"], "subject_id") if "subject_id" in data else lesson.subject
    teachers = _parse_teachers(data, subject) if "teachers" in data else [(t.teacher_id, t.role) for t in lesson.teachers]
    if "teachers" not in data and len(teachers) > subject.max_teachers_per_block:
        _parse_teachers({"teachers": [{"teacher_id": str(t)} for t, _ in teachers]}, subject)
    targets = _parse_targets(data) if "targets" in data else [Target(t.section_id, t.group_id) for t in lesson.targets]
    ppw = require_int(data, "periods_per_week", 1) if "periods_per_week" in data else lesson.periods_per_week
    duration = data.get("duration", lesson.duration)
    if isinstance(duration, bool) or not isinstance(duration, int) or not 1 <= duration <= 4:
        raise ApiError("validation", 400, details={"field": "duration", "reason": "1..4"})
    week_no = _week_no(data, tt) if "week_no" in data else lesson.week_no

    live_cards = [c for c in lesson.cards if c.deleted_at is None]
    own_ids = {c.id for c in live_cards}

    if meeting and not teachers:
        raise ApiError("validation", 400, details={"field": "teachers", "reason": "required",
                                                    "message": "اختر أعضاء الاجتماع (معلماً واحداً على الأقل)"})
    for k, v in extra.items():
        setattr(lesson, k, v)

    # Re-check placed cards against the new teachers/targets/week before changing anything.
    if "teachers" in data or "targets" in data or "week_no" in data or "bell_schedule_id" in data:
        checker = PlacementChecker(tt)
        teacher_ids = [t for t, _ in teachers]
        conflicts = []
        for c in live_cards:
            if c.is_placed:
                conflicts += checker.check(lesson, c.weekday_id, c.period_no, c.duration, week_no, c.room_id,
                                           teacher_ids=teacher_ids, targets=targets, exclude_card_ids=own_ids)
        if conflicts:
            raise _conflict_error(conflicts)

    # Apply
    lesson.subject_id = subject.id
    lesson.periods_per_week = ppw
    lesson.week_no = week_no
    if "notes" in data:
        lesson.notes = data["notes"]
    if "preferred_room_id" in data:
        lesson.preferred_room_id = _ref(Room, data["preferred_room_id"], "preferred_room_id").id if data["preferred_room_id"] else None
    if "teachers" in data:
        lesson.teachers.clear()
        db.session.flush()
        lesson.teachers = [LessonTeacher(teacher_id=tid, role=role) for tid, role in teachers]
    if "targets" in data:
        lesson.targets.clear()
        db.session.flush()
        lesson.targets = [LessonTarget(section_id=t.section_id, group_id=t.group_id) for t in targets]
    if not meeting:
        require_write(current_user, lesson)  # cannot retarget into a stage you don't own

    reset = duration != lesson.duration
    lesson.duration = duration
    removed = _sync_cards(lesson, tt, live_cards, card_durations(ppw, duration), reset)
    for c in live_cards:
        c.week_no = week_no
    db.session.flush()
    for c in lesson.cards:
        if c.deleted_at is None:
            rebuild_occupancy(c, lesson, tt)
    lesson.updated_at = utcnow()  # force a version/change_seq bump even if only children changed
    db.session.flush()
    db.session.refresh(lesson)
    out = serialize_lesson(lesson)
    out["cards_reset"] = reset
    out["cards_removed"] = removed
    return out, 200


def _sync_cards(lesson: Lesson, tt: Timetable, live: list[Card], desired: list[int], reset: bool) -> int:
    """Make the lesson's cards match `desired` durations, keeping placed/locked cards when possible."""
    if reset:
        for c in live:
            c.soft_delete()
            db.session.execute(delete(Occupancy).where(Occupancy.card_id == c.id))
        for d in desired:
            db.session.add(Card(timetable_id=tt.id, lesson=lesson, duration=d, week_no=lesson.week_no))
        return len(live)
    need = Counter(desired)
    keep, extra = [], []
    # Prefer keeping locked, then placed, then unplaced cards.
    for c in sorted(live, key=lambda c: (not c.is_locked, not c.is_placed)):
        if need[c.duration] > 0:
            need[c.duration] -= 1
            keep.append(c)
        else:
            extra.append(c)
    for c in extra:
        c.soft_delete()
        db.session.execute(delete(Occupancy).where(Occupancy.card_id == c.id))
    for d, n in need.items():
        for _ in range(n):
            db.session.add(Card(timetable_id=tt.id, lesson=lesson, duration=d, week_no=lesson.week_no))
    return len(extra)


@api_bp.delete("/lessons/<id_>")
@write_endpoint
def delete_lesson(id_):
    lesson = _get(Lesson, id_)
    editable_timetable(lesson.timetable_id)
    require_write(current_user, lesson)
    try:
        version = int(request.args.get("version", ""))
    except ValueError:
        version = None
    check_version(lesson, version)
    for c in lesson.cards:
        if c.deleted_at is None:
            c.soft_delete()
            db.session.execute(delete(Occupancy).where(Occupancy.card_id == c.id))
    lesson.soft_delete()
    db.session.flush()
    return {"id": str(lesson.id), "deleted": True}, 200


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------
@api_bp.get("/timetables/<tt_id>/cards")
@login_required
def list_cards(tt_id):
    tt = _get(Timetable, tt_id)
    cards = db.session.scalars(select(Card).where(Card.timetable_id == tt.id)).all()
    return jsonify(items=[serialize_card(c) for c in cards])


def _placement_from(data: dict, card: Card):
    wd = data.get("weekday_id", card.weekday_id)
    period = data.get("period_no", card.period_no)
    if (wd is None) != (period is None):
        raise ApiError("validation", 400, details={"reason": "weekday_id and period_no must both be set or both null"})
    if wd is not None:
        wd = parse_uuid(wd, "weekday_id")
        if isinstance(period, bool) or not isinstance(period, int) or period < 1:
            raise ApiError("validation", 400, details={"field": "period_no"})
    room = data.get("room_id", card.room_id)
    room = parse_uuid(room, "room_id") if room else None
    return wd, period, room


@api_bp.post("/cards/<id_>/check")
@login_required
def check_card(id_):
    """Dry run used by drag & drop before the drop is committed."""
    card = _get(Card, id_)
    data = request.get_json(silent=True) or {}
    wd, period, room = _placement_from(data, card)
    if wd is None:
        return jsonify(ok=True, conflicts=[])
    tt = db.session.get(Timetable, card.timetable_id)
    conflicts = PlacementChecker(tt).check(card.lesson, wd, period, card.duration, card.week_no, room,
                                           exclude_card_ids={card.id})
    return jsonify(ok=not conflicts, conflicts=[c.as_dict() for c in conflicts])


@api_bp.get("/cards/<id_>/allowed-slots")
@login_required
def allowed_slots(id_):
    """Every (day, period) cell for this card, marked allowed or with the reasons it is not."""
    card = _get(Card, id_)
    tt = db.session.get(Timetable, card.timetable_id)
    checker = PlacementChecker(tt)
    days = db.session.scalars(select(Weekday).where(Weekday.is_school_day.is_(True)).order_by(Weekday.sort_order)).all()
    out = []
    for wd in days:
        cells = []
        for p in grid_periods(checker, card.lesson, wd.id):
            conflicts = checker.check(card.lesson, wd.id, p, card.duration, card.week_no, card.room_id,
                                      exclude_card_ids={card.id})
            cells.append({"period_no": p, "ok": not conflicts,
                          "codes": sorted({c.code for c in conflicts}),
                          "messages": [c.message for c in conflicts]})
        out.append({"weekday_id": str(wd.id), "name_ar": wd.name_ar, "periods": cells})
    return jsonify(card_id=str(card.id), days=out)


@api_bp.patch("/cards/<id_>")
@write_endpoint
def update_card(id_):
    data = _json()
    card = _get(Card, id_)
    tt = editable_timetable(card.timetable_id)
    require_write(current_user, card)
    check_version(card, data.get("version"))
    wd, period, room = _placement_from(data, card)
    moving = (wd, period) != (card.weekday_id, card.period_no) or room != card.room_id
    unlock = data.get("is_locked") is False
    if card.is_locked and moving and not unlock:
        raise ApiError("validation", 409, details={"reason": "card_locked"},
                       message="الحصة مقفلة؛ ألغِ قفلها أولاً", message_en="Card is locked; unlock it first")
    if wd is not None and room is None and card.room_id is None and card.lesson.preferred_room_id:
        room = card.lesson.preferred_room_id
    if wd is not None and moving:
        conflicts = PlacementChecker(tt).check(card.lesson, wd, period, card.duration, card.week_no, room,
                                               exclude_card_ids={card.id})
        if conflicts:
            raise _conflict_error(conflicts)
    card.weekday_id, card.period_no, card.room_id = wd, period, room
    if "is_locked" in data:
        if not isinstance(data["is_locked"], bool):
            raise ApiError("validation", 400, details={"field": "is_locked"})
        card.is_locked = data["is_locked"]
    db.session.flush()
    rebuild_occupancy(card, card.lesson, tt)
    db.session.flush()  # the EXCLUDE constraint fires here if two users raced for the same slot
    db.session.refresh(card)
    return serialize_card(card), 200


# ---------------------------------------------------------------------------
# Timetable lifecycle
# ---------------------------------------------------------------------------
def copy_timetable_data(src: Timetable, name: str, term_id=None, new_id_=None) -> tuple[Timetable, dict]:
    """A draft copy of a timetable (lessons, cards, time-off, rules). Returns (copy, {old card id: new card})."""
    new = Timetable(id=new_id_ or new_id(), term_id=term_id or src.term_id, name=name, status="draft",
                    cycle_weeks=src.cycle_weeks, based_on_id=src.id)
    db.session.add(new)
    db.session.flush()
    card_map = {}
    for l in db.session.scalars(select(Lesson).where(Lesson.timetable_id == src.id)):
        nl = Lesson(timetable_id=new.id, subject_id=l.subject_id, periods_per_week=l.periods_per_week,
                    duration=l.duration, week_no=l.week_no, preferred_room_id=l.preferred_room_id, notes=l.notes,
                    kind=l.kind, title=l.title, counts_load=l.counts_load, bell_schedule_id=l.bell_schedule_id)
        nl.teachers = [LessonTeacher(teacher_id=t.teacher_id, role=t.role) for t in l.teachers]
        nl.targets = [LessonTarget(section_id=t.section_id, group_id=t.group_id) for t in l.targets]
        db.session.add(nl)
        for c in l.cards:
            if c.deleted_at is None:
                nc = Card(timetable_id=new.id, lesson=nl, weekday_id=c.weekday_id, period_no=c.period_no,
                          duration=c.duration, week_no=c.week_no, room_id=c.room_id, is_locked=c.is_locked)
                db.session.add(nc)
                card_map[c.id] = nc
    for a in db.session.scalars(select(Availability).where(Availability.timetable_id == src.id)):
        db.session.add(Availability(timetable_id=new.id, entity_type=a.entity_type, entity_id=a.entity_id,
                                    weekday_id=a.weekday_id, period_no=a.period_no, status=a.status))
    for r in db.session.scalars(select(ConstraintRule).where(ConstraintRule.timetable_id == src.id)):
        db.session.add(ConstraintRule(timetable_id=new.id, kind=r.kind, scope_type=r.scope_type,
                                      scope_ids=list(r.scope_ids), params=dict(r.params), strength=r.strength,
                                      weight=r.weight, is_active=r.is_active))
    db.session.flush()
    for nc in card_map.values():
        rebuild_occupancy(nc, nc.lesson, new)
    db.session.flush()
    return new, card_map


@api_bp.post("/timetables/<id_>/copy")
@write_endpoint
def copy_timetable(id_):
    require_admin(current_user)
    src = _get(Timetable, id_)
    data = request.get_json(silent=True) or {}
    term_id = _ref(Term, data["term_id"], "term_id").id if data.get("term_id") else None
    new, card_map = copy_timetable_data(src, data.get("name") or f"{src.name} (نسخة)", term_id,
                                        parse_uuid(data["id"]) if data.get("id") else None)
    db.session.refresh(new)
    return {**new.to_dict(), "lessons_copied": len({c.lesson_id for c in card_map.values()}),
            "cards_copied": len(card_map)}, 201


@api_bp.post("/timetables/<id_>/publish")
@write_endpoint
def publish_timetable(id_):
    require_admin(current_user)
    tt = _get(Timetable, id_)
    data = request.get_json(silent=True) or {}
    check_version(tt, data.get("version"))
    report = validate_timetable(tt)
    if report["errors"] and not data.get("force"):
        raise ApiError("validation", 409, details={"reason": "timetable_has_errors", "summary": report["summary"],
                                                     "errors": report["errors"][:50]},
                       message="تعذّر النشر: في الجدول أخطاء. أصلحها أولاً، أو انشره متجاوزاً إياها",
                       message_en="Cannot publish: the timetable has errors. Fix them or publish with force")
    for other in db.session.scalars(select(Timetable).where(
            Timetable.term_id == tt.term_id, Timetable.status == "published", Timetable.id != tt.id)):
        other.status = "archived"
    db.session.flush()
    tt.status = "published"
    tt.published_at = utcnow()
    tt.published_by = current_user.id
    db.session.flush()
    db.session.refresh(tt)
    return {**tt.to_dict(), "validation": report["summary"]}, 200


@api_bp.get("/timetables/<id_>/validate")
@login_required
def validate(id_):
    return jsonify(validate_timetable(_get(Timetable, id_)))


# ---------------------------------------------------------------------------
# Bell assignments in bulk ("apply this day's timing to these days and grades")
# ---------------------------------------------------------------------------
@api_bp.post("/bell-assignments/bulk")
@write_endpoint
def bulk_bell_assign():
    data = _json()
    term = _ref(Term, data.get("term_id"), "term_id")
    stage = _ref(Stage, data.get("stage_id"), "stage_id")
    schedule = _ref(BellSchedule, data.get("bell_schedule_id"), "bell_schedule_id")
    weekdays = data.get("weekday_ids")
    if not isinstance(weekdays, list) or not weekdays:
        raise ApiError("validation", 400, details={"field": "weekday_ids", "reason": "non-empty list"})
    weekday_objs = [_ref(Weekday, w, "weekday_ids") for w in weekdays]
    grade_ids = data.get("grade_ids")  # null/[] = the whole stage
    grades: list[Grade | None] = [None]
    if grade_ids:
        grades = [_ref(Grade, g, "grade_ids") for g in grade_ids]
        if any(g.stage_id != stage.id for g in grades):
            raise ApiError("validation", 400, details={"field": "grade_ids", "reason": "grade not in stage"})
    probe = BellAssignment(stage_id=stage.id)
    require_write(current_user, probe)
    created = updated = 0
    for wd in weekday_objs:
        for g in grades:
            gid = g.id if g else None
            q = select(BellAssignment).where(
                BellAssignment.term_id == term.id, BellAssignment.weekday_id == wd.id,
                BellAssignment.stage_id == stage.id,
                BellAssignment.grade_id == gid if gid else BellAssignment.grade_id.is_(None))
            row = db.session.scalars(q).first()
            if row:
                if row.bell_schedule_id != schedule.id:
                    row.bell_schedule_id = schedule.id
                    updated += 1
            else:
                db.session.add(BellAssignment(term_id=term.id, weekday_id=wd.id, stage_id=stage.id,
                                              grade_id=gid, bell_schedule_id=schedule.id))
                created += 1
    db.session.flush()
    return {"created": created, "updated": updated}, 200
