"""Automatic timetable generator (ERD §12) on Google OR-Tools CP-SAT.

One boolean x[card, day, start] for every place a card may start. Hard rules are the same as the
placement checker's (teachers, sections with their divisions/groups, rooms, bell times and breaks,
time-off), plus each teacher's limits. Soft goals, each with its own weight: few teacher gaps, a lesson's
periods spread over the week, no long runs of consecutive periods, and — in repair mode — moving as few
cards as possible. When some cards cannot be placed, the generator explains why with the smallest set of
requirements that cannot all hold together (CP-SAT assumptions), in Arabic.

Modes:  full   — re-place every unlocked card (locked cards stay);
        repair — like full, but every card that moves from its current place costs a penalty;
        fill   — keep everything already placed, place only the cards that are still unplaced.
"""
from __future__ import annotations

import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select

from app.arabic import count, teacher_title
from app.extensions import db
from app.models import (
    Availability,
    Card,
    Division,
    Grade,
    Lesson,
    Room,
    Section,
    StudentGroup,
    Subject,
    Teacher,
    Timetable,
    Weekday,
)
from app.rules.bells import BellCache

DEFAULTS = {"time_limit": 60, "workers": 0, "seed": 1, "allow_unplaced": True, "explain": True,
            "w_gaps": 6, "w_spread": 25, "w_consecutive": 12, "w_move": 40, "w_unplaced": 1000,
            "w_daily_max": 30, "w_class_gaps": 8}


def normalize_params(p: dict | None) -> dict:
    out = dict(DEFAULTS)
    for k, v in (p or {}).items():
        if k not in DEFAULTS:
            continue
        if isinstance(DEFAULTS[k], bool):
            out[k] = bool(v)
        else:
            try:
                out[k] = max(0, int(v))
            except (TypeError, ValueError):
                pass
    out["time_limit"] = min(max(out["time_limit"], 5), 1800)
    out["workers"] = min(out["workers"], 16)
    return out


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
@dataclass
class CardInfo:
    id: uuid.UUID
    lesson: Lesson
    duration: int
    week_no: int | None
    teachers: list
    targets: list            # [(section_id, group_id|None)]
    room_id: uuid.UUID | None
    locked: bool
    cur: tuple | None        # (day index, start period) or None
    domain: list = field(default_factory=list)     # [(day index, start)]
    blocked_by_teacher: dict = field(default_factory=dict)   # (d, p) -> teacher ids whose time-off forbids it


