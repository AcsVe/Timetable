"""Study plan (الخطة الدراسية): grade × subject weekly periods, the check against a timetable's
lessons, and creating / correcting lessons from the plan."""
from __future__ import annotations

from flask import jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import select

from app.api import api_bp
from app.api.idempotency import write_endpoint
from app.api.serialize import parse_uuid
from app.auth.permissions import can_write, require_write
from app.errors import ApiError
from app.extensions import db
from app.models import CurriculumItem, Grade, Subject, Timetable
from app.rules import curriculum as C


def _int(v, field, lo, hi, allow_zero=False):
    if v in (None, ""):
        return 0 if allow_zero else None
    if isinstance(v, bool):
        raise ApiError("validation", 400, details={"field": field})
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ApiError("validation", 400, details={"field": field, "reason": "number"})
    if not ((allow_zero and n == 0) or lo <= n <= hi):
        raise ApiError("validation", 400, details={"field": field, "reason": f"{lo}..{hi}"})
    return n


@api_bp.get("/curriculum")
@login_required
def list_curriculum():
    rows = db.session.scalars(select(CurriculumItem)).all()
    return jsonify({"items": [r.to_dict() for r in rows]})


@api_bp.put("/curriculum/bulk")
@write_endpoint
def save_curriculum():
    """{"items": [{"grade_id", "subject_id", "periods_per_week", "duration"}]} — 0 or empty periods removes the
    subject from that grade's plan. All or nothing."""
    data = request.get_json(silent=True) or {}
    items = data.get("items")
    if not isinstance(items, list) or len(items) > 3000:
        raise ApiError("validation", 400, details={"field": "items"})
    existing = {(r.grade_id, r.subject_id): r for r in db.session.scalars(select(CurriculumItem))}
    saved = removed = 0
    for i, it in enumerate(items):
        g = db.session.get(Grade, parse_uuid(it.get("grade_id"), f"items[{i}].grade_id"))
        s = db.session.get(Subject, parse_uuid(it.get("subject_id"), f"items[{i}].subject_id"))
        if g is None or s is None:
            raise ApiError("validation", 400, details={"field": f"items[{i}]", "reason": "unknown grade or subject"})
        ppw = _int(it.get("periods_per_week"), f"items[{i}].periods_per_week", 1, 40, allow_zero=True)
        dur = _int(it.get("duration"), f"items[{i}].duration", 1, 4) or 1
        row = existing.get((g.id, s.id))
        if not ppw:
            if row is not None:
                require_write(current_user, row)
                row.soft_delete()
                existing.pop((g.id, s.id))
                removed += 1
            continue
        if row is None:
            row = CurriculumItem(grade_id=g.id, subject_id=s.id, periods_per_week=ppw, duration=dur)
            require_write(current_user, row)
            db.session.add(row)
            existing[(g.id, s.id)] = row
            saved += 1
        elif (row.periods_per_week, row.duration) != (ppw, dur):
            require_write(current_user, row)
            row.periods_per_week, row.duration = ppw, dur
            saved += 1
    db.session.flush()
    return {"saved": saved, "removed": removed}, 200


@api_bp.post("/curriculum/copy")
@write_endpoint
def copy_curriculum():
    """Copy one grade's plan to other grades: {"from_grade_id", "to_grade_ids": [...], "replace": bool}."""
    data = request.get_json(silent=True) or {}
    src = db.session.get(Grade, parse_uuid(data.get("from_grade_id"), "from_grade_id"))
    if src is None:
        raise ApiError("validation", 400, details={"field": "from_grade_id"})
    plan = C.plan_by_grade()
    source = plan.get(src.id, {})
    n = 0
    for raw in data.get("to_grade_ids") or []:
        g = db.session.get(Grade, parse_uuid(raw, "to_grade_ids"))
        if g is None or g.id == src.id:
            continue
        mine = plan.get(g.id, {})
        if data.get("replace"):
            for sid, row in list(mine.items()):
                if sid not in source:
                    require_write(current_user, row)
                    row.soft_delete()
        for sid, it in source.items():
            row = mine.get(sid)
            if row is None:
                row = CurriculumItem(grade_id=g.id, subject_id=sid, periods_per_week=it.periods_per_week, duration=it.duration)
                require_write(current_user, row)
                db.session.add(row)
                n += 1
            elif data.get("replace") and (row.periods_per_week, row.duration) != (it.periods_per_week, it.duration):
                require_write(current_user, row)
                row.periods_per_week, row.duration = it.periods_per_week, it.duration
                n += 1
    db.session.flush()
    return {"copied": n}, 200


def _tt(tt_id) -> Timetable:
    tt = db.session.get(Timetable, parse_uuid(tt_id, "timetable_id"))
    if tt is None:
        raise ApiError("not_found", 404)
    return tt


@api_bp.get("/timetables/<tt_id>/curriculum/check")
@login_required
def curriculum_check(tt_id):
    return jsonify(C.check(_tt(tt_id)))


@api_bp.post("/timetables/<tt_id>/curriculum/apply")
@write_endpoint
def curriculum_apply(tt_id):
    from app.api.scheduling import editable_timetable
    tt = editable_timetable(_tt(tt_id).id)
    data = request.get_json(silent=True) or {}
    keys = data.get("keys")
    if keys is not None and not isinstance(keys, list):
        raise ApiError("validation", 400, details={"field": "keys"})
    out = C.apply(tt, [str(k) for k in keys] if keys is not None else None, bool(data.get("assign_teacher")),
                  lambda obj: can_write(current_user, obj))
    return out, 200
