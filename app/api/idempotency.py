"""Every write goes through @write_endpoint:

* requires an `Idempotency-Key` (UUID) header; a retried request with the same
  key returns the stored response and is never applied twice,
* runs the view in one transaction together with the stored response,
* turns ApiError / database IntegrityError into bilingual JSON errors.

Views return (payload: dict, status: int) and must NOT commit.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import timedelta
from functools import wraps

from flask import current_app, g, jsonify, request
from flask_login import current_user, login_required
from psycopg import errors as pgerr
from sqlalchemy.exc import IntegrityError

from app.errors import ApiError
from app.extensions import db
from app.models import IdempotencyKey
from app.models.base import utcnow


def integrity_to_api_error(exc: IntegrityError) -> ApiError:
    orig = exc.orig
    name = getattr(getattr(orig, "diag", None), "constraint_name", None) or ""
    if isinstance(orig, pgerr.ExclusionViolation) or name == "ex_occupancy_no_overlap":
        return ApiError("placement_conflict", 409, details=[{"code": "db_guard", "constraint": name}])
    if isinstance(orig, pgerr.UniqueViolation):
        return ApiError("duplicate", 409, details={"constraint": name})
    if isinstance(orig, pgerr.ForeignKeyViolation):
        return ApiError("validation", 400, details={"constraint": name, "reason": "unknown_reference"})
    return ApiError("integrity", 400, details={"constraint": name})


def _request_hash() -> str:
    h = hashlib.sha256()
    h.update(request.method.encode())
    h.update(b"\n")
    h.update(request.full_path.encode())
    h.update(b"\n")
    h.update(request.get_data() or b"")
    return h.hexdigest()


def write_endpoint(fn):
    @wraps(fn)
    @login_required
    def wrapper(*args, **kwargs):
        raw = request.headers.get("Idempotency-Key", "")
        try:
            key = uuid.UUID(raw)
        except ValueError:
            return ApiError("idempotency_key_required", 400).response()
        g.idempotency_key = key
        req_hash = _request_hash()

        existing = db.session.get(IdempotencyKey, key)
        if existing is not None:
            if existing.user_id != current_user.id or existing.request_hash != req_hash:
                return ApiError("idempotency_key_reused", 422).response()
            resp = jsonify(existing.response_body)
            resp.status_code = existing.status_code
            resp.headers["Idempotent-Replayed"] = "true"
            return resp

        try:
            payload, status = fn(*args, **kwargs)
            db.session.flush()
        except ApiError as e:
            db.session.rollback()
            payload, status = e.body(), e.status
        except IntegrityError as e:
            db.session.rollback()
            err = integrity_to_api_error(e)
            payload, status = err.body(), err.status

        if status >= 500:  # pragma: no cover - never cache server errors
            db.session.rollback()
            return jsonify(payload), status

        db.session.add(
            IdempotencyKey(
                key=key,
                user_id=current_user.id,
                method=request.method,
                path=request.path,
                request_hash=req_hash,
                status_code=status,
                response_body=payload,
                expires_at=utcnow() + timedelta(days=current_app.config["IDEMPOTENCY_TTL_DAYS"]),
            )
        )
        try:
            db.session.commit()
        except IntegrityError as e:
            db.session.rollback()
            if isinstance(e.orig, pgerr.UniqueViolation) and "idempotency_key" in str(e.orig):
                return ApiError("idempotency_in_progress", 409).response()
            err = integrity_to_api_error(e)
            return err.response()
        return jsonify(payload), status

    return wrapper