class Problem:
    """Everything the solver needs, loaded once from the database."""

    def __init__(self, tt: Timetable, mode: str):
        self.tt, self.mode = tt, mode
        self.days = list(db.session.scalars(select(Weekday).where(Weekday.is_school_day.is_(True)).order_by(Weekday.sort_order)))
        self.day_ix = {d.id: i for i, d in enumerate(self.days)}
        self.teachers = {t.id: t for t in db.session.scalars(select(Teacher))}
        self.sections = {s.id: s for s in db.session.scalars(select(Section))}
        self.grades = {g.id: g for g in db.session.scalars(select(Grade))}
        self.groups = {g.id: g for g in db.session.scalars(select(StudentGroup))}
        self.divisions = {d.id: d for d in db.session.scalars(select(Division))}
        self.rooms = {r.id: r for r in db.session.scalars(select(Room))}
        self.subjects = {s.id: s for s in db.session.scalars(select(Subject))}
        self.lessons = {l.id: l for l in db.session.scalars(select(Lesson).where(Lesson.timetable_id == tt.id))}
        self.weeks = list(range(1, tt.cycle_weeks + 1))
        bells = self.bells = BellCache(tt.term_id)
        # per grade and day: period -> slot number (consecutive slot numbers = no break between)
        self.periods = {(g, d): (bells.periods(self.grades[g], day.id) or {}) for g in self.grades for d, day in enumerate(self.days)}
        self.all_periods = sorted({p for v in self.periods.values() for p in v})
        unavailable = defaultdict(set)   # (kind, id) -> {(d, p)}
        for a in db.session.scalars(select(Availability).where(Availability.timetable_id == tt.id,
                                                               Availability.status == "unavailable")):
            if a.weekday_id in self.day_ix:
                unavailable[(a.entity_type, a.entity_id)].add((self.day_ix[a.weekday_id], a.period_no))
        self.unavailable = unavailable
        self.cards: list[CardInfo] = []
        for c in db.session.scalars(select(Card).where(Card.timetable_id == tt.id)):
            l = self.lessons.get(c.lesson_id)
            if l is None:
                continue
            cur = (self.day_ix[c.weekday_id], c.period_no) if c.weekday_id in self.day_ix and c.period_no else None
            room = c.room_id or l.preferred_room_id
            fixed = c.is_locked or (mode == "fill" and cur is not None)
            info = CardInfo(c.id, l, c.duration, c.week_no, list(l.teacher_ids),
                            [(t.section_id, t.group_id) for t in l.targets], room, fixed and cur is not None, cur)
            self._domain(info)
            self.cards.append(info)

    def _starts_for(self, info: CardInfo, d: int) -> list[int]:
        if info.lesson.is_meeting:     # its own timing template, or any period that exists that day
            per = self.bells.meeting_periods(info.lesson, self.days[d].id) or {}
            need = lambda p: [p + i for i in range(info.duration)]
            return [p for p in sorted(per) if all(q in per for q in need(p))
                    and (not info.lesson.bell_schedule_id or all(per[q] == per[p] + i for i, q in enumerate(need(p))))]
        grades = {self.sections[s].grade_id for s, _g in info.targets if s in self.sections}
        if not grades:
            return []
        out = []
        for p in self.all_periods:
            ok = True
            for g in grades:
                per = self.periods[(g, d)]
                need = [p + i for i in range(info.duration)]
                if any(q not in per for q in need) or any(per[need[i]] != per[need[0]] + i for i in range(len(need))):
                    ok = False
                    break
            if ok:
                out.append(p)
        return out

    def _domain(self, info: CardInfo):
        if info.locked:
            info.domain = [info.cur]
            return
        other = [("section", s) for s, _g in info.targets] + [("subject", info.lesson.subject_id)]
        if info.room_id:
            other.append(("room", info.room_id))
        for d in range(len(self.days)):
            for p in self._starts_for(info, d):
                cells = {(d, p + i) for i in range(info.duration)}
                if any(cells & self.unavailable.get(k, set()) for k in other):
                    continue
                blockers = [t for t in info.teachers if cells & self.unavailable.get(("teacher", t), set())]
                info.domain.append((d, p))
                if blockers:
                    info.blocked_by_teacher[(d, p)] = blockers

    # ------------------------------------------------------------------ labels (Arabic)
    def section_label(self, sid) -> str:
        s = self.sections.get(sid)
        if s is None:
            return "?"
        g = self.grades[s.grade_id].name_ar
        return s.name_ar if s.name_ar.replace(" ", "").startswith(g.replace(" ", "")) else f"{g} / {s.name_ar}"

    def lesson_label(self, l: Lesson) -> str:
        if l.is_meeting:
            return l.label
        secs = "، ".join(self.section_label(t.section_id) + (f" ({self.groups[t.group_id].name_ar})" if t.group_id in self.groups else "")
                        for t in l.targets)
        who = "، ".join(self.teachers[t].name_ar for t in l.teacher_ids if t in self.teachers)
        return f"{self.subjects[l.subject_id].name_ar} — {secs}" + (f" ({who})" if who else "")

    def teacher_label(self, tid) -> str:
        t = self.teachers.get(tid)
        return f"{teacher_title(t.gender)} {t.name_ar}" if t else "?"


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------
class Built:
    def __init__(self):
        self.x = {}                # (card index, d, p) -> var
        self.placed = {}           # card index -> linear expr / var (1 if placed)
        self.assumptions = {}      # literal index -> (kind, payload)
        self.objective_terms = []


