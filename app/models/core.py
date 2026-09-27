"""School, calendar, academic structure, bell schedules and resources (ERD §2–§5)."""
from __future__ import annotations

import uuid
from datetime import date, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    Time,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.base import SyncMixin, utcnow

LIVE = text("deleted_at IS NULL")


def live_unique(name: str, *cols, nulls_not_distinct: bool = False, where=None):
    """Unique index that ignores soft-deleted rows."""
    return Index(
        name,
        *cols,
        unique=True,
        postgresql_where=where if where is not None else LIVE,
        postgresql_nulls_not_distinct=nulls_not_distinct,
    )


def enum(*values: str, name: str):
    return Enum(*values, name=name, native_enum=False, create_constraint=True, length=20)


def uuid_fk(target: str, nullable: bool = False, index: bool = True, ondelete: str | None = None):
    return mapped_column(
        UUID(as_uuid=True), ForeignKey(target, ondelete=ondelete), nullable=nullable, index=index
    )


# ---------------------------------------------------------------------------
# §2 School, settings, calendar
# ---------------------------------------------------------------------------
class School(SyncMixin, db.Model):
    __tablename__ = "school"
    name_ar: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str | None] = mapped_column(Text)
    logo_path: Mapped[str | None] = mapped_column(Text)
    # Uploaded logo (preferred over an external URL: exports never depend on another site).
    logo_data = mapped_column(db.LargeBinary, deferred=True)
    logo_mime: Mapped[str | None] = mapped_column(String(40))
    default_lang: Mapped[str] = mapped_column(enum("ar", "en", name="lang"), nullable=False, default="ar")


class AppSetting(db.Model):
    __tablename__ = "app_setting"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value = mapped_column(JSONB, nullable=True)
    updated_at = mapped_column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AcademicYear(SyncMixin, db.Model):
    __tablename__ = "academic_year"
    name: Mapped[str] = mapped_column(String(20), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    terms = relationship("Term", back_populates="academic_year", order_by="Term.ordinal")
    __table_args__ = (
        live_unique("uq_academic_year_name_live", "name"),
        live_unique("uq_academic_year_one_current", "is_current", where=text("is_current AND deleted_at IS NULL")),
    )


class Term(SyncMixin, db.Model):
    __tablename__ = "term"
    academic_year_id: Mapped[uuid.UUID] = uuid_fk("academic_year.id")
    name_ar: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str | None] = mapped_column(Text)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    academic_year = relationship("AcademicYear", back_populates="terms")
    __table_args__ = (live_unique("uq_term_year_ordinal_live", "academic_year_id", "ordinal"),)


class Weekday(SyncMixin, db.Model):
    __tablename__ = "weekday"
    iso_dow: Mapped[int] = mapped_column(Integer, nullable=False)  # 1=Mon … 7=Sun
    name_ar: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_school_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    __table_args__ = (
        live_unique("uq_weekday_dow_live", "iso_dow"),
        CheckConstraint("iso_dow BETWEEN 1 AND 7", name="dow_range"),
    )


# ---------------------------------------------------------------------------
# §3 Academic structure
# ---------------------------------------------------------------------------
class Stage(SyncMixin, db.Model):
    __tablename__ = "stage"
    name_ar: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    grades = relationship("Grade", back_populates="stage", order_by="Grade.sort_order")


class Grade(SyncMixin, db.Model):
    __tablename__ = "grade"
    stage_id: Mapped[uuid.UUID] = uuid_fk("stage.id")
    name_ar: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stage = relationship("Stage", back_populates="grades")
    sections = relationship("Section", back_populates="grade", order_by="Section.name_ar")


class Section(SyncMixin, db.Model):
    __tablename__ = "section"
    grade_id: Mapped[uuid.UUID] = uuid_fk("grade.id")
    name_ar: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str | None] = mapped_column(Text)
    student_count: Mapped[int | None] = mapped_column(Integer)
    home_room_id: Mapped[uuid.UUID | None] = uuid_fk("room.id", nullable=True)
    class_teacher_id: Mapped[uuid.UUID | None] = uuid_fk("teacher.id", nullable=True)  # مربي الصف
    grade = relationship("Grade", back_populates="sections")
    divisions = relationship("Division", back_populates="section")
    __table_args__ = (live_unique("uq_section_grade_name_live", "grade_id", "name_ar"),)


class Division(SyncMixin, db.Model):
    """A way of splitting a section into groups that may be taught simultaneously.

    'Whole section' is represented by lesson_target.group_id = NULL, so no
    explicit whole division is stored.
    """

    __tablename__ = "division"
    section_id: Mapped[uuid.UUID] = uuid_fk("section.id")
    name: Mapped[str] = mapped_column(Text, nullable=False)
    section = relationship("Section", back_populates="divisions")
    groups = relationship("StudentGroup", back_populates="division", order_by="StudentGroup.name_ar")


class StudentGroup(SyncMixin, db.Model):
    __tablename__ = "student_group"
    division_id: Mapped[uuid.UUID] = uuid_fk("division.id")
    name_ar: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str | None] = mapped_column(Text)
    student_count: Mapped[int | None] = mapped_column(Integer)
    division = relationship("Division", back_populates="groups")


# ---------------------------------------------------------------------------
# §4 Bell schedules (per-day timing templates)
# ---------------------------------------------------------------------------
class BellSchedule(SyncMixin, db.Model):
    __tablename__ = "bell_schedule"
    name_ar: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str | None] = mapped_column(Text)
    stage_id: Mapped[uuid.UUID | None] = uuid_fk("stage.id", nullable=True)
    slots = relationship(
        "BellSlot", back_populates="schedule", order_by="BellSlot.slot_no", cascade="all, delete-orphan"
    )


