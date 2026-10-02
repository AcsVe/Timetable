"""E-mail through Microsoft Graph: settings (admin), connection test, log."""
from __future__ import annotations

from flask import jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import select

from app.api import api_bp
from app.api.idempotency import write_endpoint
from app.auth.permissions import require_admin
from app.errors import ApiError
from app.extensions import db
from app.models import EmailLog
from app.notify import graph


@api_bp.get("/mail/status")
@login_required
def mail_status():
    return jsonify({"configured": graph.is_configured()})


@api_bp.get("/mail/settings")
@login_required
def mail_settings():
    require_admin(current_user)
    return jsonify(graph.public_settings())


@api_bp.put("/mail/settings")
@write_endpoint
def save_mail_settings():
    require_admin(current_user)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("validation", 400, details={"reason": "json object required"})
    return graph.save_settings(data), 200


@api_bp.post("/mail/test")
@write_endpoint
def mail_test():
    """Sign in to Microsoft and send a test message; the result (or the exact Microsoft error) is returned."""
    from app.notify.deliver import render_html
    require_admin(current_user)
    data = request.get_json(silent=True) or {}
    to = (data.get("to") or current_user.email or "").strip()
    if not graph.EMAIL_RE.match(to):
        raise ApiError("validation", 400, details={"field": "to", "message": "اكتب بريداً صالحاً لاستلام رسالة التجربة"})
    s = graph.load_settings()
    if not graph.is_configured(s):
        raise ApiError("validation", 400, details={"message": "أكمل إعدادات البريد أولاً: معرّف المستأجر، ومعرّف التطبيق، والسر، وبريد المرسل"})
    title = "رسالة تجربة من نظام جدولة الحصص"
    try:
        graph.send_mail(s, to, title, render_html(title, "إذا وصلتك هذه الرسالة فإعدادات البريد عبر Microsoft 365 تعمل بنجاح.", None))
        ok, err = True, None
    except graph.GraphError as e:
        ok, err = False, str(e)
    db.session.add(EmailLog(to_address=to, subject=title, kind="test", status="sent" if ok else "failed", error=err,
                            sent_by=current_user.id))
    return {"ok": ok, "to": to, "error": err}, 200


@api_bp.get("/mail/log")
@login_required
def mail_log():
    require_admin(current_user)
    rows = db.session.scalars(select(EmailLog).order_by(EmailLog.created_at.desc()).limit(200)).all()
    return jsonify({"items": [{"id": str(r.id), "at": r.created_at.isoformat(), "to": r.to_address, "name": r.to_name,
                               "subject": r.subject, "kind": r.kind, "status": r.status, "error": r.error} for r in rows]})
