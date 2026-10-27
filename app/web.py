from flask import Blueprint, current_app, render_template, send_from_directory
from flask_login import login_required

web_bp = Blueprint("web", __name__)

# Bump when static assets change so the service worker refreshes its cache.
ASSET_VERSION = "2026.10.26-1"


@web_bp.app_context_processor
def _shell_context():
    """For the pages shown before sign-in: the school's name and logo (the system icon until one is uploaded)."""
    def school_brand() -> dict:
        from sqlalchemy import select

        from app.extensions import db
        from app.models import School
        try:
            school = db.session.scalars(select(School)).first()
        except Exception:   # an empty database before its first migration: show the system's own name
            db.session.rollback()
            school = None
        name_ar = (school.name_ar if school else None) or "جدولة الحصص"
        name_en = (school.name_en if school else None) or (name_ar if school else "School Timetable")
        return {"name_ar": name_ar, "name_en": name_en, "logo": school.logo_path if school else None}

    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        year = datetime.now(ZoneInfo("Asia/Amman")).year
    except Exception:   # no time-zone data on this machine
        year = datetime.now().year
    return {"asset_version": ASSET_VERSION, "school_brand": school_brand, "now_year": year}


@web_bp.get("/")
@login_required
def index():
    """Single-page admin shell; views are rendered client-side (hash router)."""
    return render_template("app.html", asset_version=ASSET_VERSION)


@web_bp.get("/sw.js")
def service_worker():
    # Served from the site root so its scope covers the whole site.
    resp = send_from_directory(current_app.static_folder, "sw.js", mimetype="application/javascript", max_age=0)
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@web_bp.get("/manifest.webmanifest")
def manifest():
    return send_from_directory(current_app.static_folder, "manifest.webmanifest",
                               mimetype="application/manifest+json", max_age=3600)


@web_bp.get("/school-logo")
def school_logo():
    """Uploaded school logo (public: it also appears on the login page and printed reports)."""
    from flask import Response, abort
    from sqlalchemy import select
    from sqlalchemy.orm import undefer

    from app.extensions import db
    from app.models import School

    school = db.session.scalars(select(School).options(undefer(School.logo_data))).first()
    if school is None or not school.logo_data:
        abort(404)
    resp = Response(bytes(school.logo_data), mimetype=school.logo_mime or "image/png")
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@web_bp.get("/offline")
def offline():
    return render_template("offline.html")
