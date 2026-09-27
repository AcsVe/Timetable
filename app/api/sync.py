"""Delta sync + system settings.

GET /api/sync?since=<change_seq>  → every row (including soft-deleted tombstones)
changed after `since`, in change_seq order, paged. This is what the offline
cache (level 1) and, later, the offline outbox (level 2) build on.
"""
from __future__ import annotations

from flask import current_app, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import select

from app.api import api_bp
from app.api.crud import RESOURCES, serialize
from app.api.idempotency import write_endpoint
from app.api.scheduling import serialize_card, serialize_lesson
from app.auth.permissions import require_admin
from app.errors import ApiError
from app.extensions import db
from app.models import AppSetting, Card, Lesson

# Public settings any signed-in client may read (e.g. to know whether offline editing is on).
PUBLIC_SETTINGS = {"offline_edit_enabled", "vapid_public_key", "school_week_start"}


def _synced():
    for name, res in RESOURCES.items():
        if res.admin_read_only:
            continue
        yield name, res.model, (lambda o, r=res: serialize(r, o))
    yield "lessons", Lesson, serialize_lesson_no_cards
    yield "cards", Card, serialize_card


def serialize_lesson_no_cards(o):
    return serialize_lesson(o, with_cards=False)


@api_bp.get("/sync")
@login_required
def sync():
    try:
        since = int(request.args.get("since", "0"))
    except ValueError:
        raise ApiError("validation", 400, details={"field": "since"})
    limit = min(int(request.args.get("limit", current_app.config["SYNC_PAGE_SIZE"])), 2000)
    batch = []
    for name, model, ser in _synced():
        rows = db.session.scalars(
            select(model).where(model.change_seq > since).order_by(model.change_seq).limit(limit)
            .execution_options(include_deleted=True)
        ).all()
        batch.extend((r.change_seq, name, r, ser) for r in rows)
    # Each model contributed its lowest `limit` rows, so the lowest `limit` overall are exact.
    batch.sort(key=lambda x: x[0])
    batch = batch[:limit]
    changes = [{"type": name, "deleted": r.deleted_at is not None, "data": ser(r)} for _, name, r, ser in batch]
    nxt = batch[-1][0] if batch else since
    return jsonify(changes=changes, next=nxt, more=len(batch) == limit)


@api_bp.get("/settings")
@login_required
def list_settings():
    q = select(AppSetting)
    rows = db.session.scalars(q).all()
    if current_user.role != "admin":
        rows = [r for r in rows if r.key in PUBLIC_SETTINGS]
    return jsonify({r.key: r.value for r in rows})


@api_bp.put("/settings/<key>")
@write_endpoint
def put_setting(key):
    require_admin(current_user)
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or "value" not in data:
        raise ApiError("validation", 400, details={"field": "value"})
    row = db.session.get(AppSetting, key) or AppSetting(key=key)
    row.value = data["value"]
    db.session.add(row)
    return {"key": key, "value": row.value}, 200
