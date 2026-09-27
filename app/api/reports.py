"""Reports (JSON preview / Excel / PDF) and school logo upload."""
from __future__ import annotations

import uuid

from flask import Response, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import select

from app.api import api_bp
from app.api.idempotency import write_endpoint
from app.api.serialize import parse_uuid
from app.auth.permissions import require_admin
from app.errors import ApiError
from app.extensions import db
from app.models import School, Timetable
from app.reports.data import KINDS, build_report, parse_filters
from app.reports.logo import logo_bytes

MIME = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}
LOGO_TYPES = {"image/png": "png", "image/jpeg": "jpg"}
MAX_LOGO = 1_000_000


@api_bp.get("/timetables/<tt_id>/reports/<kind>")
@login_required
def report(tt_id, kind):
    if kind not in KINDS:
        raise ApiError("not_found", 404)
    tt = db.session.get(Timetable, parse_uuid(tt_id))
    if tt is None:
        raise ApiError("not_found", 404)
    fmt = request.args.get("format", "json")
    lang = "en" if request.args.get("lang") == "en" else "ar"
    try:
        filters = parse_filters(request.args)
    except ValueError:
        raise ApiError("validation", 400, details={"reason": "invalid filter id"})
    rep = build_report(tt, kind, lang, filters, request.args.get("layout", "rows"))
    if fmt == "json":
        return jsonify(rep.to_json())
    if fmt not in MIME:
        raise ApiError("validation", 400, details={"field": "format", "reason": "json | xlsx | pdf"})
    logo = logo_bytes()
    if fmt == "xlsx":
        from app.reports.xlsx import render_xlsx
        data = render_xlsx(rep, logo)
    else:
        from app.reports.pdf import render_pdf
        data = render_pdf(rep, logo)
    filename = f"{rep.title} - {tt.name}.{fmt}".replace("/", "-")
    resp = Response(data, mimetype=MIME[fmt])
    from urllib.parse import quote
    ascii_name = f"report-{kind}.{fmt}"
    resp.headers["Content-Disposition"] = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _school() -> School:
    school = db.session.scalars(select(School)).first()
    if school is None:
        raise ApiError("validation", 400, details={"reason": "save the school name first",
                                                     "message": "احفظ اسم المدرسة أولاً، ثم ارفع الشعار"})
    return school


@api_bp.post("/school/logo")
@write_endpoint
def upload_logo():
    require_admin(current_user)
    f = request.files.get("file")
    if f is None:
        raise ApiError("validation", 400, details={"field": "file", "reason": "required"})
    data = f.read(MAX_LOGO + 1)
    if len(data) > MAX_LOGO:
        raise ApiError("validation", 400, details={"field": "file", "message": "حجم الشعار يتجاوز 1 ميغابايت"})
    mime = f.mimetype
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        mime = "image/png"
    elif data[:3] == b"\xff\xd8\xff":
        mime = "image/jpeg"
    if mime not in LOGO_TYPES:
        raise ApiError("validation", 400, details={"field": "file", "message": "يُقبل الشعار بصيغة PNG أو JPEG فقط"})
    school = _school()
    school.logo_data = data
    school.logo_mime = mime
    school.logo_path = f"/school-logo?v={uuid.uuid4().hex[:8]}"
    db.session.flush()
    db.session.refresh(school)
    return {"logo_path": school.logo_path, "version": school.version}, 200


@api_bp.delete("/school/logo")
@write_endpoint
def delete_logo():
    require_admin(current_user)
    school = _school()
    school.logo_data = None
    school.logo_mime = None
    school.logo_path = None
    db.session.flush()
    db.session.refresh(school)
    return {"logo_path": None, "version": school.version}, 200
