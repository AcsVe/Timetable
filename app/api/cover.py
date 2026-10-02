"""Absences and cover (حصص الإشغال) for one day, ranked substitutes, automatic assignment,
messages to the substitutes, and each user's in-app notifications."""
from __future__ import annotations

from datetime import date

from flask import jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import select

from app.api import api_bp
from app.api.idempotency import write_endpoint
from app.api.serialize import parse_uuid
from app.auth.permissions import can_write
from app.errors import ApiError
from app.extensions import db
from app.models import Notification, Substitution, Timetable
from app.models.base import utcnow
from app.rules.cover import KIND_LABELS, CoverDay, week_start


def _tt(tt_id) -> Timetable:
    tt = db.session.get(Timetable, parse_uuid(tt_id))
    if tt is None:
        raise ApiError("not_found", 404)
    return tt


def _date(raw, field="date") -> date:
    try:
        return date.fromisoformat(str(raw))
    except (TypeError, ValueError):
        raise ApiError("validation", 400, details={"field": field, "reason": "YYYY-MM-DD"})


@api_bp.get("/timetables/<tt_id>/cover")
@login_required
def cover_day(tt_id):
    tt = _tt(tt_id)
    d = _date(request.args.get("date"))
    day = CoverDay(tt, d)
    needs = day.needs()
    return jsonify({
        "date": d.isoformat(), "week_start": week_start(d).isoformat(),
        "weekday": {"id": str(day.weekday.id), "name_ar": day.weekday.name_ar, "name_en": day.weekday.name_en}
        if day.weekday else None,
        "cycle_week": day.week,
        "absences": [{"id": str(a.id), "teacher_id": str(a.teacher_id), "date_from": a.date_from.isoformat(),
                      "date_to": a.date_to.isoformat(), "period_from": a.period_from, "period_to": a.period_to,
                      "reason": a.reason, "note": a.note, "version": a.version, "extra": a.extra} for a in day.absences],
        "needs": [day.need_json(n) for n in needs],
        "summary": day.summary(needs),
        "kinds": {k: {"ar": v[0], "en": v[1]} for k, v in KIND_LABELS.items()},
    })


@api_bp.get("/timetables/<tt_id>/cover/candidates")
@login_required
def cover_candidates(tt_id):
    tt = _tt(tt_id)
    day = CoverDay(tt, _date(request.args.get("date")))
    key = request.args.get("key", "")
    need = next((n for n in day.needs() if n.key == key), None)
    if need is None:
        raise ApiError("not_found", 404, details={"field": "key"})
    exclude = need.substitution.id if need.substitution else None
    return jsonify({"key": key, "candidates": day.candidates(need, exclude_sub_id=exclude)})


@api_bp.post("/timetables/<tt_id>/cover/auto")
@write_endpoint
def cover_auto(tt_id):
    tt = _tt(tt_id)
    data = request.get_json(silent=True) or {}
    d = _date(data.get("date"))
    keys = set(data["keys"]) if isinstance(data.get("keys"), list) and data["keys"] else None
    day = CoverDay(tt, d)
    if current_user.role != "admin":   # a stage editor may only decide for lessons of their stages
        allowed = {n.key for n in day.needs() if can_write(current_user, n.card)}
        keys = (keys & allowed) if keys is not None else allowed
    return day.auto_assign(keys), 200


@api_bp.post("/timetables/<tt_id>/cover/clear")
@write_endpoint
def cover_clear(tt_id):
    """Remove the decisions of a day (all, the automatic ones only, or the chosen ones)."""
    tt = _tt(tt_id)
    data = request.get_json(silent=True) or {}
    d = _date(data.get("date"))
    ids = {str(x) for x in data.get("ids") or []}
    only_auto = bool(data.get("only_auto"))
    n = 0
    for s in db.session.scalars(select(Substitution).where(Substitution.timetable_id == tt.id, Substitution.date == d)):
        if ids and str(s.id) not in ids:
            continue
        if only_auto and not s.auto:
            continue
        if not can_write(current_user, s):
            continue
        s.soft_delete()
        n += 1
    db.session.flush()
    return {"deleted": n}, 200


@api_bp.get("/timetables/<tt_id>/cover/messages")
@login_required
def cover_messages(tt_id):
    tt = _tt(tt_id)
    return jsonify({"messages": CoverDay(tt, _date(request.args.get("date"))).messages()})


@api_bp.post("/timetables/<tt_id>/cover/notify")
@write_endpoint
def cover_notify(tt_id):
    """E-mail every substitute of the day (Microsoft Graph), put a notice in the inbox of those with a
    user account, and mark the day's covers as notified."""
    from app.notify.deliver import deliver
    tt = _tt(tt_id)
    data = request.get_json(silent=True) or {}
    d = _date(data.get("date"))
    day = CoverDay(tt, d)
    msgs = day.messages()
    if data.get("teacher_ids"):
        wanted = {str(x) for x in data["teacher_ids"]}
        msgs = [m for m in msgs if m["teacher_id"] in wanted]
    out = deliver(msgs, kind="cover", title=f"حصص إشغال يوم {day.weekday.name_ar if day.weekday else ''} {d.isoformat()}".replace("  ", " "),
                  title_en=f"Cover on {d.isoformat()}", url=f"#/cover?date={d.isoformat()}",
                  email=data.get("email", True) is not False, in_app=data.get("in_app", True) is not False)
    ok = {r["teacher_id"] for r in out["results"] if r["email_status"] == "sent" or r["in_app"]}
    now = utcnow()
    for s in day.subs:
        if s.kind == "cover" and s.notified_at is None and s.deleted_at is None and str(s.substitute_teacher_id) in ok:
            s.notified_at = now
    db.session.flush()
    out["messages"] = msgs
    return out, 200


# ---------------------------------------------------------------------------
# My notifications (topbar bell)
# ---------------------------------------------------------------------------
@api_bp.get("/notifications/mine")
@login_required
def my_notifications():
    rows = db.session.scalars(select(Notification).where(Notification.user_id == current_user.id)
                              .order_by(Notification.created_at.desc()).limit(50)).all()
    return jsonify({"unread": sum(1 for r in rows if r.read_at is None), "items": [{
        "id": str(r.id), "kind": r.kind, "title_ar": r.title_ar, "title_en": r.title_en, "body": r.body, "url": r.url,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "read": r.read_at is not None} for r in rows]})


@api_bp.post("/notifications/read")
@write_endpoint
def read_notifications():
    data = request.get_json(silent=True) or {}
    ids = {str(x) for x in data.get("ids") or []}
    n = 0
    for r in db.session.scalars(select(Notification).where(Notification.user_id == current_user.id,
                                                           Notification.read_at.is_(None))):
        if not ids or str(r.id) in ids:
            r.read_at = utcnow()
            n += 1
    return {"read": n}, 200
