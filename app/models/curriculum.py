"""The study plan (الخطة الدراسية): how many periods a week each grade must have of each subject.
The timetable's lessons are checked against it, and missing lessons can be created from it."""
from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.base import SyncMixin
from app.models.core import live_unique, uuid_fk


class CurriculumItem(SyncMixin, db.Model):
    __tablename__ = "curriculum_item"
    grade_id: Mapped[uuid.UUID] = uuid_fk("grade.id")
    subject_id: Mapped[uuid.UUID] = uuid_fk("subject.id")
    periods_per_week: Mapped[int] = mapped_column(Integer, nullable=False)
    duration: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")  # 2 = taught in double periods
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        live_unique("uq_curriculum_live", "grade_id", "subject_id"),
        CheckConstraint("periods_per_week BETWEEN 1 AND 40", name="curriculum_ppw_range"),
        CheckConstraint("duration BETWEEN 1 AND 4", name="curriculum_duration_range"),
    )
