"""Students (by section) and the e-mail log."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.base import SyncMixin, new_id, utcnow
from app.models.core import enum, live_unique, uuid_fk


class Student(SyncMixin, db.Model):
    __tablename__ = "student"
    section_id: Mapped[uuid.UUID] = uuid_fk("section.id")
    student_no: Mapped[str | None] = mapped_column(String(40))      # school / ministry number, used to match on re-import
    name_ar: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str | None] = mapped_column(Text)
    gender: Mapped[str | None] = mapped_column(enum("m", "f", name="gender"))
    group_ids = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, server_default=text("'{}'"))
    guardian_phone: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    extra = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    __table_args__ = (
        live_unique("uq_student_no_live", "student_no", where=text("student_no IS NOT NULL AND deleted_at IS NULL")),
    )


class EmailLog(db.Model):
    """Every e-mail the system tried to send (append only)."""

    __tablename__ = "email_log"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    to_address: Mapped[str] = mapped_column(Text, nullable=False)
    to_name: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)          # cover / exams / duties / test
    status: Mapped[str] = mapped_column(enum("sent", "failed", name="mail_status"), nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    sent_by: Mapped[uuid.UUID | None] = uuid_fk("app_user.id", nullable=True, index=False, ondelete="SET NULL")
    __table_args__ = (Index("ix_email_log_kind", "kind"),)
