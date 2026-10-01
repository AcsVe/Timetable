"""Exam timetable with invigilation, and the teachers' duty roster (per term).

Both are deliberately flexible: list values (duty purposes, locations, floors, corridors…) and the
labels and extra fields of each screen are configured by the school in `app_setting` under the keys
"module:exams" / "module:duties"; the values of extra fields live in the `extra` JSON of each row.
"""
from __future__ import annotations

import uuid
from datetime import date, time

from sqlalchemy import Date, Index, Integer, Text, Time, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.base import SyncMixin
from app.models.core import uuid_fk


class ExamSession(SyncMixin, db.Model):
    """One exam sitting: a subject (or a free title) for a stage / grades, on a date and time,
    held in one or more rooms, each with its location, sections and invigilating teachers.

    rooms = [{"room_id": uuid|null, "location": "المبنى أ › الطابق الأول", "section_ids": [...],
              "teacher_ids": [...], "extra": {...}}]"""

    __tablename__ = "exam_session"
    term_id: Mapped[uuid.UUID] = uuid_fk("term.id")
    exam_date: Mapped[date] = mapped_column(Date, nullable=False)
    starts_at: Mapped[time | None] = mapped_column(Time)
    ends_at: Mapped[time | None] = mapped_column(Time)
    session_label: Mapped[str | None] = mapped_column(Text)        # e.g. «الجلسة الأولى»
    stage_id: Mapped[uuid.UUID | None] = uuid_fk("stage.id", nullable=True)
    grade_ids = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, server_default=text("'{}'"))
    subject_id: Mapped[uuid.UUID | None] = uuid_fk("subject.id", nullable=True)
    title: Mapped[str | None] = mapped_column(Text)                # used when there is no subject
    rooms = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    notes: Mapped[str | None] = mapped_column(Text)
    extra = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    __table_args__ = (Index("ix_exam_session_term_date", "term_id", "exam_date"),)


class DutyAssignment(SyncMixin, db.Model):
    """One duty slot: who supervises what, where and when (e.g. the morning queue, the first break
    in the east corridor of the first floor, the students' dismissal)."""

    __tablename__ = "duty_assignment"
    term_id: Mapped[uuid.UUID] = uuid_fk("term.id")
    weekday_id: Mapped[uuid.UUID | None] = uuid_fk("weekday.id", nullable=True)   # NULL = every school day
    duty_type: Mapped[str] = mapped_column(Text, nullable=False)                   # الغاية / السبب
    location: Mapped[str | None] = mapped_column(Text)                             # «الطابق الأول › الممر الشرقي»
    stage_id: Mapped[uuid.UUID | None] = uuid_fk("stage.id", nullable=True)
    time_label: Mapped[str | None] = mapped_column(Text)                           # «الاستراحة الأولى»
    starts_at: Mapped[time | None] = mapped_column(Time)
    ends_at: Mapped[time | None] = mapped_column(Time)
    teacher_ids = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, server_default=text("'{}'"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text)
    extra = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    __table_args__ = (Index("ix_duty_assignment_term_day", "term_id", "weekday_id"),)
