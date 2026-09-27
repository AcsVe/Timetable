"""Users, roles, notifications and infrastructure tables (ERD §9)."""
from __future__ import annotations

import uuid
from datetime import datetime

from flask_login import UserMixin
from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String, Table, Text, text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.models.base import SyncMixin, new_id, utcnow
from app.models.core import enum, live_unique, uuid_fk

user_stage = Table(
    "user_stage",
    db.metadata,
    Column("user_id", UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True),
    Column("stage_id", UUID(as_uuid=True), ForeignKey("stage.id", ondelete="CASCADE"), primary_key=True),
)

ROLES = ("admin", "stage_editor", "viewer")


class AppUser(SyncMixin, UserMixin, db.Model):
    __tablename__ = "app_user"
    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(Text)
    ms_oid: Mapped[str | None] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(enum(*ROLES, name="user_role"), nullable=False, default="viewer")
    preferred_lang: Mapped[str] = mapped_column(enum("ar", "en", name="user_lang"), nullable=False, default="ar")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stages = relationship("Stage", secondary=user_stage)
    __table_args__ = (
        live_unique("uq_app_user_email_live", "email"),
        live_unique("uq_app_user_ms_oid_live", "ms_oid", where=text("ms_oid IS NOT NULL AND deleted_at IS NULL")),
    )

    def set_password(self, pw: str) -> None:
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw: str) -> bool:
        return bool(self.password_hash) and check_password_hash(self.password_hash, pw)

    @property
    def is_usable(self) -> bool:
        if not self.is_active or self.deleted_at is not None:
            return False
        return self.valid_until is None or self.valid_until > utcnow()

    @property
    def stage_ids(self) -> set[uuid.UUID]:
        return {s.id for s in self.stages}

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class PushSubscription(db.Model):
    __tablename__ = "push_subscription"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = uuid_fk("app_user.id", ondelete="CASCADE")
    endpoint: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    p256dh: Mapped[str] = mapped_column(Text, nullable=False)
    auth: Mapped[str] = mapped_column(Text, nullable=False)
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at = mapped_column(DateTime(timezone=True), default=utcnow)
    last_success_at = mapped_column(DateTime(timezone=True))


class Notification(db.Model):
    __tablename__ = "notification"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = uuid_fk("app_user.id", ondelete="CASCADE")
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title_ar: Mapped[str] = mapped_column(Text, nullable=False)
    title_en: Mapped[str | None] = mapped_column(Text)
    body = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    url: Mapped[str | None] = mapped_column(Text)
    created_at = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    read_at = mapped_column(DateTime(timezone=True))
    email_sent_at = mapped_column(DateTime(timezone=True))
    push_sent_at = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class AuditLog(db.Model):
    """Append-only: who changed what."""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    diff = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    idempotency_key: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class IdempotencyKey(db.Model):
    """Stored response for each mutating request so a retried request is never applied twice."""

    __tablename__ = "idempotency_key"
    key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = uuid_fk("app_user.id", ondelete="CASCADE")
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body = mapped_column(JSONB)
    created_at = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    expires_at = mapped_column(DateTime(timezone=True), nullable=False, index=True)
