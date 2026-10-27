from __future__ import annotations

import uuid

from flask import Blueprint, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import select

from app.errors import ApiError
from app.extensions import db, login_manager
from app.models import AppUser
from app.models.base import utcnow

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@login_manager.user_loader
def _load_user(user_id: str):
    try:
        user = db.session.get(AppUser, uuid.UUID(user_id))
    except ValueError:
        return None
    # Deactivated or expired (temporary substitute) accounts are logged out immediately.
    return user if user is not None and user.is_usable else None


@login_manager.unauthorized_handler
def _unauthorized():
    if request.path.startswith("/api/") or request.is_json:
        return ApiError("unauthorized", 401).response()
    return redirect(url_for("auth.login", next=request.path))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")
    data = request.get_json(silent=True) or request.form
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    user = db.session.scalars(select(AppUser).where(AppUser.email == email)).first()
    if user is None or not user.check_password(password) or not user.is_usable:
        if request.is_json:
            return jsonify(error="bad_credentials", message="البريد الإلكتروني أو كلمة المرور غير صحيحة، أو أن الحساب غير مفعّل",
                           message_en="Wrong email or password, or the account is inactive"), 401
        return render_template("login.html", error=True, email=email), 401
    user.last_login_at = utcnow()
    db.session.commit()
    login_user(user, remember=bool(data.get("remember")))
    if request.is_json:
        return jsonify(user=serialize_me(user))
    nxt = request.args.get("next") or "/"
    return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else "/")


@auth_bp.post("/logout")
@login_required
def logout():
    logout_user()
    if request.is_json:
        return jsonify(ok=True)
    return redirect(url_for("auth.login"))


@auth_bp.post("/me/password")
@login_required
def change_password():
    """The signed-in user changes their own password (the current one is required)."""
    data = request.get_json(silent=True) or {}
    current = data.get("current_password") or ""
    new = data.get("new_password") or ""
    if not current_user.check_password(current):
        return jsonify(error="bad_password", message="كلمة المرور الحالية غير صحيحة",
                       message_en="The current password is wrong"), 400
    if len(new) < 8:
        return jsonify(error="validation", message="كلمة المرور الجديدة ثمانية أحرف على الأقل",
                       message_en="The new password must be at least 8 characters"), 400
    user = db.session.get(AppUser, current_user.id)
    user.set_password(new)
    db.session.commit()
    return jsonify(ok=True)


def serialize_me(user: AppUser) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
        "preferred_lang": user.preferred_lang,
        "stage_ids": sorted(str(s) for s in user.stage_ids),
        "valid_until": user.valid_until.isoformat() if user.valid_until else None,
        "ui_prefs": user.ui_prefs or {},
    }


@auth_bp.get("/me")
@login_required
def me():
    return jsonify(user=serialize_me(current_user))


def _clean_nav(v) -> dict:
    """{"favorites": [route, …], "collapsed": [group, …]}: short strings only, no duplicates, bounded."""
    if not isinstance(v, dict):
        raise ApiError("validation", 400, details={"field": "nav"})
    out = {}
    for key, limit in (("favorites", 40), ("collapsed", 20)):
        items = v.get(key, [])
        if not isinstance(items, list) or not all(isinstance(x, str) and 0 < len(x) <= 80 for x in items):
            raise ApiError("validation", 400, details={"field": f"nav.{key}"})
        out[key] = list(dict.fromkeys(items))[:limit]
    return out


@auth_bp.put("/me/prefs")
@login_required
def save_prefs():
    """Personal screen settings (the side menu's favourites and collapsed groups). Saving the same value
    twice changes nothing, so no Idempotency-Key is needed; written with a plain UPDATE so a click on a
    menu group neither bumps the account's version nor fills the audit log."""
    from sqlalchemy import update
    data = request.get_json(silent=True) or {}
    prefs = dict(current_user.ui_prefs or {})
    if "nav" in data:
        try:
            prefs["nav"] = _clean_nav(data["nav"])
        except ApiError as e:       # this blueprint has no API error handler of its own
            return e.response()
    table = AppUser.__table__
    db.session.execute(update(table).where(table.c.id == current_user.id).values(ui_prefs=prefs))
    db.session.commit()
    return jsonify(ui_prefs=prefs)
