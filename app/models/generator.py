"""Automatic timetable generation runs (ERD §12)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.base import SyncMixin
from app.models.core import enum, uuid_fk

RUN_STATUSES = ("queued", "feasibility_failed", "running", "solved", "partial", "infeasible", "timeout",
                "cancelled", "failed")


class GeneratorRun(SyncMixin, db.Model):
    __tablename__ = "generator_run"
    timetable_id: Mapped[uuid.UUID] = uuid_fk("timetable.id")
    result_timetable_id: Mapped[uuid.UUID | None] = uuid_fk("timetable.id", nullable=True)
    mode: Mapped[str] = mapped_column(enum("full", "repair", "fill", name="gen_mode"), nullable=False, default="full")
    status: Mapped[str] = mapped_column(enum(*RUN_STATUSES, name="gen_status"), nullable=False, default="queued")
    params = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    feasibility = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    infeasible_core = mapped_column(JSONB)
    metrics = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    progress = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    objective: Mapped[int | None] = mapped_column(BigInteger)
    message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
