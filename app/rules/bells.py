"""Bell schedule resolution: for grade G on weekday D in term T, a grade-specific
assignment wins over the stage-wide one (ERD §4)."""
from __future__ import annotations

import uuid

from sqlalchemy import select

from app.extensions import db
from app.models import BellAssignment, BellSchedule, Grade


def resolve_schedule(term_id: uuid.UUID, grade: Grade, weekday_id: uuid.UUID) -> BellSchedule | None:
    rows = db.session.scalars(
        select(BellAssignment).where(
            BellAssignment.term_id == term_id,
            BellAssignment.weekday_id == weekday_id,
            BellAssignment.stage_id == grade.stage_id,
            (BellAssignment.grade_id == grade.id) | BellAssignment.grade_id.is_(None),
        )
    ).all()
    specific = [r for r in rows if r.grade_id is not None]
    chosen = specific[0] if specific else (rows[0] if rows else None)
    return db.session.get(BellSchedule, chosen.bell_schedule_id) if chosen else None


def lesson_periods(schedule: BellSchedule) -> dict[int, int]:
    """period_no -> slot_no for the lesson slots of a schedule."""
    return {s.period_no: s.slot_no for s in schedule.slots if s.kind == "lesson"}


class BellCache:
    """Per-request memo so checking a whole grid doesn't re-query the same schedules."""

    def __init__(self, term_id: uuid.UUID):
        self.term_id = term_id
        self._cache: dict[tuple, dict[int, int] | None] = {}

    def periods(self, grade: Grade, weekday_id: uuid.UUID) -> dict[int, int] | None:
        key = (grade.id, weekday_id)
        if key not in self._cache:
            sched = resolve_schedule(self.term_id, grade, weekday_id)
            self._cache[key] = lesson_periods(sched) if sched else None
        return self._cache[key]

    def schedule_periods(self, schedule_id: uuid.UUID) -> dict[int, int] | None:
        key = ("schedule", schedule_id)
        if key not in self._cache:
            sched = db.session.get(BellSchedule, schedule_id)
            self._cache[key] = lesson_periods(sched) if sched else None
        return self._cache[key]

    def any_periods(self, weekday_id: uuid.UUID) -> dict[int, int]:
        """Every period number that exists for some grade on that day (a meeting without its own timing)."""
        key = ("any", weekday_id)
        if key not in self._cache:
            ids = set(db.session.scalars(select(BellAssignment.bell_schedule_id).where(
                BellAssignment.term_id == self.term_id, BellAssignment.weekday_id == weekday_id)))
            out: dict[int, int] = {}
            for sid in ids:
                for p, slot in (self.schedule_periods(sid) or {}).items():
                    out.setdefault(p, p)    # slot numbers differ between schedules: no break check here
            self._cache[key] = out
        return self._cache[key]

    def meeting_periods(self, lesson, weekday_id: uuid.UUID) -> dict[int, int] | None:
        if lesson.bell_schedule_id:
            return self.schedule_periods(lesson.bell_schedule_id)
        return self.any_periods(weekday_id)
