"""Send one prepared message per teacher: e-mail (Microsoft Graph) and/or an in-app notice for teachers
who have a user account. Every e-mail attempt is written to email_log."""
from __future__ import annotations

import uuid
from html import escape

from flask import has_request_context, request
from flask_login import current_user
from sqlalchemy import select

from app.extensions import db
from app.models import AppUser, EmailLog, Notification, School, Teacher
from app.models.base import utcnow
from app.notify import graph


def _school_name() -> str:
    s = db.session.scalars(select(School)).first()
    return s.name_ar if s else ""


def render_html(title: str, text: str, link: str | None) -> str:
    school = escape(_school_name())
    lines = "".join(f"<p style='margin:4px 0'>{escape(line) or '&nbsp;'}</p>" for line in text.split("\n"))
    button = (f"<p style='margin-top:16px'><a href='{escape(link)}' style='background:#1f4e8c;color:#fff;padding:8px 16px;"
              f"border-radius:6px;text-decoration:none'>فتح في نظام الجدولة</a></p>") if link else ""
    return (f"<div dir='rtl' style='font-family:Tahoma,Arial,sans-serif;font-size:14px;color:#111;line-height:1.6'>"
            f"<div style='font-weight:bold;font-size:16px'>{school}</div>"
            f"<div style='font-weight:bold;margin:6px 0 10px'>{escape(title)}</div>{lines}{button}"
            f"<p style='color:#777;font-size:12px;margin-top:18px'>رسالة آلية من نظام جدولة الحصص؛ لا حاجة إلى الرد عليها.</p></div>")


def deliver(messages: list[dict], *, kind: str, title: str, title_en: str, url: str | None,
            email: bool = True, in_app: bool = True) -> dict:
    """messages: [{"teacher_id", "name", "text"}]. Returns per-teacher results and totals."""
    settings = graph.load_settings()
    can_mail = email and graph.is_configured(settings)
    base = request.host_url.rstrip("/") + "/" if has_request_context() else ""
    link = f"{base}{url}" if (base and url) else None
    sender_id = current_user.id if has_request_context() and current_user.is_authenticated else None
    fatal = None   # a sign-in failure stops the batch: every other message would fail the same way
    results = []
    for m in messages:
        t = db.session.get(Teacher, uuid.UUID(str(m["teacher_id"])))
        user = db.session.get(AppUser, t.user_id) if t and t.user_id else None
        address = (t.email if t and t.email else None) or (user.email if user else None)
        r = {"teacher_id": str(m["teacher_id"]), "name": m["name"], "email": address, "email_status": None,
             "error": None, "in_app": False}
        if in_app and user is not None:
            db.session.add(Notification(user_id=user.id, kind=kind, title_ar=title, title_en=title_en,
                                        body={"text": m["text"]}, url=url))
            r["in_app"] = True
        if email:
            if not can_mail:
                r["email_status"] = "disabled"
            elif not address or not graph.EMAIL_RE.match(address):
                r["email_status"] = "no_email"
            elif fatal:
                r["email_status"], r["error"] = "failed", fatal
            else:
                try:
                    graph.send_mail(settings, address, title, render_html(title, m["text"], link), m["name"])
                    r["email_status"] = "sent"
                except graph.GraphError as e:
                    r["email_status"], r["error"] = "failed", str(e)
                    if "رمز الدخول" in str(e) or "تعذّر الاتصال" in str(e):
                        fatal = str(e)
                db.session.add(EmailLog(to_address=address, to_name=m["name"], subject=title, kind=kind,
                                        status="sent" if r["email_status"] == "sent" else "failed",
                                        error=r["error"], sent_by=sender_id))
        results.append(r)
    db.session.flush()
    count = lambda st: sum(1 for r in results if r["email_status"] == st)  # noqa: E731
    return {"results": results, "teachers": len(results), "sent": count("sent"), "failed": count("failed"),
            "no_email": count("no_email"), "in_app": sum(1 for r in results if r["in_app"]),
            "mail_configured": graph.is_configured(settings), "at": utcnow().isoformat()}
