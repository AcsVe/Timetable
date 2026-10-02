"""Cover for absent teachers (حصص الإشغال).

For one date and one timetable, `CoverDay` works out:
  * which lesson periods lose their teacher (the "needs"), and what has been decided for each;
  * for any need, every possible substitute ranked by a transparent score, with the reasons in Arabic;
  * a fair automatic assignment for all open needs at once.

A teacher is *unavailable* for a period when they teach at that period, are absent, or already cover
another class then. Softer facts lower the score but are only shown as warnings: not otherwise at
school that day, on duty at that time, marked unavailable in the timetable, or above their daily
maximum. Fairness: covers already given this week and this term weigh against a teacher.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, time, timedelta

from sqlalchemy import select

from app.arabic import count, g, teacher_title
from app.extensions import db
from app.models import (
    Availability,
    Card,
    DutyAssignment,
    Lesson,
    Section,
    Subject,
    Substitution,
    Teacher,
    TeacherAbsence,
    Term,
    Timetable,
    Weekday,
)
from app.rules.bells import resolve_schedule

KIND_LABELS = {"cover": ("إشغال بمعلم بديل", "Covered by a substitute"),
               "merge": ("دمج مع شعبة أخرى", "Merged with another class"),
               "cancel": ("إلغاء الحصة", "Cancelled"),
               "none": ("لا تحتاج إلى بديل", "No cover needed")}


def week_start(d: date) -> date:
    """The school week starts on Sunday."""
    return d - timedelta(days=d.isoweekday() % 7)


def school_weekday(d: date) -> Weekday | None:
    return db.session.scalars(select(Weekday).where(Weekday.iso_dow == d.isoweekday(),
                                                    Weekday.is_school_day.is_(True))).first()


def cycle_week(tt: Timetable, d: date) -> int | None:
    """Week of an A/B cycle a date falls in (counted from the term start); None for one-week timetables."""
    if tt.cycle_weeks <= 1:
        return None
    term = db.session.get(Term, tt.term_id)
    if not term or not term.start_date:
        return None
    return ((week_start(d) - week_start(term.start_date)).days // 7) % tt.cycle_weeks + 1


def _tname(t: Teacher | None) -> str:
    return f"{teacher_title(t.gender)} {t.name_ar}" if t else "?"


def _overlap(a0: time | None, a1: time | None, b0: time | None, b1: time | None) -> bool:
    return bool(a0 and a1 and b0 and b1 and a0 < b1 and b0 < a1)


def _hm(t: time | None) -> str | None:
    return t.strftime("%H:%M") if t else None


@dataclass
class Need:
    key: str
    card: Card
    lesson: Lesson
    period_no: int
    teacher_id: uuid.UUID
    absence: TeacherAbsence | None
    starts_at: time | None = None
    ends_at: time | None = None
    co_present: list = field(default_factory=list)
    substitution: Substitution | None = None
    stale: bool = False     # a decision whose absence was since removed or shortened


class CoverDay:
    def __init__(self, tt: Timetable, d: date):
        self.tt, self.date = tt, d
        self.weekday = school_weekday(d)
        self.week = cycle_week(tt, d)
        self.teachers = {t.id: t for t in db.session.scalars(select(Teacher))}
        self.subjects = {s.id: s for s in db.session.scalars(select(Subject))}
        self.sections = {s.id: s for s in db.session.scalars(select(Section))}
        self.lessons = {l.id: l for l in db.session.scalars(select(Lesson).where(Lesson.timetable_id == tt.id))}
        self.absences = list(db.session.scalars(select(TeacherAbsence).where(
            TeacherAbsence.date_from <= d, TeacherAbsence.date_to >= d)))
        self.subs = list(db.session.scalars(select(Substitution).where(
            Substitution.timetable_id == tt.id, Substitution.date == d)))
        self.cards: list[Card] = []
        if self.weekday is not None:
            for c in db.session.scalars(select(Card).where(Card.timetable_id == tt.id, Card.weekday_id == self.weekday.id)):
                if c.lesson_id in self.lessons and (self.week is None or c.week_no is None or c.week_no == self.week):
                    self.cards.append(c)
        # teaching periods today per teacher
        self.teaching: dict[uuid.UUID, dict[int, Card]] = defaultdict(dict)
        for c in self.cards:
            for tid in self.lessons[c.lesson_id].teacher_ids:
                for p in range(c.period_no, c.period_no + c.duration):
                    self.teaching[tid][p] = c
        self._times: dict = {}
        self._extra = None

    # ------------------------------------------------------------------ helpers
    def absence_of(self, tid, period: int) -> TeacherAbsence | None:
        return next((a for a in self.absences if a.teacher_id == tid and a.covers(self.date, period)), None)

    def slot_time(self, lesson: Lesson, period: int) -> tuple[time | None, time | None]:
        sec = self.sections.get(lesson.targets[0].section_id) if lesson.targets else None
        if sec is None or self.weekday is None:
            return None, None
        key = (sec.grade_id, period)
        if key not in self._times:
            sched = resolve_schedule(self.tt.term_id, sec.grade, self.weekday.id)
            slot = next((s for s in sched.slots if s.kind == "lesson" and s.period_no == period), None) if sched else None
            self._times[key] = (slot.starts_at, slot.ends_at) if slot else (None, None)
        return self._times[key]

    def covering(self, exclude_id=None) -> dict[tuple, Substitution]:
        """(teacher, period) -> the cover they give today."""
        out = {}
        for s in self.subs:
            if s.id != exclude_id and s.kind == "cover" and s.substitute_teacher_id:
                out[(s.substitute_teacher_id, s.period_no)] = s
        return out

    def section_label(self, sid) -> str:
        s = self.sections.get(sid)
        if not s:
            return "?"
        g = s.grade.name_ar
        return s.name_ar if s.name_ar.replace(" ", "").startswith(g.replace(" ", "")) else f"{g} / {s.name_ar}"

    # ------------------------------------------------------------------ needs
    def needs(self) -> list[Need]:
        out: dict[str, Need] = {}
        for c in self.cards:
            l = self.lessons[c.lesson_id]
            if l.is_meeting:          # no class waits for a meeting: nothing to cover
                continue
            for p in range(c.period_no, c.period_no + c.duration):
                for tid in l.teacher_ids:
                    a = self.absence_of(tid, p)
                    if a is None:
                        continue
                    key = f"{c.id}:{p}:{tid}"
                    s0, s1 = self.slot_time(l, p)
                    out[key] = Need(key, c, l, p, tid, a, s0, s1,
                                    co_present=[x for x in l.teacher_ids if x != tid and self.absence_of(x, p) is None])
        cards = {c.id: c for c in self.cards}
        for s in self.subs:
            key = f"{s.card_id}:{s.period_no}:{s.original_teacher_id}"
            if key in out:
                out[key].substitution = s
            else:   # decided earlier, but the absence no longer covers it
                c = cards.get(s.card_id) or db.session.get(Card, s.card_id)
                l = self.lessons.get(c.lesson_id) if c else None
                if c is None or l is None:
                    continue
                s0, s1 = self.slot_time(l, s.period_no)
                out[key] = Need(key, c, l, s.period_no, s.original_teacher_id, None, s0, s1, substitution=s, stale=True)
        return sorted(out.values(), key=lambda n: (n.period_no, self.section_label(n.lesson.targets[0].section_id)
                                                   if n.lesson.targets else ""))

    # ------------------------------------------------------------------ candidates
    def _context(self):
        """Data that does not depend on the need: duties, time-off, cover counts, load, subjects."""
        if self._extra is not None:
            return self._extra
        wk0 = week_start(self.date)
        week_cov = defaultdict(int)
        term_cov = defaultdict(int)
        for s in db.session.scalars(select(Substitution).where(Substitution.timetable_id == self.tt.id,
                                                               Substitution.kind == "cover")):
            if s.substitute_teacher_id is None or s.date == self.date:
                continue
            term_cov[s.substitute_teacher_id] += 1
            if wk0 <= s.date < wk0 + timedelta(days=7):
                week_cov[s.substitute_teacher_id] += 1
        unavailable = set()
        if self.weekday is not None:
            for a in db.session.scalars(select(Availability).where(
                    Availability.timetable_id == self.tt.id, Availability.entity_type == "teacher",
                    Availability.weekday_id == self.weekday.id, Availability.status == "unavailable")):
                unavailable.add((a.entity_id, a.period_no))
        duties = [d for d in db.session.scalars(select(DutyAssignment).where(DutyAssignment.term_id == self.tt.term_id))
                  if self.weekday is not None and (d.weekday_id is None or d.weekday_id == self.weekday.id)]
        assigned = defaultdict(int)
        subj_of = defaultdict(set)
        secs_of = defaultdict(set)
        for l in self.lessons.values():
            if l.is_meeting:
                continue
            for tid in l.teacher_ids:
                assigned[tid] += l.periods_per_week
                subj_of[tid].add(l.subject_id)
                secs_of[tid].update(t.section_id for t in l.targets)
        for t in self.teachers.values():
            subj_of[t.id].update(s.id for s in t.subjects)
        self._extra = dict(week=week_cov, term=term_cov, unavailable=unavailable, duties=duties, assigned=assigned,
                           subjects=subj_of, sections=secs_of)
        return self._extra

    def candidates(self, need: Need, extra_busy: dict | None = None, extra_load: dict | None = None,
                   exclude_sub_id=None) -> list[dict]:
        ctx = self._context()
        covering = self.covering(exclude_sub_id)
        if extra_busy:
            covering = {**covering, **extra_busy}
        l = need.lesson
        p = need.period_no
        need_secs = {t.section_id for t in l.targets}
        need_stages = {self.sections[s].grade.stage_id for s in need_secs if s in self.sections}
        out = []
        for tid, t in self.teachers.items():
            if tid in l.teacher_ids:
                continue
            hard = []
            if p in self.teaching.get(tid, {}):
                c = self.teaching[tid][p]
                busy_l = self.lessons[c.lesson_id]
                hard.append(f"لديه {busy_l.label} في الوقت نفسه" if busy_l.is_meeting
                            else f"لديه حصة {busy_l.subject.name_ar} في الوقت نفسه")
            if self.absence_of(tid, p):
                hard.append("غائب")
            if (tid, p) in covering:
                hard.append("يغطي حصة أخرى في الوقت نفسه")
            if hard:
                continue
            score, why, warn = 0, [], []
            today = set(self.teaching.get(tid, {}).keys()) | {pp for (x, pp) in covering if x == tid}
            if self.teaching.get(tid):
                score += 40
                why.append("في المدرسة اليوم")
                if (p - 1) in today or (p + 1) in today:
                    score += 5
                    why.append(g(t.gender, "لديه حصة ملاصقة", "لديها حصة ملاصقة"))
            else:
                score -= 30
                warn.append(g(t.gender, "ليس لديه حصص في هذا اليوم", "ليس لديها حصص في هذا اليوم"))
            if l.subject_id in ctx["subjects"][tid]:
                score += 20
                why.append(f"{g(t.gender, 'يدرّس', 'تدرّس')} {l.subject.name_ar}")
            if need_secs & ctx["sections"][tid]:
                score += 15
                why.append(g(t.gender, "يدرّس هذه الشعبة", "تدرّس هذه الشعبة"))
            if need_stages & {s.id for s in t.stages}:
                score += 10
                why.append(g(t.gender, "من معلمي المرحلة", "من معلمات المرحلة"))
            day_load = len(today) + (extra_load or {}).get(tid, 0)
            score -= 4 * day_load
            if t.max_periods_per_day is not None and day_load + 1 > t.max_periods_per_day:
                score -= 25
                warn.append(f"{g(t.gender, 'يتجاوز حدّه', 'تتجاوز حدّها')} اليومي ({t.max_periods_per_day})")
            wk = ctx["week"][tid] + (extra_load or {}).get(("week", tid), 0)
            tm = ctx["term"][tid] + (extra_load or {}).get(("term", tid), 0)
            score -= 6 * wk + 2 * tm
            if t.target_weekly_periods is not None:
                gap = t.target_weekly_periods - ctx["assigned"][tid]
                if gap > 0:
                    score += min(10, gap)
                    why.append(f"{g(t.gender, 'نصابه', 'نصابها')} غير مكتمل ({gap})")
            if (tid, p) in ctx["unavailable"]:
                score -= 50
                warn.append(g(t.gender, "غير متاح في هذه الحصة", "غير متاحة في هذه الحصة"))
            for d in ctx["duties"]:
                if tid in (d.teacher_ids or []) and _overlap(d.starts_at, d.ends_at, need.starts_at, need.ends_at):
                    score -= 30
                    warn.append(f"{g(t.gender, 'مناوب', 'مناوبة')} ({d.duty_type})")
            out.append({
                "teacher_id": str(tid), "name": t.name_ar, "name_en": t.name_en, "score": score,
                "reasons": why, "warnings": warn, "periods_today": day_load, "covers_week": wk, "covers_term": tm,
            })
        out.sort(key=lambda x: (-x["score"], x["covers_term"], x["name"]))
        return out

    # ------------------------------------------------------------------ automatic
    def auto_assign(self, keys: set[str] | None = None) -> dict:
        """Give every open need (or the chosen ones) the best fair substitute, hardest needs first.
        A need whose lesson still has a teacher present is marked 'no cover needed'."""
        needs = [n for n in self.needs() if not n.stale and n.substitution is None and (keys is None or n.key in keys)]
        created, left = [], []
        busy: dict = {}
        load: dict = defaultdict(int)
        todo = []
        for n in needs:
            if n.co_present:
                created.append(self._add(n, "none", None, note="المعلم المشارك حاضر"))
            else:
                todo.append(n)
        # fewest options first, so scarce teachers are kept for the needs that only they can take
        todo.sort(key=lambda n: len(self.candidates(n, busy, load)))
        for n in todo:
            cands = self.candidates(n, busy, load)
            if not cands:
                left.append(n.key)
                continue
            best = cands[0]
            tid = uuid.UUID(best["teacher_id"])
            created.append(self._add(n, "cover", tid))
            busy[(tid, n.period_no)] = True
            load[tid] += 1
            load[("week", tid)] += 1
            load[("term", tid)] += 1
        db.session.flush()
        return {"created": len(created), "unassigned": left}

    def _add(self, n: Need, kind: str, tid, note=None) -> Substitution:
        s = Substitution(timetable_id=self.tt.id, date=self.date, card_id=n.card.id, period_no=n.period_no,
                         original_teacher_id=n.teacher_id, substitute_teacher_id=tid, kind=kind, auto=True, note=note)
        db.session.add(s)
        self.subs.append(s)
        return s

    # ------------------------------------------------------------------ serialisation
    def need_json(self, n: Need) -> dict:
        l = n.lesson
        s = n.substitution
        return {
            "key": n.key, "card_id": str(n.card.id), "lesson_id": str(l.id), "period_no": n.period_no,
            "starts_at": _hm(n.starts_at), "ends_at": _hm(n.ends_at),
            "subject_id": str(l.subject_id), "subject": l.subject.name_ar,
            "targets": [{"section_id": str(t.section_id), "group_id": str(t.group_id) if t.group_id else None} for t in l.targets],
            "sections": "، ".join(self.section_label(t.section_id) + (f" ({t.group.name_ar})" if t.group_id else "") for t in l.targets),
            "teacher_id": str(n.teacher_id), "room_id": str(n.card.room_id) if n.card.room_id else None,
            "absence_id": str(n.absence.id) if n.absence else None, "reason": n.absence.reason if n.absence else None,
            "co_present": [str(x) for x in n.co_present], "stale": n.stale,
            "substitution": None if s is None else {
                "id": str(s.id), "version": s.version, "kind": s.kind,
                "substitute_teacher_id": str(s.substitute_teacher_id) if s.substitute_teacher_id else None,
                "room_id": str(s.room_id) if s.room_id else None, "note": s.note, "auto": s.auto,
                "notified_at": s.notified_at.isoformat() if s.notified_at else None},
        }

    def summary(self, needs: list[Need]) -> dict:
        live = [n for n in needs if not n.stale]
        return {"needs": len(live), "decided": sum(1 for n in live if n.substitution),
                "open": sum(1 for n in live if not n.substitution),
                "covered": sum(1 for n in live if n.substitution and n.substitution.kind == "cover"),
                "absent_teachers": len({a.teacher_id for a in self.absences})}

    def messages(self) -> list[dict]:
        """One message per substitute teacher for the day (to send by WhatsApp / Teams / e-mail, or in-app)."""
        by_t = defaultdict(list)
        for n in self.needs():
            s = n.substitution
            if s and s.kind == "cover" and s.substitute_teacher_id and not n.stale:
                by_t[s.substitute_teacher_id].append(n)
        out = []
        for tid, ns in by_t.items():
            t = self.teachers.get(tid)
            lines = []
            for n in sorted(ns, key=lambda x: x.period_no):
                when = f" ({_hm(n.starts_at)}\u200e–\u200e{_hm(n.ends_at)})" if n.starts_at else ""
                room = n.substitution.room_id or n.card.room_id
                room_txt = ""
                if room:
                    from app.models import Room
                    r = db.session.get(Room, room)
                    room_txt = f" — {r.name_ar}" if r else ""
                lines.append(f"• الحصة {n.period_no}{when}: {n.lesson.subject.name_ar} — "
                             f"{self.need_json(n)['sections']}{room_txt} (بدلاً من {_tname(self.teachers.get(n.teacher_id))})")
            day = self.weekday.name_ar if self.weekday else ""
            text = (f"{_tname(t)}، السلام عليكم.\nلديك {count(len(ns), 'period')} للإشغال يوم {day} "
                    f"\u200e{self.date.isoformat()}\u200f:\n" + "\n".join(lines))
            out.append({"teacher_id": str(tid), "name": t.name_ar if t else "?", "user_id": str(t.user_id) if t and t.user_id else None,
                        "email": t.email if t else None, "phone": t.phone if t else None, "count": len(ns), "text": text})
        out.sort(key=lambda x: x["name"])
        return out
