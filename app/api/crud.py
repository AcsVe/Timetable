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
    Grade,
    Lesson,
    Room,
    School,
    Section,
    Stage,
    StudentGroup,
    Subject,
    Teacher,
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
                                                     "message": "لا يمكنك إلغاء صلاحية المدير أو تعطيل حسابك بنفسك"})


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


def _must_get(model, id_, field_name):
    obj = db.session.get(model, id_)
    if obj is None:
        raise ApiError("validation", 400, details={"field": field_name, "reason": "unknown_reference", "id": str(id_)})
    return obj


RESOURCES: dict[str, Resource] = {
    "school": Resource(School),
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
    order = [c for c in ("sort_order", "name_ar", "slot_no", "created_at") if c in cols]
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
