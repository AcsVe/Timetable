"""Coercion of JSON input into column values, driven by the column types."""
from __future__ import annotations

import uuid
from datetime import date, datetime, time

from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from app.errors import ApiError


def _bad(field: str, reason: str):
    return ApiError("validation", 400, details={"field": field, "reason": reason})


def coerce(col, field: str, value):
    if value is None:
        if not col.nullable and col.default is None and col.server_default is None:
            raise _bad(field, "required")
        return None
    t = col.type
    if isinstance(t, SAEnum):
        if value not in t.enums:
            raise _bad(field, f"must be one of {list(t.enums)}")
        return value
    if isinstance(t, JSONB):
        return value
    if isinstance(t, ARRAY):
        if not isinstance(value, list):
            raise _bad(field, "must be a list")
        try:
            return [uuid.UUID(str(v)) for v in value]
        except ValueError:
            raise _bad(field, "must be a list of UUIDs")
    try:
        py = t.python_type
    except NotImplementedError:  # pragma: no cover
        return value
    try:
        if py is uuid.UUID:
            return uuid.UUID(str(value))
        if py is bool:
            if not isinstance(value, bool):
                raise ValueError
            return value
        if py is int:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError
            return value
        if py is datetime:
            return datetime.fromisoformat(value)
        if py is date:
            return date.fromisoformat(value)
        if py is time:
            return time.fromisoformat(value)
        if py is str:
            if not isinstance(value, str):
                raise ValueError
            value = value.strip()
            if not value and not col.nullable:
                raise _bad(field, "required")
            if getattr(t, "length", None) and len(value) > t.length:
                raise _bad(field, f"max length {t.length}")
            return value or None
    except ApiError:
        raise
    except (ValueError, TypeError):
        raise _bad(field, f"invalid {py.__name__}")
    return value


def parse_uuid(value, field: str = "id") -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise _bad(field, "invalid uuid")


def parse_uuid_list(value, field: str) -> list[uuid.UUID]:
    if not isinstance(value, list):
        raise _bad(field, "must be a list")
    return [parse_uuid(v, field) for v in value]


def require_int(data: dict, field: str, minimum: int | None = None) -> int:
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise _bad(field, "required integer")
    if minimum is not None and v < minimum:
        raise _bad(field, f"must be >= {minimum}")
    return v
