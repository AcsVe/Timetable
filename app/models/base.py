"""Shared base for every editable table (ERD §1).

Every SyncMixin row carries what offline editing (level 2) will need later:
client-generatable UUIDv7 ids, an optimistic-lock `version`, a global
monotonically increasing `change_seq` for delta sync, and a soft-delete
tombstone (`deleted_at`).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal

import uuid6
from flask import has_request_context
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Sequence, event, func, inspect
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, Session, declared_attr, mapped_column, with_loader_criteria

from app.extensions import db

global_change_seq = Sequence("global_change_seq", metadata=db.metadata)

# Columns managed by the server; never writable through the API.
SYSTEM_COLUMNS = frozenset(
    {"created_at", "updated_at", "version", "change_seq", "deleted_at", "created_by", "updated_by"}
)


def new_id() -> uuid.UUID:
    return uuid.UUID(bytes=uuid6.uuid7().bytes)


def utcnow() -> datetime:
    from datetime import timezone

    return datetime.now(timezone.utc)


class SyncMixin:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    change_seq: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=global_change_seq.next_value(), index=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @declared_attr
    def created_by(cls) -> Mapped[uuid.UUID | None]:
        return mapped_column(UUID(as_uuid=True), ForeignKey("app_user.id", use_alter=True))

    @declared_attr
    def updated_by(cls) -> Mapped[uuid.UUID | None]:
        return mapped_column(UUID(as_uuid=True), ForeignKey("app_user.id", use_alter=True))

    @declared_attr.directive
    def __mapper_args__(cls):
        # SQLAlchemy increments `version` and adds `WHERE version = :old` on every UPDATE.
        return {"version_id_col": cls.version}

    # -- helpers -------------------------------------------------------
    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def soft_delete(self) -> None:
        self.deleted_at = utcnow()

    def to_dict(self, exclude: frozenset[str] = frozenset()) -> dict:
        out = {}
        for col in inspect(self).mapper.column_attrs:
            if col.key in exclude:
                continue
            out[col.key] = jsonable(getattr(self, col.key))
        return out


def jsonable(v):
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, (datetime, date, time)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    if hasattr(v, "lower") and hasattr(v, "upper") and hasattr(v, "bounds"):  # Range
        return [v.lower, v.upper]
    return v


# ---------------------------------------------------------------------------
# Session events
# ---------------------------------------------------------------------------
@event.listens_for(Session, "do_orm_execute")
def _hide_soft_deleted(state):
    """Soft-deleted rows are invisible unless execution_options(include_deleted=True)."""
    if (
        state.is_select
        and not state.is_column_load
        and not state.execution_options.get("include_deleted", False)
    ):
        state.statement = state.statement.options(
            with_loader_criteria(SyncMixin, lambda cls: cls.deleted_at.is_(None), include_aliases=True)
        )


def _current_user_id():
    if not has_request_context():
        return None
    try:
        from flask_login import current_user

        if current_user and current_user.is_authenticated:
            return current_user.id
    except Exception:  # pragma: no cover
        return None
    return None


@event.listens_for(Session, "before_flush")
def _stamp_rows(session, flush_context, instances):
    from app.models.users import AuditLog

    uid = _current_user_id()
    audit = []
    for obj in list(session.new):
        if isinstance(obj, SyncMixin):
            if obj.id is None:
                obj.id = new_id()
            if obj.version is None:
                obj.version = 1
            if uid and obj.created_by is None:
                obj.created_by = uid
                obj.updated_by = uid
            audit.append((obj, "create"))
    for obj in list(session.dirty):
        if isinstance(obj, SyncMixin) and session.is_modified(obj, include_collections=True):
            # A new change_seq on every change, including child-collection-only changes,
            # so the parent row is re-sent by /api/sync and its version bumps.
            obj.change_seq = global_change_seq.next_value()
            if uid:
                obj.updated_by = uid
            hist = inspect(obj).attrs.deleted_at.history
            action = "delete" if hist.added and hist.added[0] is not None else "update"
            audit.append((obj, action))
    for obj, action in audit:
        diff = {}
        state = inspect(obj)
        for attr in state.mapper.column_attrs:
            if attr.key in SYSTEM_COLUMNS:
                continue
            h = state.attrs[attr.key].history
            if action == "create" or h.has_changes():
                new = h.added[0] if h.added else getattr(obj, attr.key)
                old = h.deleted[0] if h.deleted else None
                if action == "create":
                    diff[attr.key] = jsonable(new)
                else:
                    diff[attr.key] = [jsonable(old), jsonable(new)]
        session.add(
            AuditLog(
                user_id=uid,
                entity_type=obj.__tablename__,
                entity_id=obj.id,
                action=action,
                diff=diff,
                idempotency_key=_current_idem_key(),
            )
        )


def _current_idem_key():
    if not has_request_context():
        return None
    from flask import g

    return getattr(g, "idempotency_key", None)
