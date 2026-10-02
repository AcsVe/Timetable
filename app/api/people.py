"""Students: move several to another section at once (groups follow the gender)."""
from __future__ import annotations

from flask import request
from flask_login import current_user
from sqlalchemy import select

from app.api import api_bp
from app.api.crud import check_version
from app.api.idempotency import write_endpoint
from app.api.serialize import parse_uuid
from app.auth.permissions import require_write
from app.errors import ApiError
from app.extensions import db
from app.importing.apply import Importer, recount_students
from app.importing.text import norm
from app.models import Division, Section, Student, StudentGroup


def gender_groups(section_id, gender) -> list:
    if not gender:
        return []
    words = {norm(w) for w in Importer.GENDER_GROUPS[gender]}
    out = []
    for d in db.session.scalars(select(Division).where(Division.section_id == section_id)):
        g = next((g for g in db.session.scalars(select(StudentGroup).where(StudentGroup.division_id == d.id))
                  if norm(g.name_ar) in words), None)
        if g is not None:
            out.append(g.id)
    return out


@api_bp.post("/students/move")
@write_endpoint
def move_students():
    data = request.get_json(silent=True) or {}
    target = db.session.get(Section, parse_uuid(data.get("section_id"), "section_id"))
    items = data.get("items")
    if target is None or not isinstance(items, list) or not items:
        raise ApiError("validation", 400, details={"reason": "section_id and items required"})
    touched = {target.id}
    n = 0
    for it in items:
        st = db.session.get(Student, parse_uuid((it or {}).get("id")))
        if st is None:
            raise ApiError("not_found", 404)
        require_write(current_user, st)
        check_version(st, it.get("version"))
        if st.section_id == target.id:
            continue
        touched.add(st.section_id)
        st.section_id = target.id
        st.group_ids = gender_groups(target.id, st.gender)
        require_write(current_user, st)
        n += 1
    db.session.flush()
    recount_students(touched)
    return {"moved": n}, 200
