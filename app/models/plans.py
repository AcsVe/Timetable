"""Holiday calendar and period plans (منشئ الخطط).

A Holiday stops lessons on its dates (for every stage, or the stages listed). A PeriodPlan holds, for
one term (and optionally one stage), how many periods of each subject each grade must receive in each
period of the term — the whole term, each month, each week or each day — so the timetable, the
absences and the teachers' loads can be compared with it."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.base import SyncMixin
from app.models.core import enum, uuid_fk

HOLIDAY_KINDS = ("official", "term_break", "exams", "activity", "other")
PERIOD_TYPES = ("term", "month", "week", "day")


class Holiday(SyncMixin, db.Model):
    __tablename__ = "holiday"
    name_ar: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str | None] = mapped_column(Text)
    date_from: Mapped[date] = mapped_column(Date, nullable=False)
    date_to: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[str] = mapped_column(enum(*HOLIDAY_KINDS, name="holiday_kind"), nullable=False, default="official",
                                      server_default="official")
    stage_ids = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, server_default=text("'{}'"))   # empty = every stage
    stops_lessons: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (CheckConstraint("date_to >= date_from", name="holiday_dates"),)

    def applies(self, d: date, stage_id: uuid.UUID | None) -> bool:
        return (self.stops_lessons and self.date_from <= d <= self.date_to
                and (not self.stage_ids or (stage_id is not None and stage_id in self.stage_ids)))


class PeriodPlan(SyncMixin, db.Model):
    __tablename__ = "period_plan"
    name: Mapped[str] = mapped_column(Text, nullable=False)
    term_id: Mapped[uuid.UUID] = uuid_fk("term.id")
    stage_id: Mapped[uuid.UUID | None] = uuid_fk("stage.id", nullable=True)
    period_type: Mapped[str] = mapped_column(enum(*PERIOD_TYPES, name="plan_period_type"), nullable=False, default="term")
    status: Mapped[str] = mapped_column(enum("draft", "approved", name="plan_status"), nullable=False, default="draft",
                                        server_default="draft")
    approved_by: Mapped[uuid.UUID | None] = uuid_fk("app_user.id", nullable=True, index=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    # {"<grade_id>:<subject_id>": {"<period key>": periods}}  — keys: "term", "2026-10", "2026-10-04" (week start / day)
    targets = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
