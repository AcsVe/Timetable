"""Import endpoints: Excel template, preview (dry run, rolled back) and commit."""
from __future__ import annotations

from flask import Response, request
from flask_login import current_user, login_required

from app.api import api_bp
from app.api.idempotency import write_endpoint
from app.api.serialize import parse_uuid
from app.auth.permissions import require_admin
from app.errors import ApiError
from app.extensions import db

MAX_FILE = 20_000_000
KINDS = {"teachers", "subjects", "rooms", "sections", "lessons", "students"}


def _bundles():
    files = [f for f in request.files.getlist("file") if f and f.filename]
    if not files:
        raise ApiError("validation", 400, details={"field": "file", "reason": "required"},
                       message="اختر ملفاً للاستيراد", message_en="Choose a file to import")
    if len(files) > 5:
        raise ApiError("validation", 400, details={"field": "file", "reason": "too_many_files"},
                       message="يمكن استيراد خمسة ملفات على الأكثر دفعةً واحدة", message_en="At most five files at once")
    return [_bundle(f) for f in files]


def _bundle(f):
    data = f.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise ApiError("validation", 413, details={"reason": "file_too_large"},
                       message="حجم الملف أكبر من 20 ميغابايت", message_en="The file is larger than 20 MB")
    name = f.filename.lower()
    kind = request.form.get("kind") or None
    if kind and kind not in KINDS:
        raise ApiError("validation", 400, details={"field": "kind"})
    from app.importing import asc, tabular
    if name.endswith((".xml", ".roz")):
        return asc.parse_asc(data, name)
    if name.endswith((".xlsx", ".xlsm")) or (data[:2] == b"PK" and b"xl/" in data[:2000]):
        return tabular.parse_xlsx(data, kind)
    if name.endswith((".csv", ".txt", ".tsv")):
        return tabular.parse_csv(data, kind, f.filename)
    if name.endswith(".xls"):
        raise ApiError("validation", 400, details={"reason": "xls_not_supported"},
                       message="صيغة ‎.xls القديمة غير مدعومة؛ احفظ الملف في Excel بصيغة ‎.xlsx",
                       message_en="The old .xls format is not supported; save the file as .xlsx in Excel")
    raise ApiError("validation", 400, details={"reason": "unsupported_file"},
                   message="نوع الملف غير مدعوم. الأنواع المدعومة: ‎.xlsx و‎.csv و‎.xml و‎.roz (aSc)",
                   message_en="Unsupported file type. Supported: .xlsx, .csv, .xml and .roz (aSc)")


def _options() -> dict:
    form = request.form
    opt = lambda k: (form.get(k) or "").strip() or None  # noqa: E731
    out = {"stage_name": opt("stage_name"), "new_timetable_name": opt("new_timetable_name"),
           "replace_all": form.get("replace_all") in ("1", "true", "on")}
    for k in ("stage_id", "timetable_id", "term_id"):
        out[k] = parse_uuid(opt(k), k) if opt(k) else None
    return out


def _run():
    require_admin(current_user)
    from app.importing.apply import run_import
    return run_import(_bundles(), **_options())


@api_bp.get("/import/template.xlsx")
@login_required
def import_template():
    from app.importing.template import build_template
    resp = Response(build_template(),
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp.headers["Content-Disposition"] = ("attachment; filename=\"import-template.xlsx\"; "
                                           "filename*=UTF-8''%D9%82%D8%A7%D9%84%D8%A8-%D8%A7%D9%84%D8%A7%D8%B3%D8%AA%D9%8A%D8%B1%D8%A7%D8%AF.xlsx")
    return resp


@api_bp.post("/import/preview")
@login_required
def import_preview():
    """Runs the real import, reports what it did, then rolls everything back."""
    try:
        report = _run()
        report["committed"] = False
        return report, 200
    except ApiError:
        raise
    finally:
        db.session.rollback()


@api_bp.post("/import/commit")
@write_endpoint
def import_commit():
    report = _run()
    report["committed"] = True
    return report, 200
