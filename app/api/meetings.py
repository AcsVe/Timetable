"""Meetings: the message each member receives (when and where), preview and send."""
from __future__ import annotations

from collections import defaultdict

from flask import jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import select

from app.api import api_bp
from app.api.idempotency import write_endpoint
from app.api.serialize import parse_uuid
from app.arabic import g, teacher_title
from app.auth.permissions import require_admin
from app.errors import ApiError
from app.extensions import db
from app.models import BellSchedule, Card, Lesson, Room, Teacher, Timetable, Weekday


def _tt(tt_id) -> Timetable:
    tt = db.session.get(Timetable, parse_uuid(tt_id, "timetable_id"))
    if tt is None:
        raise ApiError("not_found", 404)
    return tt


def meeting_messages(tt: Timetable, wanted: set[str] | None = None) -> list[dict]:
    days = {d.id: d for d in db.session.scalars(select(Weekday))}
    order = {d.id: d.sort_order for d in days.values()}
    lines = defaultdict(list)
    for l in db.session.scalars(select(Lesson).where(Lesson.timetable_id == tt.id, Lesson.kind == "meeting")
                                .order_by(Lesson.title)):
        sched = db.session.get(BellSchedule, l.bell_schedule_id) if l.bell_schedule_id else None
        slots = {s.period_no: s for s in sched.slots if s.kind == "lesson"} if sched else {}
        cards = sorted((c for c in db.session.scalars(select(Card).where(Card.lesson_id == l.id)) if c.weekday_id),
                       key=lambda c: (order.get(c.weekday_id, 99), c.period_no))
        if not cards:
            continue
        parts = []
        for c in cards:
            p = f"الحصة {c.period_no}" if c.duration == 1 else f"الحصص {c.period_no}–{c.period_no + c.duration - 1}"
            a, b = slots.get(c.period_no), slots.get(c.period_no + c.duration - 1)
            when = f" (⁦{a.starts_at.strftime('%H:%M')}–{b.ends_at.strftime('%H:%M')}⁩)" if a and b else ""
            room = db.session.get(Room, c.room_id or l.preferred_room_id) if (c.room_id or l.preferred_room_id) else None
            parts.append(f"يوم {days[c.weekday_id].name_ar}، {p}{when}" + (f"، في {room.name_ar}" if room else ""))
        for tid in l.teacher_ids:
            lines[tid].append(f"• {l.title}: " + "؛ ".join(parts))
    out = []
    for tid, ls in lines.items():
        if wanted is not None and str(tid) not in wanted:
            continue
        t = db.session.get(Teacher, tid)
        if t is None:
            continue
        hello = f"{g(t.gender, 'عزيزي', 'عزيزتي')} {teacher_title(t.gender)} {t.name_ar}،"
        text = "\n".join([hello, f"مواعيد اجتماعاتك الأسبوعية في «{tt.name}»:", *ls])
        out.append({"teacher_id": str(t.id), "name": t.name_ar, "email": t.email, "phone": t.phone, "text": text})
    return sorted(out, key=lambda m: m["name"])


@api_bp.get("/timetables/<tt_id>/meetings/messages")
@login_required
def meetings_messages(tt_id):
    return jsonify({"messages": meeting_messages(_tt(tt_id))})


@api_bp.post("/timetables/<tt_id>/meetings/notify")
@write_endpoint
def notify_meetings(tt_id):
    require_admin(current_user)
    from app.notify.deliver import deliver
    tt = _tt(tt_id)
    data = request.get_json(silent=True) or {}
    wanted = {str(x) for x in data.get("teacher_ids") or []} or None
    msgs = meeting_messages(tt, wanted)
    out = deliver(msgs, kind="meetings", title=f"مواعيد الاجتماعات — {tt.name}", title_en=f"Meetings — {tt.name}",
                  url="#/meetings", email=data.get("email", True) is not False, in_app=data.get("in_app", True) is not False)
    out["messages"] = msgs
    return out, 200
