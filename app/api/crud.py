"""Generic REST resources for the reference data (ERD §2–§5, §7, §9).

GET    /api/<res>                 list  (filter by any column: ?grade_id=…)
GET    /api/<res>/<id>
POST   /api/<res>                 create (client may supply "id" — UUIDv7 from the browser)
PATCH  /api/<res>/<id>            update; body must carry the current "version"
DELETE /api/<res>/<id>?version=N  soft delete; refused while live records depend on it
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import time
from typing import Callable

from flask import jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import func, select

from app.api import api_bp
from app.api.idempotency import write_endpoint
from app.api.serialize import coerce, parse_uuid, parse_uuid_list
from app.auth.permissions import require_admin, require_write
from app.errors import ApiError
from app.extensions import db
from app.models import (
    AcademicYear,
    AppUser,
    Availability,
    BellAssignment,
    BellSchedule,
    BellSlot,
    Building,
    ConstraintRule,
    Division,
    DutyAssignment,
    ExamSession,
    Grade,
    Lesson,
    Room,
    School,
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
from app.models.base import SYSTEM_COLUMNS, SyncMixin, jsonable
from app.models.users import ROLES


@dataclass
class Resource:
    model: type
    read_only_fields: frozenset[str] = frozenset()
    hidden_fields: frozenset[str] = frozenset()
    create_only_fields: frozenset[str] = frozenset()
    write_extra: Callable | None = None  # (obj, data, creating) -> None
    read_extra: Callable | None = None  # (obj) -> dict
    admin_read_only: bool = False
    before_delete: Callable | None = None
    after_write: Callable | None = None
    fields: list = field(default_factory=list)

    def __post_init__(self):
        cols = self.model.__table__.columns
        self.fields = [
            c for c in cols
            if c.name not in SYSTEM_COLUMNS and c.name != "id" and c.name not in self.read_only_fields
            and c.name not in self.hidden_fields
        ]


def serialize(res: Resource, obj) -> dict:
    out = obj.to_dict(exclude=res.hidden_fields)
    if res.read_extra:
        out.update(res.read_extra(obj))
    return out


# ---------------------------------------------------------------------------
# Resource-specific hooks
# ---------------------------------------------------------------------------
def _teacher_write(obj: Teacher, data: dict, creating: bool):
    if "stage_ids" in data:
        ids = parse_uuid_list(data["stage_ids"], "stage_ids")
        obj.stages = [_must_get(Stage, i, "stage_ids") for i in ids]
    if "subject_ids" in data:
        ids = parse_uuid_list(data["subject_ids"], "subject_ids")
        obj.subjects = [_must_get(Subject, i, "subject_ids") for i in ids]


def _teacher_read(obj: Teacher) -> dict:
    return {
        "stage_ids": sorted(str(s.id) for s in obj.stages),
        "subject_ids": sorted(str(s.id) for s in obj.subjects),
    }


def _subject_write(obj: Subject, data: dict, creating: bool):
    if "room_ids" in data:
        ids = parse_uuid_list(data["room_ids"], "room_ids")
        obj.rooms = [_must_get(Room, i, "room_ids") for i in ids]


def _subject_read(obj: Subject) -> dict:
    return {"room_ids": sorted(str(r.id) for r in obj.rooms)}


SLOT_FIELDS = ("slot_no", "kind", "period_no", "label_ar", "label_en", "starts_at", "ends_at")


def _bell_write(obj: BellSchedule, data: dict, creating: bool):
    if "slots" not in data:
        return
    raw = data["slots"]
    if not isinstance(raw, list):
        raise ApiError("validation", 400, details={"field": "slots", "reason": "must be a list"})
    cols = BellSlot.__table__.columns
    slots = []
    for i, s in enumerate(raw):
        if not isinstance(s, dict):
            raise ApiError("validation", 400, details={"field": f"slots[{i}]"})
        vals = {k: coerce(cols[k], f"slots[{i}].{k}", s.get(k)) for k in SLOT_FIELDS}
        slots.append(vals)
    slots.sort(key=lambda s: s["slot_no"])
    # Times must be strictly increasing and non-overlapping; periods unique.
    prev_end: time | None = None
    periods = set()
    for s in slots:
        if s["ends_at"] <= s["starts_at"] or (prev_end and s["starts_at"] < prev_end):
            raise ApiError("validation", 400, details={"field": "slots", "reason": "overlapping_or_unordered_times",
                                                         "slot_no": s["slot_no"]})
        if (s["kind"] == "lesson") != (s["period_no"] is not None):
            raise ApiError("validation", 400, details={"field": "slots", "reason": "lesson_needs_period_no",
                                                         "slot_no": s["slot_no"]})
        if s["period_no"] is not None:
            if s["period_no"] in periods:
                raise ApiError("validation", 400, details={"field": "slots", "reason": "duplicate_period_no"})
            periods.add(s["period_no"])
        prev_end = s["ends_at"]
    # Replace wholesale: delete old rows first to avoid unique clashes inside one flush.
    if not creating:
        obj.slots.clear()
        db.session.flush()
    obj.slots = [BellSlot(**s) for s in slots]


def _bell_read(obj: BellSchedule) -> dict:
    return {
        "slots": [
            {k: jsonable(getattr(s, k)) for k in SLOT_FIELDS}
            for s in obj.slots
        ]
    }


def _user_write(obj: AppUser, data: dict, creating: bool):
    if "password" in data:
        pw = data["password"]
        if not isinstance(pw, str) or len(pw) < 8:
            raise ApiError("validation", 400, details={"field": "password", "reason": "min 8 characters"})
        obj.set_password(pw)
    elif creating and not obj.ms_oid:
        raise ApiError("validation", 400, details={"field": "password", "reason": "required"})
    if "stage_ids" in data:
        ids = parse_uuid_list(data["stage_ids"], "stage_ids")
        obj.stages = [_must_get(Stage, i, "stage_ids") for i in ids]
    if obj.role == "stage_editor" and not obj.stages:
        raise ApiError("validation", 400, details={"field": "stage_ids", "reason": "stage_editor needs at least one stage"})
    if not creating and obj.id == current_user.id and (not obj.is_active or obj.role != "admin"):
        raise ApiError("validation", 400, details={"reason": "cannot_lock_yourself_out",
                                                     "message": "لا يمكنك سحب صلاحية المدير من حسابك أو تعطيله بنفسك"})


def _user_read(obj: AppUser) -> dict:
    return {"stage_ids": sorted(str(s.id) for s in obj.stages)}


def _user_before_delete(obj: AppUser):
    if obj.id == current_user.id:
        raise ApiError("validation", 400, details={"reason": "cannot_delete_yourself"})


def _timetable_child_guard(obj):
    tt = db.session.get(Timetable, obj.timetable_id) if obj.timetable_id else None
    if tt is None:
        raise ApiError("validation", 400, details={"field": "timetable_id", "reason": "unknown"})
    if tt.status == "archived":
        raise ApiError("timetable_readonly", 409)


def _availability_write(obj: Availability, data: dict, creating: bool):
    _timetable_child_guard(obj)


def _constraint_write(obj: ConstraintRule, data: dict, creating: bool):
    _timetable_child_guard(obj)
    if obj.kind == "weekly_load":
        from app.rules.loads import normalize_params
        obj.params = normalize_params(obj.params or {})
        p = obj.params
        obj.scope_type = "teacher" if p["teacher_ids"] else "subject" if p["subject_ids"] else "stage" if p["stage_ids"] else "global"
        obj.scope_ids = [uuid.UUID(x) for x in (p["teacher_ids"] or p["subject_ids"] or p["stage_ids"])]


def _ids_exist(model, raw, field_name) -> list[str]:
    ids = parse_uuid_list(raw or [], field_name)
    for i in ids:
        _must_get(model, i, field_name)
    return [str(i) for i in dict.fromkeys(ids)]


def _extra_dict(value, field_name="extra") -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ApiError("validation", 400, details={"field": field_name, "reason": "must be an object"})
    return value


def _time_order(obj, field="ends_at"):
    if obj.starts_at and obj.ends_at and obj.ends_at <= obj.starts_at:
        raise ApiError("validation", 400, details={"field": field, "reason": "ends_before_start",
                                                     "message": "يجب أن يكون وقت الانتهاء بعد وقت البدء"})


def _exam_write(obj: ExamSession, data: dict, creating: bool):
    _time_order(obj)
    if "grade_ids" in data:
        obj.grade_ids = [uuid.UUID(i) for i in _ids_exist(Grade, data["grade_ids"], "grade_ids")]
    if "extra" in data:
        obj.extra = _extra_dict(data["extra"])
    if "rooms" in data:
        raw = data["rooms"] or []
        if not isinstance(raw, list):
            raise ApiError("validation", 400, details={"field": "rooms", "reason": "must be a list"})
        rooms = []
        for i, r in enumerate(raw):
            if not isinstance(r, dict):
                raise ApiError("validation", 400, details={"field": f"rooms[{i}]", "reason": "must be an object"})
            room_id = r.get("room_id") or None
            if room_id:
                room_id = str(_must_get(Room, parse_uuid(room_id, f"rooms[{i}].room_id"), f"rooms[{i}].room_id").id)
            location = r.get("location")
            if location is not None and not isinstance(location, str):
                raise ApiError("validation", 400, details={"field": f"rooms[{i}].location", "reason": "must be text"})
            rooms.append({
                "room_id": room_id,
                "location": (location or "").strip() or None,
                "section_ids": _ids_exist(Section, r.get("section_ids"), f"rooms[{i}].section_ids"),
                "teacher_ids": _ids_exist(Teacher, r.get("teacher_ids"), f"rooms[{i}].teacher_ids"),
                "extra": _extra_dict(r.get("extra"), f"rooms[{i}].extra"),
            })
        obj.rooms = rooms
    if obj.subject_id is None and not (obj.title or "").strip():
        raise ApiError("validation", 400, details={"field": "subject_id", "reason": "required",
                                                     "message": "اختر المبحث أو اكتب عنواناً للامتحان"})


def _duty_write(obj: DutyAssignment, data: dict, creating: bool):
    _time_order(obj)
    if "teacher_ids" in data:
        obj.teacher_ids = [uuid.UUID(i) for i in _ids_exist(Teacher, data["teacher_ids"], "teacher_ids")]
    if "extra" in data:
        obj.extra = _extra_dict(data["extra"])


def _absence_write(obj: TeacherAbsence, data: dict, creating: bool):
    if obj.date_from and obj.date_to and obj.date_to < obj.date_from:
        raise ApiError("validation", 400, details={"field": "date_to", "reason": "before date_from",
                                                     "message": "يجب ألّا يسبق تاريخُ النهاية تاريخَ البداية"})
    if (obj.period_from is None) != (obj.period_to is None):
        raise ApiError("validation", 400, details={"field": "period_to", "reason": "both or neither",
                                                     "message": "حدِّد الحصة الأولى والأخيرة معاً، أو اتركهما فارغتين ليكون الغياب يوماً كاملاً"})
    if obj.period_from is not None and (obj.period_from < 1 or obj.period_to < obj.period_from):
        raise ApiError("validation", 400, details={"field": "period_to", "reason": "invalid range",
                                                     "message": "يجب ألّا تسبق الحصةُ الأخيرة الحصةَ الأولى"})
    if "extra" in data:
        obj.extra = _extra_dict(data["extra"])
    if (obj.date_to - obj.date_from).days > 366:
        raise ApiError("validation", 400, details={"field": "date_to", "message": "مدة الغياب أطول من سنة"})


def _absence_before_delete(obj: TeacherAbsence):
    """Decisions taken for the periods this absence covered are removed with it (unless another absence
    of the same teacher still covers them)."""
    others = [a for a in db.session.scalars(select(TeacherAbsence).where(
        TeacherAbsence.teacher_id == obj.teacher_id, TeacherAbsence.id != obj.id))]
    for s in db.session.scalars(select(Substitution).where(
            Substitution.original_teacher_id == obj.teacher_id,
            Substitution.date >= obj.date_from, Substitution.date <= obj.date_to)):
        if obj.covers(s.date, s.period_no) and not any(a.covers(s.date, s.period_no) for a in others):
            s.soft_delete()


def _substitution_write(obj: Substitution, data: dict, creating: bool):
    from app.models import Card
    from app.rules.cover import CoverDay, school_weekday
    tt = db.session.get(Timetable, obj.timetable_id)
    card = db.session.get(Card, obj.card_id)
    if tt is None or card is None or card.timetable_id != tt.id:
        raise ApiError("validation", 400, details={"field": "card_id", "reason": "not in this timetable"})
    wd = school_weekday(obj.date)
    if wd is None or card.weekday_id != wd.id or not (card.period_no <= obj.period_no < card.period_no + card.duration):
        raise ApiError("validation", 400, details={"field": "period_no", "reason": "card not on that day/period",
                                                     "message": "هذه الحصة ليست في هذا اليوم أو في هذه الحصة من الجدول"})
    lesson = db.session.get(Lesson, card.lesson_id)
    if obj.original_teacher_id not in lesson.teacher_ids:
        raise ApiError("validation", 400, details={"field": "original_teacher_id", "reason": "not a teacher of this lesson"})
    if obj.kind == "cover":
        if obj.substitute_teacher_id is None:
            raise ApiError("validation", 400, details={"field": "substitute_teacher_id", "reason": "required",
                                                         "message": "اختر المعلم البديل"})
        if obj.substitute_teacher_id in lesson.teacher_ids:
            raise ApiError("validation", 400, details={"field": "substitute_teacher_id",
                                                         "message": "المعلم البديل من معلمي الحصة نفسها"})
        day = CoverDay(tt, obj.date)
        t = db.session.get(Teacher, obj.substitute_teacher_id)
        if t is None:
            raise ApiError("validation", 400, details={"field": "substitute_teacher_id", "reason": "unknown_reference"})
        name = f"{'المعلمة' if t.gender == 'f' else 'المعلم'} {t.name_ar}"
        if obj.period_no in day.teaching.get(t.id, {}):
            raise ApiError("substitute_busy", 409, details={"message": f"{name}: لديه حصة في الوقت نفسه" if t.gender != "f"
                                                                     else f"{name}: لديها حصة في الوقت نفسه"})
        if day.absence_of(t.id, obj.period_no):
            raise ApiError("substitute_busy", 409, details={"message": f"{name}: {'غائبة' if t.gender == 'f' else 'غائب'} في هذه الحصة"})
        if (t.id, obj.period_no) in day.covering(exclude_id=obj.id):
            raise ApiError("substitute_busy", 409, details={"message": f"{name}: {'تغطي' if t.gender == 'f' else 'يغطي'} حصة أخرى في الوقت نفسه"})
    elif obj.kind in ("cancel", "none"):
        obj.substitute_teacher_id = None
    if not creating:
        obj.auto = False


def _must_get(model, id_, field_name):
    obj = db.session.get(model, id_)
    if obj is None:
        raise ApiError("validation", 400, details={"field": field_name, "reason": "unknown_reference", "id": str(id_)})
    return obj


RESOURCES: dict[str, Resource] = {
    "school": Resource(School, hidden_fields=frozenset({"logo_data"}), read_only_fields=frozenset({"logo_mime"})),
    "academic-years": Resource(AcademicYear),
    "terms": Resource(Term),
    "weekdays": Resource(Weekday),
    "stages": Resource(Stage),
    "grades": Resource(Grade),
    "sections": Resource(Section),
    "divisions": Resource(Division, create_only_fields=frozenset({"section_id"})),
    "groups": Resource(StudentGroup, create_only_fields=frozenset({"division_id"})),
    "bell-schedules": Resource(BellSchedule, write_extra=_bell_write, read_extra=_bell_read),
    "bell-assignments": Resource(BellAssignment),
    "subjects": Resource(Subject, write_extra=_subject_write, read_extra=_subject_read),
    "teachers": Resource(Teacher, write_extra=_teacher_write, read_extra=_teacher_read),
    "buildings": Resource(Building),
    "rooms": Resource(Room),
    "timetables": Resource(
        Timetable,
        read_only_fields=frozenset({"status", "published_at", "published_by", "based_on_id"}),
        create_only_fields=frozenset({"term_id"}),
    ),
    "availability": Resource(Availability, write_extra=_availability_write,
                             create_only_fields=frozenset({"timetable_id"})),
    "exam-sessions": Resource(ExamSession, write_extra=_exam_write),
    "duty-assignments": Resource(DutyAssignment, write_extra=_duty_write),
    "absences": Resource(TeacherAbsence, write_extra=_absence_write, before_delete=_absence_before_delete),
    "substitutions": Resource(Substitution, write_extra=_substitution_write,
                              read_only_fields=frozenset({"notified_at"}),
                              create_only_fields=frozenset({"timetable_id", "date", "card_id", "period_no",
                                                            "original_teacher_id"})),
    "constraint-rules": Resource(ConstraintRule, write_extra=_constraint_write,
                                 create_only_fields=frozenset({"timetable_id"})),
    "users": Resource(
        AppUser,
        hidden_fields=frozenset({"password_hash"}),
        read_only_fields=frozenset({"last_login_at"}),
        write_extra=_user_write,
        read_extra=_user_read,
        admin_read_only=True,
        before_delete=_user_before_delete,
    ),
}

# Association tables cleaned automatically when a parent is soft-deleted.
AUTO_CLEAN_TABLES = {"teacher_stage", "teacher_subject", "subject_room", "user_stage"}
IGNORED_DEPENDENTS = {"occupancy", "bell_slot", "idempotency_key", "notification", "push_subscription", "audit_log"}
AUDIT_COLUMNS = {"created_by", "updated_by", "published_by"}


def live_dependents(obj) -> dict[str, int]:
    table = obj.__table__
    out: dict[str, int] = {}
    for t in db.metadata.sorted_tables:
        if t.name in AUTO_CLEAN_TABLES or t.name in IGNORED_DEPENDENTS:
            continue
        for fk in t.foreign_keys:
            if fk.column.table is not table or fk.parent.name in AUDIT_COLUMNS:
                continue
            q = select(func.count()).select_from(t).where(fk.parent == obj.id)
            if "deleted_at" in t.c:
                q = q.where(t.c.deleted_at.is_(None))
            elif "lesson_id" in t.c:  # lesson_teacher / lesson_target: count only live lessons
                q = q.where(t.c.lesson_id.in_(select(Lesson.id).where(Lesson.deleted_at.is_(None))))
            n = db.session.execute(q.execution_options(include_deleted=True)).scalar_one()
            if t is table and fk.parent == table.c.id:  # pragma: no cover - self row
                continue
            if n:
                out[t.name] = out.get(t.name, 0) + n
    return out


def _get_res(name: str) -> Resource:
    res = RESOURCES.get(name)
    if res is None:
        raise ApiError("not_found", 404)
    return res


def _get_obj(res: Resource, id_: str):
    obj = db.session.get(res.model, parse_uuid(id_))
    if obj is None:
        raise ApiError("not_found", 404)
    return obj


def apply_fields(res: Resource, obj, data: dict, creating: bool) -> None:
    for col in res.fields:
        if col.name not in data:
            continue
        if not creating and col.name in res.create_only_fields:
            if data[col.name] != jsonable(getattr(obj, col.name)):
                raise ApiError("validation", 400, details={"field": col.name, "reason": "cannot be changed"})
            continue
        setattr(obj, col.name, coerce(col, col.name, data[col.name]))
    if creating:
        for col in res.fields:
            if (not col.nullable and col.name not in data and col.default is None
                    and col.server_default is None and not col.foreign_keys and col.name not in ("id",)):
                raise ApiError("validation", 400, details={"field": col.name, "reason": "required"})
            if not col.nullable and col.foreign_keys and col.name not in data:
                raise ApiError("validation", 400, details={"field": col.name, "reason": "required"})


def query_value(col, name: str, raw: str):
    """Query-string values are always strings; convert before type coercion."""
    try:
        py = col.type.python_type
    except NotImplementedError:  # pragma: no cover
        py = str
    if py is int:
        try:
            return int(raw)
        except ValueError:
            raise ApiError("validation", 400, details={"field": name, "reason": "invalid int"})
    if py is bool:
        return raw.lower() in ("1", "true", "yes")
    return coerce(col, name, raw)


def check_version(obj, supplied) -> None:
    if isinstance(supplied, bool) or not isinstance(supplied, int):
        raise ApiError("validation", 400, details={"field": "version", "reason": "required integer"})
    if supplied != obj.version:
        raise ApiError("version_conflict", 409, details={"current": obj.to_dict()})


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@api_bp.get("/<res_name>")
@login_required
def list_resource(res_name):
    res = _get_res(res_name)
    if res.admin_read_only:
        require_admin(current_user)
    q = select(res.model)
    cols = res.model.__table__.columns
    for k, v in request.args.items():
        if k in cols and k not in res.hidden_fields:
            q = q.where(cols[k] == query_value(cols[k], k, v))
    order = [c for c in ("exam_date", "date", "date_from", "period_no", "starts_at", "sort_order", "name_ar", "slot_no", "created_at") if c in cols]
    if order:
        q = q.order_by(*(cols[c] for c in order))
    items = db.session.scalars(q).all()
    return jsonify(items=[serialize(res, o) for o in items])


@api_bp.get("/<res_name>/<id_>")
@login_required
def get_resource(res_name, id_):
    res = _get_res(res_name)
    if res.admin_read_only:
        require_admin(current_user)
    return jsonify(serialize(res, _get_obj(res, id_)))


@api_bp.post("/<res_name>")
@write_endpoint
def create_resource(res_name):
    res = _get_res(res_name)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("validation", 400, details={"reason": "json object required"})
    obj = res.model()
    if data.get("id") is not None:
        obj.id = parse_uuid(data["id"])
    apply_fields(res, obj, data, creating=True)
    if res.write_extra:
        res.write_extra(obj, data, True)
    require_write(current_user, obj)
    db.session.add(obj)
    db.session.flush()
    db.session.refresh(obj)
    return serialize(res, obj), 201


@api_bp.patch("/<res_name>/<id_>")
@write_endpoint
def update_resource(res_name, id_):
    res = _get_res(res_name)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("validation", 400, details={"reason": "json object required"})
    obj = _get_obj(res, id_)
    require_write(current_user, obj)
    check_version(obj, data.get("version"))
    apply_fields(res, obj, data, creating=False)
    if res.write_extra:
        res.write_extra(obj, data, False)
    require_write(current_user, obj)  # cannot move a record into a stage you don't own
    db.session.flush()
    db.session.refresh(obj)
    return serialize(res, obj), 200


@api_bp.delete("/<res_name>/<id_>")
@write_endpoint
def delete_resource(res_name, id_):
    res = _get_res(res_name)
    obj = _get_obj(res, id_)
    require_write(current_user, obj)
    try:
        version = int(request.args.get("version", ""))
    except ValueError:
        version = None
    check_version(obj, version)
    if res.before_delete:
        res.before_delete(obj)
    deps = live_dependents(obj)
    if deps:
        raise ApiError("has_dependents", 409, details=deps)
    obj.soft_delete()
    _clean_after_delete(obj)
    db.session.flush()
    return {"id": str(obj.id), "deleted": True, "version": obj.version}, 200


@api_bp.post("/<res_name>/bulk-delete")
@write_endpoint
def bulk_delete_resource(res_name):
    """Delete several records at once: {"items": [{"id", "version"}, …]}. All or nothing:
    one refusal (permission, stale version, dependants) cancels the whole batch."""
    res = _get_res(res_name)
    data = request.get_json(silent=True) or {}
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise ApiError("validation", 400, details={"field": "items", "reason": "non-empty list required"})
    if len(items) > 1000:
        raise ApiError("validation", 400, details={"field": "items", "reason": "at most 1000"})
    deleted = []
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            raise ApiError("validation", 400, details={"field": f"items[{i}]"})
        obj = _get_obj(res, str(it.get("id")))
        require_write(current_user, obj)
        check_version(obj, it.get("version"))
        if res.before_delete:
            res.before_delete(obj)
        deps = live_dependents(obj)
        if deps:
            raise ApiError("has_dependents", 409, details={**deps, "id": str(obj.id)})
        obj.soft_delete()
        _clean_after_delete(obj)
        deleted.append(str(obj.id))
    db.session.flush()
    return {"deleted": deleted, "count": len(deleted)}, 200


def _clean_after_delete(obj) -> None:
    for rel in ("stages", "subjects", "rooms"):
        if hasattr(obj, rel) and isinstance(getattr(obj, rel), list):
            setattr(obj, rel, [])
    kind = {Teacher: "teacher", Section: "section", Subject: "subject", Room: "room"}.get(type(obj))
    if kind:
        for a in db.session.scalars(
            select(Availability).where(Availability.entity_type == kind, Availability.entity_id == obj.id)
        ):
            a.soft_delete()
    if isinstance(obj, Teacher):   # duty and invigilation lists hold teacher ids without a foreign key
        tid = str(obj.id)
        for d in db.session.scalars(select(DutyAssignment).where(DutyAssignment.teacher_ids.contains([obj.id]))):
            d.teacher_ids = [x for x in d.teacher_ids if x != obj.id]
        for e in db.session.scalars(select(ExamSession)):
            if any(tid in (r.get("teacher_ids") or []) for r in e.rooms or []):
                e.rooms = [{**r, "teacher_ids": [x for x in r.get("teacher_ids") or [] if x != tid]} for r in e.rooms]
