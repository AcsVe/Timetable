"""Stage-scoped write permissions (decision #5).

admin          → everything
stage_editor   → records whose stages are all within the user's stages
viewer         → read only
Reads are open to every signed-in user: conflict detection must always see
all stages (a teacher shared by two stages is busy for everyone).
"""
from __future__ import annotations

import uuid

from app.errors import ApiError
from app.extensions import db
from app.models import (
    Availability,
    BellAssignment,
    BellSchedule,
    Card,
    Division,
    DutyAssignment,
    ExamSession,
    Grade,
    Lesson,
    Section,
    StudentGroup,
    Teacher,
)

GLOBAL = None  # marker: record has no stage → admin only


def _section_stage(section_id) -> uuid.UUID | None:
    s = db.session.get(Section, section_id)
    return s.grade.stage_id if s else None


def stages_of(obj) -> set[uuid.UUID] | None:
    if isinstance(obj, Grade):
        return {obj.stage_id}
    if isinstance(obj, Section):
        g = obj.grade or db.session.get(Grade, obj.grade_id)
        return {g.stage_id} if g else set()
    if isinstance(obj, Division):
        sid = _section_stage(obj.section_id)
        return {sid} if sid else set()
    if isinstance(obj, StudentGroup):
        d = obj.division or db.session.get(Division, obj.division_id)
        sid = _section_stage(d.section_id) if d else None
        return {sid} if sid else set()
    if isinstance(obj, BellSchedule):
        return {obj.stage_id} if obj.stage_id else GLOBAL
    if isinstance(obj, BellAssignment):
        return {obj.stage_id}
    if isinstance(obj, Lesson):
        return {_section_stage(t.section_id) for t in obj.targets} - {None}
    if isinstance(obj, Card):
        return stages_of(obj.lesson or db.session.get(Lesson, obj.lesson_id))
    if isinstance(obj, Availability):
        if obj.entity_type == "section":
            sid = _section_stage(obj.entity_id)
            return {sid} if sid else set()
        if obj.entity_type == "teacher":
            t = db.session.get(Teacher, obj.entity_id)
            return stages_of(t) if t else set()
        return GLOBAL
    if isinstance(obj, Teacher):
        return {s.id for s in obj.stages} or GLOBAL
    if isinstance(obj, (ExamSession, DutyAssignment)):
        return {obj.stage_id} if obj.stage_id else GLOBAL
    return GLOBAL


# Teachers are shared across stages: an editor may edit a teacher who teaches in
# any of their stages (intersection), not only teachers exclusive to them.
INTERSECT_MODELS = (Teacher,)


def can_write(user, obj) -> bool:
    if user.role == "admin":
        return True
    if user.role != "stage_editor":
        return False
    stages = stages_of(obj)
    if stages is GLOBAL:
        return False
    if isinstance(obj, Availability) and obj.entity_type == "teacher":
        return bool(stages & user.stage_ids)
    if isinstance(obj, INTERSECT_MODELS):
        return bool(stages & user.stage_ids)
    return bool(stages) and stages <= user.stage_ids


def require_write(user, obj) -> None:
    if not can_write(user, obj):
        raise ApiError("forbidden", 403)


def require_admin(user) -> None:
    if user.role != "admin":
        raise ApiError("forbidden", 403)
