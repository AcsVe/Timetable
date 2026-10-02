"""Teacher absences and cover (substitution) for the lessons they miss (ERD §8).

An absence covers whole days, or a range of periods on each of its days. For every placed lesson of
an absent teacher on such a day a `Substitution` row records what happens to that period: covered by
another teacher, merged with another class, cancelled, or no cover needed (a co-teacher is present).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.base import SyncMixin
from app.models.core import enum, live_unique, uuid_fk

COVER_KINDS = ("cover", "merge", "cancel", "none")


class TeacherAbsence(SyncMixin, db.Model):
    __tablename__ = "teacher_absence"
    teacher_id: Mapped[uuid.UUID] = uuid_fk("teacher.id")
    date_from: Mapped[date] = mapped_column(Date, nullable=False)
    date_to: Mapped[date] = mapped_column(Date, nullable=False)
    period_from: Mapped[int | None] = mapped_column(Integer)   # NULL = the whole day
    period_to: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)            # from the school's own list (module:cover)
    note: Mapped[str | None] = mapped_column(Text)
    extra = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    __table_args__ = (
        CheckConstraint("date_to >= date_from", name="absence_dates"),
        CheckConstraint("(period_from IS NULL) = (period_to IS NULL)", name="absence_periods_pair"),
        CheckConstraint("period_from IS NULL OR (period_from >= 1 AND period_to >= period_from)", name="absence_periods"),
        Index("ix_teacher_absence_dates", "date_from", "date_to"),
    )

    def covers(self, d: date, period: int) -> bool:
        if not (self.date_from <= d <= self.date_to):
            return False
        return self.period_from is None or self.period_from <= period <= self.period_to


class Substitution(SyncMixin, db.Model):
    __tablename__ = "substitution"
    timetable_id: Mapped[uuid.UUID] = uuid_fk("timetable.id")
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    card_id: Mapped[uuid.UUID] = uuid_fk("card.id")
    period_no: Mapped[int] = mapped_column(Integer, nullable=False)
    original_teacher_id: Mapped[uuid.UUID] = uuid_fk("teacher.id")
    substitute_teacher_id: Mapped[uuid.UUID | None] = uuid_fk("teacher.id", nullable=True)
    kind: Mapped[str] = mapped_column(enum(*COVER_KINDS, name="cover_kind"), nullable=False, default="cover")
    room_id: Mapped[uuid.UUID | None] = uuid_fk("room.id", nullable=True)
    note: Mapped[str | None] = mapped_column(Text)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auto: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False, server_default=text("false"))
    __table_args__ = (
        live_unique("uq_substitution_slot_live", "date", "card_id", "period_no", "original_teacher_id"),
        CheckConstraint("kind <> 'cover' OR substitute_teacher_id IS NOT NULL", name="cover_needs_teacher"),
        CheckConstraint("period_no >= 1", name="substitution_period_pos"),
    )
