"""Timetables, lessons, cards, occupancy guard and constraints (ERD §6–§7)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, INT4RANGE, JSONB, UUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.base import SyncMixin
from app.models.core import enum, live_unique, uuid_fk


class Timetable(SyncMixin, db.Model):
    __tablename__ = "timetable"
    term_id: Mapped[uuid.UUID] = uuid_fk("term.id")
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        enum("draft", "published", "archived", name="tt_status"), nullable=False, default="draft"
    )
    cycle_weeks: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    based_on_id: Mapped[uuid.UUID | None] = uuid_fk("timetable.id", nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[uuid.UUID | None] = uuid_fk("app_user.id", nullable=True, index=False)
    term = relationship("Term")
    __table_args__ = (
        live_unique(
            "uq_timetable_one_published", "term_id",
            where=text("status = 'published' AND deleted_at IS NULL"),
        ),
        CheckConstraint("cycle_weeks BETWEEN 1 AND 4", name="cycle_weeks_range"),
    )

    def weeks_range(self, week_no: int | None) -> tuple[int, int]:
        """Half-open range of cycle weeks a card occupies: all weeks, or one."""
        if week_no is None:
            return (1, self.cycle_weeks + 1)
        return (week_no, week_no + 1)


class Lesson(SyncMixin, db.Model):
    """What must be taught: subject × targets × teachers × periods per week."""

    __tablename__ = "lesson"
    timetable_id: Mapped[uuid.UUID] = uuid_fk("timetable.id")
    subject_id: Mapped[uuid.UUID] = uuid_fk("subject.id")
    periods_per_week: Mapped[int] = mapped_column(Integer, nullable=False)
    duration: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    week_no: Mapped[int | None] = mapped_column(Integer)
    preferred_room_id: Mapped[uuid.UUID | None] = uuid_fk("room.id", nullable=True)
    notes: Mapped[str | None] = mapped_column(Text)
    # A meeting (department meeting, heads of department…) is a lesson with teachers and no classes:
    # it blocks its members like a lesson, shows in their timetables under its title, and may be left
    # out of their weekly teaching load.
    kind: Mapped[str] = mapped_column(enum("lesson", "meeting", name="lesson_kind"), nullable=False,
                                      default="lesson", server_default="lesson")
    title: Mapped[str | None] = mapped_column(Text)
    counts_load: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    bell_schedule_id: Mapped[uuid.UUID | None] = uuid_fk("bell_schedule.id", nullable=True)

    subject = relationship("Subject")
    timetable = relationship("Timetable")
    teachers = relationship("LessonTeacher", back_populates="lesson", cascade="all, delete-orphan")
    targets = relationship("LessonTarget", back_populates="lesson", cascade="all, delete-orphan")
    cards = relationship("Card", back_populates="lesson", order_by="Card.created_at")
    __table_args__ = (
        CheckConstraint("periods_per_week >= 1", name="ppw_pos"),
        CheckConstraint("duration BETWEEN 1 AND 4", name="duration_range"),
    )

    @property
    def is_meeting(self) -> bool:
        return self.kind == "meeting"

    @property
    def label(self) -> str:
        """What the lesson is called in grids, reports and messages: the meeting title or the subject."""
        if self.kind == "meeting" and self.title:
            return self.title
        return self.subject.name_ar

    @property
    def label_en(self) -> str:
        if self.kind == "meeting" and self.title:
            return self.title
        return self.subject.name_en or self.subject.name_ar

    @property
    def teacher_ids(self) -> list[uuid.UUID]:
        return [t.teacher_id for t in self.teachers]


class LessonTeacher(db.Model):
    __tablename__ = "lesson_teacher"
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lesson.id", ondelete="CASCADE"), primary_key=True
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teacher.id"), primary_key=True, index=True
    )
    role: Mapped[str] = mapped_column(enum("main", "assistant", name="teacher_role"), nullable=False, default="main")
    lesson = relationship("Lesson", back_populates="teachers")
    teacher = relationship("Teacher")


class LessonTarget(db.Model):
    __tablename__ = "lesson_target"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_id: Mapped[uuid.UUID] = uuid_fk("lesson.id", ondelete="CASCADE")
    section_id: Mapped[uuid.UUID] = uuid_fk("section.id")
    group_id: Mapped[uuid.UUID | None] = uuid_fk("student_group.id", nullable=True)
    lesson = relationship("Lesson", back_populates="targets")
    section = relationship("Section")
    group = relationship("StudentGroup")
    __table_args__ = (
        Index("uq_lesson_target", "lesson_id", "section_id", "group_id",
              unique=True, postgresql_nulls_not_distinct=True),
    )


class Card(SyncMixin, db.Model):
    """One placed (or not-yet-placed) block of a lesson."""

    __tablename__ = "card"
    timetable_id: Mapped[uuid.UUID] = uuid_fk("timetable.id")
    lesson_id: Mapped[uuid.UUID] = uuid_fk("lesson.id")
    weekday_id: Mapped[uuid.UUID | None] = uuid_fk("weekday.id", nullable=True)
    period_no: Mapped[int | None] = mapped_column(Integer)
    duration: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    week_no: Mapped[int | None] = mapped_column(Integer)
    room_id: Mapped[uuid.UUID | None] = uuid_fk("room.id", nullable=True)
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    lesson = relationship("Lesson", back_populates="cards")
    __table_args__ = (
        CheckConstraint("(weekday_id IS NULL) = (period_no IS NULL)", name="placed_consistent"),
        CheckConstraint("duration BETWEEN 1 AND 4", name="card_duration_range"),
        CheckConstraint("period_no IS NULL OR period_no >= 1", name="period_pos"),
        Index("ix_card_slot", "timetable_id", "weekday_id", "period_no"),
    )

    @property
    def is_placed(self) -> bool:
        return self.weekday_id is not None


class Occupancy(db.Model):
    """Derived rows (one per teacher / exclusive room of each placed card).

    The EXCLUDE constraint makes a double-booked teacher or room impossible at
    the database level, whatever the application code does and however many
    users save at the same moment. Conflicts are by period number (decision #1).
    """

    __tablename__ = "occupancy"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    timetable_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("timetable.id"), nullable=False)
    card_id: Mapped[uuid.UUID] = uuid_fk("card.id", ondelete="CASCADE")
    resource_type: Mapped[str] = mapped_column(enum("teacher", "room", name="occ_resource"), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    weekday_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("weekday.id"), nullable=False)
    periods = mapped_column(INT4RANGE, nullable=False)
    weeks = mapped_column(INT4RANGE, nullable=False)
    __table_args__ = (
        ExcludeConstraint(
            ("timetable_id", "="),
            ("resource_type", "="),
            ("resource_id", "="),
            ("weekday_id", "="),
            ("periods", "&&"),
            ("weeks", "&&"),
            name="ex_occupancy_no_overlap",
            using="gist",
        ),
    )


class Availability(SyncMixin, db.Model):
    """Time-off grid. A missing row means available."""

    __tablename__ = "availability"
    timetable_id: Mapped[uuid.UUID] = uuid_fk("timetable.id")
    entity_type: Mapped[str] = mapped_column(
        enum("teacher", "section", "subject", "room", name="avail_entity"), nullable=False
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    weekday_id: Mapped[uuid.UUID] = uuid_fk("weekday.id", index=False)
    period_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        enum("unavailable", "conditional", name="avail_status"), nullable=False, default="unavailable"
    )
    __table_args__ = (
        live_unique("uq_availability_live", "timetable_id", "entity_type", "entity_id", "weekday_id", "period_no"),
    )


class ConstraintRule(SyncMixin, db.Model):
    """ASC 'card relationships' and similar advanced rules; enforced fully by the generator (phase 3)."""

    __tablename__ = "constraint_rule"
    timetable_id: Mapped[uuid.UUID] = uuid_fk("timetable.id")
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    scope_type: Mapped[str] = mapped_column(
        enum("subject", "lesson", "teacher", "section", "grade", "stage", "global", name="rule_scope"),
        nullable=False,
    )
    scope_ids = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, server_default=text("'{}'"))
    params = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    strength: Mapped[str] = mapped_column(enum("hard", "soft", name="rule_strength"), nullable=False, default="hard")
    weight: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
