"""Exam timetable / duty roster helpers: screen configuration, checks, copying a roster between terms."""
from __future__ import annotations

from flask import jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import select

from app.api import api_bp
from app.api.idempotency import write_endpoint
from app.api.serialize import parse_uuid
from app.auth.permissions import require_write
from app.errors import ApiError
from app.extensions import db
from app.models import DutyAssignment, ExamSession, Term, Timetable
from app.rules.modules import MODULES, load_module
from app.rules.school_ops import check_duties, check_exams


@api_bp.get("/modules/<name>")
@login_required
def get_module(name):
    if name not in MODULES:
        raise ApiError("not_found", 404)
    return jsonify(load_module(name))


def _term(raw, field="term_id") -> Term:
    if not raw:
        raise ApiError("validation", 400, details={"field": field, "reason": "required"})
    term = db.session.get(Term, parse_uuid(raw, field))
    if term is None:
        raise ApiError("validation", 400, details={"field": field, "reason": "unknown"})
    return term


def _timetable_for(term: Term, raw=None) -> Timetable | None:
    if raw:
        return db.session.get(Timetable, parse_uuid(raw, "timetable_id"))
    rows = list(db.session.scalars(select(Timetable).where(Timetable.term_id == term.id)))
    return next((t for t in rows if t.status == "published"), None) or next(
        (t for t in rows if t.status == "draft"), None)


@api_bp.get("/school-ops/check")
@login_required
def school_ops_check():
    term = _term(request.args.get("term_id"))
    what = request.args.get("what", "all")
    out = {}
    if what in ("all", "exams"):
        out["exams"] = check_exams(term.id)
    if what in ("all", "duties"):
        out["duties"] = check_duties(term.id, _timetable_for(term, request.args.get("timetable_id")))
    return jsonify(out)


@api_bp.post("/duty-assignments/copy")
@write_endpoint
def copy_duties():
    """Copy every duty of one term into another (e.g. the first term's roster into the second)."""
    data = request.get_json(silent=True) or {}
    src, dst = _term(data.get("from_term_id"), "from_term_id"), _term(data.get("to_term_id"), "to_term_id")
    if src.id == dst.id:
        raise ApiError("validation", 400, details={"field": "to_term_id", "reason": "same term",
                                                     "message": "اختر فصلاً دراسياً غير الفصل المنسوخ منه"})
    if data.get("replace"):
        for d in db.session.scalars(select(DutyAssignment).where(DutyAssignment.term_id == dst.id)):
            require_write(current_user, d)
            d.soft_delete()
    n = 0
    cols = [c.name for c in DutyAssignment.__table__.columns
            if c.name not in ("id", "term_id", "created_at", "updated_at", "version", "change_seq", "deleted_at",
                              "created_by", "updated_by")]
    for d in db.session.scalars(select(DutyAssignment).where(DutyAssignment.term_id == src.id)):
        copy = DutyAssignment(term_id=dst.id, **{c: getattr(d, c) for c in cols})
        require_write(current_user, copy)
        db.session.add(copy)
        n += 1
    db.session.flush()
    return {"copied": n}, 200


@api_bp.post("/exam-sessions/copy")
@write_endpoint
def copy_exams():
    """Copy the exams of a term (e.g. to reuse rooms and invigilators); dates are shifted by `shift_days`."""
    from datetime import timedelta
    data = request.get_json(silent=True) or {}
    src, dst = _term(data.get("from_term_id"), "from_term_id"), _term(data.get("to_term_id"), "to_term_id")
    try:
        shift = int(data.get("shift_days") or 0)
    except (TypeError, ValueError):
        raise ApiError("validation", 400, details={"field": "shift_days"})
    cols = [c.name for c in ExamSession.__table__.columns
            if c.name not in ("id", "term_id", "created_at", "updated_at", "version", "change_seq", "deleted_at",
                              "created_by", "updated_by")]
    n = 0
    for e in db.session.scalars(select(ExamSession).where(ExamSession.term_id == src.id)):
        copy = ExamSession(term_id=dst.id, **{c: getattr(e, c) for c in cols})
        copy.exam_date = e.exam_date + timedelta(days=shift)
        require_write(current_user, copy)
        db.session.add(copy)
        n += 1
    db.session.flush()
    return {"copied": n}, 200
