"""Period plans (منشئ الخطط): periods of the term, fill from the weekly plan, approve, analyse."""
from __future__ import annotations

from datetime import date

from flask import jsonify, request
from flask_login import current_user, login_required

from app.api import api_bp
from app.api.idempotency import write_endpoint
from app.api.serialize import parse_uuid
from app.auth.permissions import require_admin, require_write
from app.errors import ApiError
from app.extensions import db
from app.models import PeriodPlan, Term, Timetable
from app.models.base import utcnow
from app.rules import plans as P


def _plan(pid) -> PeriodPlan:
    p = db.session.get(PeriodPlan, parse_uuid(pid))
    if p is None:
        raise ApiError("not_found", 404)
    return p


@api_bp.get("/plans/<pid>/periods")
@login_required
def plan_periods(pid):
    p = _plan(pid)
    cal = P.Calendar(db.session.get(Term, p.term_id))
    lang = request.args.get("lang", "ar")
    return jsonify({"periods": P.periods(p, cal, lang), "days_per_week": cal.days_per_week,
                    "school_days": len(cal.school_days(p.stage_id)), "all_days": len(cal.all_days()),
                    "grades": [{"id": str(g.id), "name_ar": g.name_ar, "name_en": g.name_en} for g in P.plan_grades(p)]})


@api_bp.post("/plans/<pid>/fill-weekly")
@write_endpoint
def plan_fill(pid):
    p = _plan(pid)
    require_write(current_user, p)
    data = request.get_json(silent=True) or {}
    ids = [parse_uuid(x, "grade_ids") for x in data["grade_ids"]] if data.get("grade_ids") else None
    n = P.fill_from_weekly(p, ids, bool(data.get("overwrite")))
    if p.status == "approved":
        p.status, p.approved_by, p.approved_at = "draft", None, None
    db.session.flush()
    return {"filled": n, "targets": p.targets, "version": p.version, "status": p.status}, 200


@api_bp.post("/plans/<pid>/approve")
@write_endpoint
def plan_approve(pid):
    require_admin(current_user)
    p = _plan(pid)
    data = request.get_json(silent=True) or {}
    if data.get("approve", True):
        p.status, p.approved_by, p.approved_at = "approved", current_user.id, utcnow()
    else:
        p.status, p.approved_by, p.approved_at = "draft", None, None
    db.session.flush()
    return p.to_dict(), 200


@api_bp.get("/plans/<pid>/analysis")
@login_required
def plan_analysis(pid):
    p = _plan(pid)
    tt = db.session.get(Timetable, parse_uuid(request.args.get("timetable_id"), "timetable_id"))
    if tt is None:
        raise ApiError("validation", 400, details={"field": "timetable_id"})
    today = date.fromisoformat(request.args["today"]) if request.args.get("today") else None
    return jsonify(P.analyze(p, tt, request.args.get("period") or None, today))