class BellSlot(db.Model):
    """Owned child of BellSchedule; synced as part of its parent."""

    __tablename__ = "bell_slot"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bell_schedule_id: Mapped[uuid.UUID] = uuid_fk("bell_schedule.id", ondelete="CASCADE")
    slot_no: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(enum("lesson", "break", name="slot_kind"), nullable=False)
    period_no: Mapped[int | None] = mapped_column(Integer)
    label_ar: Mapped[str | None] = mapped_column(Text)
    label_en: Mapped[str | None] = mapped_column(Text)
    starts_at: Mapped[time] = mapped_column(Time, nullable=False)
    ends_at: Mapped[time] = mapped_column(Time, nullable=False)
    schedule = relationship("BellSchedule", back_populates="slots")
    __table_args__ = (
        Index("uq_bell_slot_no", "bell_schedule_id", "slot_no", unique=True),
        Index("uq_bell_slot_period", "bell_schedule_id", "period_no", unique=True,
              postgresql_where=text("period_no IS NOT NULL")),
        CheckConstraint("(kind = 'lesson') = (period_no IS NOT NULL)", name="lesson_has_period"),
        CheckConstraint("ends_at > starts_at", name="slot_time_order"),
    )


class BellAssignment(SyncMixin, db.Model):
    """Which bell schedule applies to (term, weekday, stage[, grade]). Grade-specific wins."""

    __tablename__ = "bell_assignment"
    term_id: Mapped[uuid.UUID] = uuid_fk("term.id")
    weekday_id: Mapped[uuid.UUID] = uuid_fk("weekday.id")
    stage_id: Mapped[uuid.UUID] = uuid_fk("stage.id")
    grade_id: Mapped[uuid.UUID | None] = uuid_fk("grade.id", nullable=True)
    bell_schedule_id: Mapped[uuid.UUID] = uuid_fk("bell_schedule.id")
    schedule = relationship("BellSchedule")
    __table_args__ = (
        live_unique(
            "uq_bell_assignment_live", "term_id", "weekday_id", "stage_id", "grade_id", nulls_not_distinct=True
        ),
    )


# ---------------------------------------------------------------------------
# §5 Resources
# ---------------------------------------------------------------------------
class Subject(SyncMixin, db.Model):
    __tablename__ = "subject"
    name_ar: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str | None] = mapped_column(Text)
    short_ar: Mapped[str | None] = mapped_column(String(20))
    short_en: Mapped[str | None] = mapped_column(String(20))
    color: Mapped[str | None] = mapped_column(String(9))
    max_teachers_per_block: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    requires_room_type: Mapped[str | None] = mapped_column(String(30))
    rooms = relationship("Room", secondary="subject_room")
    __table_args__ = (CheckConstraint("max_teachers_per_block >= 1", name="max_teachers_pos"),)


teacher_stage = Table(
    "teacher_stage",
    db.metadata,
    Column("teacher_id", UUID(as_uuid=True), ForeignKey("teacher.id", ondelete="CASCADE"), primary_key=True),
    Column("stage_id", UUID(as_uuid=True), ForeignKey("stage.id", ondelete="CASCADE"), primary_key=True),
)
teacher_subject = Table(
    "teacher_subject",
    db.metadata,
    Column("teacher_id", UUID(as_uuid=True), ForeignKey("teacher.id", ondelete="CASCADE"), primary_key=True),
    Column("subject_id", UUID(as_uuid=True), ForeignKey("subject.id", ondelete="CASCADE"), primary_key=True),
)
subject_room = Table(
    "subject_room",
    db.metadata,
    Column("subject_id", UUID(as_uuid=True), ForeignKey("subject.id", ondelete="CASCADE"), primary_key=True),
    Column("room_id", UUID(as_uuid=True), ForeignKey("room.id", ondelete="CASCADE"), primary_key=True),
)


class Teacher(SyncMixin, db.Model):
    __tablename__ = "teacher"
    name_ar: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str | None] = mapped_column(Text)
    short: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(30))
    title: Mapped[str | None] = mapped_column(String(40))  # اللقب: أ.، د.، م.
    gender: Mapped[str | None] = mapped_column(enum("m", "f", name="gender"))
    color: Mapped[str | None] = mapped_column(String(9))
    user_id: Mapped[uuid.UUID | None] = uuid_fk("app_user.id", nullable=True)
    target_weekly_periods: Mapped[int | None] = mapped_column(Integer)
    max_periods_per_day: Mapped[int | None] = mapped_column(Integer)
    max_gaps_per_day: Mapped[int | None] = mapped_column(Integer)
    max_gaps_per_week: Mapped[int | None] = mapped_column(Integer)
    max_consecutive: Mapped[int | None] = mapped_column(Integer)
    max_days_per_week: Mapped[int | None] = mapped_column(Integer)
    stages = relationship("Stage", secondary=teacher_stage)
    subjects = relationship("Subject", secondary=teacher_subject)
    __table_args__ = (live_unique("uq_teacher_user_live", "user_id", where=text("user_id IS NOT NULL AND deleted_at IS NULL")),)


class Building(SyncMixin, db.Model):
    __tablename__ = "building"
    name_ar: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str | None] = mapped_column(Text)


class Room(SyncMixin, db.Model):
    __tablename__ = "room"
    building_id: Mapped[uuid.UUID | None] = uuid_fk("building.id", nullable=True)
    name_ar: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str | None] = mapped_column(Text)
    short: Mapped[str | None] = mapped_column(String(20))
    room_type: Mapped[str | None] = mapped_column(String(30))
    capacity: Mapped[int | None] = mapped_column(Integer)
    is_shared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
