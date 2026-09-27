from flask import Blueprint, current_app, render_template, send_from_directory
from flask_login import login_required

web_bp = Blueprint("web", __name__)

# Bump when static assets change so the service worker refreshes its cache.
ASSET_VERSION = "2026.09.27-2"


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


@web_bp.get("/offline")
def offline():
    return render_template("offline.html")
