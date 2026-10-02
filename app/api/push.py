"""Web Push: the server key, subscribing this device, and a test notification."""
from __future__ import annotations

from flask import jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import func, select

from app.api import api_bp
from app.api.idempotency import write_endpoint
from app.errors import ApiError
from app.extensions import db
from app.models import PushSubscription
from app.notify import webpush


@api_bp.get("/push/key")
@login_required
def push_key():
    _priv, pub = webpush.vapid_keys()
    db.session.commit()
    n = db.session.execute(select(func.count()).select_from(PushSubscription)
                           .where(PushSubscription.user_id == current_user.id)).scalar_one()
    return jsonify({"public_key": pub, "devices": n})


@api_bp.post("/push/subscribe")
@write_endpoint
def push_subscribe():
    data = request.get_json(silent=True) or {}
    endpoint = (data.get("endpoint") or "").strip()
    keys = data.get("keys") or {}
    if not endpoint.startswith("https://") or not keys.get("p256dh") or not keys.get("auth"):
        raise ApiError("validation", 400, details={"reason": "endpoint and keys required"})
    try:
        if len(webpush.unb64u(keys["p256dh"])) != 65 or len(webpush.unb64u(keys["auth"])) < 16:
            raise ValueError
    except (ValueError, TypeError):
        raise ApiError("validation", 400, details={"field": "keys", "reason": "invalid"})
    sub = db.session.scalars(select(PushSubscription).where(PushSubscription.endpoint == endpoint)).first()
    if sub is None:
        sub = PushSubscription(endpoint=endpoint, user_id=current_user.id, p256dh=keys["p256dh"], auth=keys["auth"])
        db.session.add(sub)
    else:   # the same browser now belongs to whoever signed in on it
        sub.user_id, sub.p256dh, sub.auth = current_user.id, keys["p256dh"], keys["auth"]
    sub.user_agent = (request.headers.get("User-Agent") or "")[:300]
    db.session.flush()
    return {"ok": True}, 200


@api_bp.post("/push/unsubscribe")
@write_endpoint
def push_unsubscribe():
    data = request.get_json(silent=True) or {}
    n = 0
    for sub in db.session.scalars(select(PushSubscription).where(PushSubscription.endpoint == (data.get("endpoint") or ""),
                                                                 PushSubscription.user_id == current_user.id)):
        db.session.delete(sub)
        n += 1
    return {"removed": n}, 200


@api_bp.post("/push/test")
@write_endpoint
def push_test():
    r = webpush.push_to_user(current_user.id, "تجربة الإشعارات", "إذا ظهر هذا التنبيه فالإشعارات تعمل على جهازك.", "#/home")
    return r, 200
