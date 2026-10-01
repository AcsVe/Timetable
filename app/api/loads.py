"""Weekly-load status of every teacher under the school's conditional load rules."""
from __future__ import annotations

from flask import jsonify
from flask_login import login_required

from app.api import api_bp
from app.api.serialize import parse_uuid
from app.errors import ApiError
from app.extensions import db
from app.models import Timetable
from app.rules.loads import evaluate


@api_bp.get("/timetables/<tt_id>/load-status")
@login_required
def load_status(tt_id):
    tt = db.session.get(Timetable, parse_uuid(tt_id))
    if tt is None:
        raise ApiError("not_found", 404)
    return jsonify(evaluate(tt))