def build_model(pb: Problem, prm: dict, explain: bool = False):
    from ortools.sat.python import cp_model
    m = cp_model.CpModel()
    b = Built()
    lits = {}

    def lit(key, kind, payload):
        if key not in lits:
            v = m.NewBoolVar(f"a_{len(lits)}")
            lits[key] = v
            b.assumptions[v.Index()] = (kind, payload)
        return lits[key]

    # placement variables
    for i, c in enumerate(pb.cards):
        vs = []
        for (d, p) in c.domain:
            v = m.NewBoolVar(f"x{i}_{d}_{p}")
            b.x[(i, d, p)] = v
            vs.append(v)
            for t in c.blocked_by_teacher.get((d, p), []):
                if explain:
                    m.AddImplication(lit(("avail", t), "teacher_time_off", t), v.Not())
                else:
                    m.Add(v == 0)
        placed = sum(vs) if vs else 0
        b.placed[i] = placed
        if not vs:
            continue
        if c.locked:
            if explain:
                m.Add(placed == 1).OnlyEnforceIf(lit(("locked", c.id), "locked", c.id))
                m.Add(placed <= 1)
            else:
                m.Add(placed == 1)
        elif explain:
            m.Add(placed <= 1)
        elif prm["allow_unplaced"]:
            m.Add(placed <= 1)
            b.objective_terms.append((prm["w_unplaced"] * c.duration, 1 - placed))
        else:
            m.Add(placed == 1)
        if explain and not c.locked:
            m.Add(placed == 1).OnlyEnforceIf(lit(("lesson", c.lesson.id), "lesson", c.lesson.id))
        # hints: start from where the card is now
        if c.cur is not None and (i, *c.cur) in b.x:
            for (d, p) in c.domain:
                m.AddHint(b.x[(i, d, p)], 1 if (d, p) == c.cur else 0)
        if pb.mode == "repair" and c.cur is not None and not c.locked and not explain:
            stay = b.x.get((i, *c.cur))
            b.objective_terms.append((prm["w_move"], 1 - stay if stay is not None else 1))

    # cover[(resource, d, q, w)] -> list of vars occupying it
    def covering(i, c):
        for (d, p) in c.domain:
            v = b.x[(i, d, p)]
            for q in range(p, p + c.duration):
                yield d, q, v

    weeks_of = lambda c: pb.weeks if c.week_no is None else [c.week_no]  # noqa: E731
    teacher_slots = defaultdict(list)
    room_slots = defaultdict(list)
    section_whole = defaultdict(list)
    section_groups = defaultdict(lambda: defaultdict(list))   # (s, d, q, w) -> group -> vars
    pools = defaultdict(list)       # (frozenset rooms, d, q, w) -> vars
    for i, c in enumerate(pb.cards):
        subj = pb.subjects.get(c.lesson.subject_id)
        pool = None
        if not c.room_id and subj is not None and subj.rooms:
            allowed = frozenset(r.id for r in subj.rooms if not r.is_shared)
            if allowed and len(allowed) == len(subj.rooms):
                pool = allowed
        room = pb.rooms.get(c.room_id) if c.room_id else None
        for d, q, v in covering(i, c):
            for w in weeks_of(c):
                for t in c.teachers:
                    teacher_slots[(t, d, q, w)].append(v)
                if room is not None and not room.is_shared:
                    room_slots[(room.id, d, q, w)].append(v)
                if pool:
                    pools[(pool, d, q, w)].append(v)
                for s, g in c.targets:
                    if g is None:
                        section_whole[(s, d, q, w)].append(v)
                    else:
                        section_groups[(s, d, q, w)][g].append(v)
    for vs in teacher_slots.values():
        if len(vs) > 1:
            m.Add(sum(vs) <= 1)
    for vs in room_slots.values():
        if len(vs) > 1:
            m.Add(sum(vs) <= 1)
    for (pool, d, q, w), vs in pools.items():   # cards that may use any room of a set, plus cards fixed in those rooms
        used = [v for r in pool for v in room_slots.get((r, d, q, w), [])]
        if len(vs) + len(used) > len(pool):
            m.Add(sum(vs) + sum(used) <= len(pool))
    keys = set(section_whole) | set(section_groups)
    for key in keys:
        whole = section_whole.get(key, [])
        groups = section_groups.get(key, {})
        by_div = defaultdict(list)
        for g, vs in groups.items():
            if len(vs) > 1:
                m.Add(sum(vs) <= 1)
            div = pb.groups[g].division_id if g in pb.groups else g
            by_div[div].append(vs)
        if not groups:
            if len(whole) > 1:
                m.Add(sum(whole) <= 1)
            continue
        active = []
        for div, lists in by_div.items():
            flat = [v for vs in lists for v in vs]
            if len(lists) == 1 and len(flat) == 1:
                active.append(flat[0])
                continue
            y = m.NewBoolVar("")
            for v in flat:
                m.AddImplication(v, y)
            active.append(y)
        if len(whole) + len(active) > 1:
            m.Add(sum(whole) + sum(active) <= 1)

    # teacher busy / limits / soft goals
    by_teacher = defaultdict(list)
    for i, c in enumerate(pb.cards):
        for t in c.teachers:
            by_teacher[t].append(i)
    for t, idxs in by_teacher.items():
        teacher = pb.teachers.get(t)
        if teacher is None:
            continue
        day_used = []
        for d in range(len(pb.days)):
            busy = {}
            terms_day = []
            for q in pb.all_periods:
                vs = [v for w in pb.weeks for v in teacher_slots.get((t, d, q, w), [])]
                vs = list(dict.fromkeys(vs))
                if not vs:
                    continue
                bq = m.NewBoolVar("")
                m.AddMaxEquality(bq, vs)
                busy[q] = bq
                terms_day.append(bq)
            if not busy:
                continue
            if teacher.max_periods_per_day is not None:
                cond = lit(("maxday", t), "max_per_day", t) if explain else None
                ct = m.Add(sum(terms_day) <= teacher.max_periods_per_day)
                if cond is not None:
                    ct.OnlyEnforceIf(cond)
            if teacher.max_days_per_week is not None:
                u = m.NewBoolVar("")
                m.AddMaxEquality(u, terms_day)
                day_used.append(u)
            if explain:
                continue
            qs = sorted(busy)
            if prm["w_gaps"] and len(qs) > 2:
                before = {}
                prev = None
                for q in qs:
                    if prev is None:
                        before[q] = None
                    else:
                        bv = m.NewBoolVar("")
                        m.AddMaxEquality(bv, [busy[prev]] + ([before[prev]] if before[prev] is not None else []))
                        before[q] = bv
                    prev = q
                after = {}
                nxt = None
                for q in reversed(qs):
                    if nxt is None:
                        after[q] = None
                    else:
                        av = m.NewBoolVar("")
                        m.AddMaxEquality(av, [busy[nxt]] + ([after[nxt]] if after[nxt] is not None else []))
                        after[q] = av
                    nxt = q
                gaps = []
                for q in qs:
                    if before[q] is None or after[q] is None:
                        continue
                    gv = m.NewBoolVar("")
                    m.Add(gv >= before[q] + after[q] - busy[q] - 1)
                    gaps.append(gv)
                for gv in gaps:
                    b.objective_terms.append((prm["w_gaps"], gv))
                if teacher.max_gaps_per_day is not None and gaps:
                    over = m.NewIntVar(0, len(gaps), "")
                    m.Add(over >= sum(gaps) - teacher.max_gaps_per_day)
                    b.objective_terms.append((prm["w_daily_max"], over))
            if teacher.max_consecutive and prm["w_consecutive"]:
                k = teacher.max_consecutive
                for j in range(len(qs) - k):
                    window = qs[j:j + k + 1]
                    if window[-1] - window[0] != k:
                        continue
                    over = m.NewBoolVar("")
                    m.Add(sum(busy[q] for q in window) <= k + over)
                    b.objective_terms.append((prm["w_consecutive"], over))
        if teacher.max_days_per_week is not None and day_used:
            ct = m.Add(sum(day_used) <= teacher.max_days_per_week)
            if explain:
                ct.OnlyEnforceIf(lit(("maxdays", t), "max_days", t))

    # classes: no empty period before a later lesson (students' day stays compact, free periods at the end)
    if not explain and prm["w_class_gaps"]:
        for s_id in {s for s, _g in [t for c in pb.cards for t in c.targets]}:
            sec = pb.sections.get(s_id)
            if sec is None:
                continue
            for d in range(len(pb.days)):
                per = pb.periods.get((sec.grade_id, d), {})
                qs = sorted(per)
                busy = {}
                for q in qs:
                    vs = [v for w in pb.weeks for v in section_whole.get((s_id, d, q, w), [])]
                    vs += [v for w in pb.weeks for vv in section_groups.get((s_id, d, q, w), {}).values() for v in vv]
                    vs = list(dict.fromkeys(vs))
                    if vs:
                        bq = m.NewBoolVar("")
                        m.AddMaxEquality(bq, vs)
                        busy[q] = bq
                if len(busy) < 2:
                    continue
                after = None
                for q in reversed(qs):
                    if after is not None:
                        idle = m.NewBoolVar("")
                        m.Add(idle >= after - (busy[q] if q in busy else 0))
                        b.objective_terms.append((prm["w_class_gaps"], idle))
                    if q in busy:
                        nxt = m.NewBoolVar("")
                        m.AddMaxEquality(nxt, [busy[q]] + ([after] if after is not None else []))
                        after = nxt

    # a lesson's periods spread over different days
    if not explain and prm["w_spread"]:
        by_lesson = defaultdict(list)
        for i, c in enumerate(pb.cards):
            by_lesson[c.lesson.id].append(i)
        for lid, idxs in by_lesson.items():
            if len(idxs) < 2:
                continue
            per_day = -(-len(idxs) // len(pb.days))   # 6 periods in a 5-day week: up to 2 on one day
            for d in range(len(pb.days)):
                vs = [b.x[(i, dd, p)] for i in idxs for (dd, p) in pb.cards[i].domain if dd == d]
                if len(vs) > per_day:
                    extra = m.NewIntVar(0, len(vs), "")
                    m.Add(extra >= sum(vs) - per_day)
                    b.objective_terms.append((prm["w_spread"], extra))
    if not explain and b.objective_terms:
        m.Minimize(sum(w * e for w, e in b.objective_terms))
    if explain:
        m.AddAssumptions(list(lits.values()))
    return m, b


# ---------------------------------------------------------------------------
# Explaining infeasibility
# ---------------------------------------------------------------------------
def explain(pb: Problem, prm: dict, time_limit: float = 20) -> list[dict]:
    """The smallest set of requirements that cannot all be met, in Arabic."""
    from ortools.sat.python import cp_model
    m, b = build_model(pb, prm, explain=True)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = 1
    status = solver.Solve(m)
    if status != cp_model.INFEASIBLE:
        return []
    core = [b.assumptions[i] for i in solver.SufficientAssumptionsForInfeasibility() if i in b.assumptions]
    out = []
    for kind, payload in core:
        if kind == "lesson":
            l = pb.lessons[payload]
            n = sum(c.duration for c in pb.cards if c.lesson.id == payload)
            out.append({"kind": kind, "lesson_id": str(payload),
                        "message": f"وضع كل حصص «{pb.lesson_label(l)}» ({count(n, 'period')})"})
        elif kind == "teacher_time_off":
            out.append({"kind": kind, "teacher_id": str(payload),
                        "message": f"أوقات عدم التوفر لـ{pb.teacher_label(payload)}"})
        elif kind == "max_per_day":
            t = pb.teachers[payload]
            out.append({"kind": kind, "teacher_id": str(payload),
                        "message": f"الحد الأقصى اليومي لـ{pb.teacher_label(payload)} ({count(t.max_periods_per_day, 'period')})"})
        elif kind == "max_days":
            t = pb.teachers[payload]
            out.append({"kind": kind, "teacher_id": str(payload),
                        "message": f"أقصى عدد من أيام الدوام لـ{pb.teacher_label(payload)} ({count(t.max_days_per_week, 'day')})"})
        elif kind == "locked":
            c = next(c for c in pb.cards if c.id == payload)
            out.append({"kind": kind, "card_id": str(payload),
                        "message": f"الحصة المقفلة «{pb.lesson_label(c.lesson)}» يوم {pb.days[c.cur[0]].name_ar} الحصة {c.cur[1]}"})
    out.sort(key=lambda x: (x["kind"] != "lesson", x["message"]))
    return out


# ---------------------------------------------------------------------------
# Metrics (same for the source timetable and the result)
# ---------------------------------------------------------------------------
def metrics(pb: Problem, placement: dict) -> dict:
    """placement: card index -> (d, p) or None."""
    busy = defaultdict(set)
    per_lesson_day = defaultdict(int)
    total = placed = 0
    unplaced = []
    for i, c in enumerate(pb.cards):
        total += c.duration
        pos = placement.get(i)
        if pos is None:
            unplaced.append(i)
            continue
        placed += c.duration
        d, p = pos
        per_lesson_day[(c.lesson.id, d)] += 1
        for t in c.teachers:
            for q in range(p, p + c.duration):
                busy[(t, d)].add(q)
    gaps_by_teacher = defaultdict(int)
    max_day_gaps = 0
    over_daily = 0
    for (t, d), qs in busy.items():
        g = (max(qs) - min(qs) + 1) - len(qs)
        gaps_by_teacher[t] += g
        max_day_gaps = max(max_day_gaps, g)
        teacher = pb.teachers.get(t)
        if teacher and teacher.max_periods_per_day is not None and len(qs) > teacher.max_periods_per_day:
            over_daily += 1
    cards_per_lesson = defaultdict(int)
    for c in pb.cards:
        cards_per_lesson[c.lesson.id] += 1
    cap = {lid: -(-n // max(len(pb.days), 1)) for lid, n in cards_per_lesson.items()}
    doubles = sum(n - cap[lid] for (lid, _d), n in per_lesson_day.items() if n > cap[lid])
    worst = sorted(gaps_by_teacher.items(), key=lambda kv: -kv[1])[:10]
    lessons_unplaced = defaultdict(int)
    for i in unplaced:
        lessons_unplaced[pb.cards[i].lesson.id] += pb.cards[i].duration
    class_busy = defaultdict(set)
    for i, c in enumerate(pb.cards):
        pos = placement.get(i)
        if pos is None:
            continue
        for sid, _g in c.targets:
            for q in range(pos[1], pos[1] + c.duration):
                class_busy[(sid, pos[0])].add(q)
    class_idle = 0
    for (sid, d), qs in class_busy.items():
        sec = pb.sections.get(sid)
        first = min(pb.periods.get((sec.grade_id, d), {}) or [1]) if sec else 1
        class_idle += sum(1 for q in range(first, max(qs)) if q not in qs and (not sec or q in pb.periods.get((sec.grade_id, d), {})))
    return {
        "class_idle_periods": class_idle,
        "periods_total": total, "periods_placed": placed, "placed_ratio": round(placed / total, 4) if total else None,
        "teacher_gaps": sum(gaps_by_teacher.values()), "max_gaps_in_a_day": max_day_gaps,
        "same_day_repeats": doubles, "days_over_teacher_max": over_daily,
        "worst_gaps": [{"teacher": pb.teachers[t].name_ar, "gaps": n} for t, n in worst if n and t in pb.teachers],
        "unplaced": [{"lesson_id": str(lid), "label": pb.lesson_label(pb.lessons[lid]), "periods": n}
                     for lid, n in sorted(lessons_unplaced.items(), key=lambda kv: -kv[1])][:100],
    }


def current_placement(pb: Problem) -> dict:
    return {i: c.cur for i, c in enumerate(pb.cards) if c.cur is not None}


# ---------------------------------------------------------------------------
# Solve
# ---------------------------------------------------------------------------
@dataclass
class Outcome:
    status: str                     # solved / partial / infeasible / timeout / cancelled
    placement: dict
    objective: int | None
    wall: float
    solutions: int
    core: list = field(default_factory=list)
    message: str = ""


def solve(pb: Problem, prm: dict, on_progress=None, should_stop=None) -> Outcome:
    from ortools.sat.python import cp_model
    t0 = time.time()
    m, b = build_model(pb, prm)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(prm["time_limit"])
    solver.parameters.random_seed = int(prm["seed"])
    if prm["workers"]:
        solver.parameters.num_workers = int(prm["workers"])

    class Cb(cp_model.CpSolverSolutionCallback):
        def __init__(self):
            super().__init__()
            self.n = 0
            self.last = 0.0

        def on_solution_callback(self):
            self.n += 1
            now = time.time()
            if on_progress and now - self.last > 1.5:
                self.last = now
                on_progress({"solutions": self.n, "objective": int(self.ObjectiveValue()),
                             "bound": int(self.BestObjectiveBound()), "elapsed": round(now - t0, 1)})

    cb = Cb()
    stopper = None
    if should_stop is not None:
        import threading
        done = threading.Event()

        def watch():
            while not done.wait(2.0):
                try:
                    if should_stop():
                        solver.StopSearch()
                        return
                except Exception:   # never let the watcher crash the run
                    return
        stopper = threading.Thread(target=watch, daemon=True)
        stopper.start()
    status = solver.Solve(m, cb)
    if stopper is not None:
        done.set()
    wall = round(time.time() - t0, 1)
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        placement = {}
        for (i, d, p), v in b.x.items():
            if solver.Value(v):
                placement[i] = (d, p)
        unplaced = [i for i in range(len(pb.cards)) if i not in placement]
        st = "partial" if unplaced else "solved"
        return Outcome(st, placement, int(solver.ObjectiveValue()), wall, cb.n,
                       message="أفضل حل ممكن (مثالي)" if status == cp_model.OPTIMAL else "أفضل حل وُجد في المهلة المحددة")
    if status == cp_model.INFEASIBLE:
        return Outcome("infeasible", {}, None, wall, cb.n, message="لا يوجد حل يحقق كل الشروط")
    stopped = should_stop() if should_stop else False
    return Outcome("cancelled" if stopped else "timeout", {}, None, wall, cb.n,
                   message="أُوقف التوليد" if stopped else "انتهت المهلة قبل إيجاد أي حل؛ زد المهلة أو خفف القيود")


# ---------------------------------------------------------------------------
# Writing the result
# ---------------------------------------------------------------------------
def assign_pool_rooms(pb: Problem, placement: dict) -> dict:
    """Rooms for cards of subjects that may use any of several rooms, slot by slot (greedy)."""
    taken = defaultdict(set)    # (d, q, w) -> room ids
    for i, c in enumerate(pb.cards):
        if c.room_id and i in placement:
            d, p = placement[i]
            for q in range(p, p + c.duration):
                for w in (pb.weeks if c.week_no is None else [c.week_no]):
                    taken[(d, q, w)].add(c.room_id)
    out = {}
    for i, c in enumerate(pb.cards):
        subj = pb.subjects.get(c.lesson.subject_id)
        if c.room_id or i not in placement or subj is None or not subj.rooms:
            continue
        d, p = placement[i]
        cells = [(d, q, w) for q in range(p, p + c.duration) for w in (pb.weeks if c.week_no is None else [c.week_no])]
        for r in sorted(subj.rooms, key=lambda r: r.name_ar):
            if r.is_shared or all(r.id not in taken[x] for x in cells):
                out[i] = r.id
                if not r.is_shared:
                    for x in cells:
                        taken[x].add(r.id)
                break
    return out


def write_result(pb: Problem, placement: dict, target: Timetable, card_map: dict | None) -> None:
    """Put every card where the solution says (cards it could not place are left unplaced)."""
    from sqlalchemy import delete
    from app.models import Occupancy
    from app.rules.placement import rebuild_occupancy
    rooms = assign_pool_rooms(pb, placement)
    db.session.execute(delete(Occupancy).where(Occupancy.timetable_id == target.id))
    db.session.flush()
    cards = []
    for i, c in enumerate(pb.cards):
        card = card_map[c.id] if card_map else db.session.get(Card, c.id)
        pos = placement.get(i)
        if pos is None:
            if not c.locked:
                card.weekday_id, card.period_no = None, None
        else:
            card.weekday_id, card.period_no = pb.days[pos[0]].id, pos[1]
            if not card.room_id and (c.room_id or rooms.get(i)):
                card.room_id = c.room_id or rooms.get(i)
        cards.append(card)
    db.session.flush()
    for card in cards:
        rebuild_occupancy(card, card.lesson or db.session.get(Lesson, card.lesson_id), target)
    db.session.flush()


# ---------------------------------------------------------------------------
# Feasibility (instant, before solving)
# ---------------------------------------------------------------------------
def feasibility(tt: Timetable) -> list[dict]:
    from app.rules.validate import validate_timetable
    rep = validate_timetable(tt)
    keep = {"teacher_infeasible", "section_overloaded", "no_bell_schedule", "too_many_teachers"}
    out = [{"code": e["code"], "level": "error", "message": e["message"], "message_en": e.get("message_en")}
           for e in rep["errors"] if e["code"] in keep]
    # special rooms: periods that need one of a few rooms vs. what those rooms can hold in a week
    pb_days = db.session.scalars(select(Weekday).where(Weekday.is_school_day.is_(True))).all()
    need = defaultdict(int)
    for l in db.session.scalars(select(Lesson).where(Lesson.timetable_id == tt.id)):
        subj = l.subject
        if l.preferred_room_id is None and subj.rooms and all(not r.is_shared for r in subj.rooms):
            need[frozenset(r.id for r in subj.rooms)] += l.periods_per_week
    if need:
        periods = max((len(v) for v in (BellCache(tt.term_id).periods(g, d.id) or {} for g in db.session.scalars(select(Grade)) for d in pb_days)), default=0)
        for rooms, n in need.items():
            cap = len(rooms) * periods * len(pb_days)
            if n > cap:
                names = "، ".join(sorted(db.session.get(Room, r).name_ar for r in rooms))
                out.append({"code": "rooms_overloaded", "level": "error",
                            "message": f"القاعات ({names}): المطلوب {count(n, 'period')}، وسعتها في الأسبوع {count(cap, 'slot')} فقط",
                            "message_en": f"Rooms ({names}): {n} periods needed, only {cap} slots per week"})
    return out
