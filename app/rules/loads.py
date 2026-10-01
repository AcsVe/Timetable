"""Conditional weekly-load rules (قواعد النصاب الأسبوعي).

A rule is a ConstraintRule with kind="weekly_load". Its params say whom it covers and what is expected:

    stage_ids / subject_ids / teacher_ids   who is covered (AND between the three kinds, OR inside one)
    mode       "exact" | "range" | "min" | "max" | "target" (each teacher's own نصاب)
    value / min / max / tolerance
    count      "all"   → every period the teacher teaches
               "scope" → only the periods of the covered subjects / stages
    basis      "assigned" (lessons) | "placed" (cards already in the timetable)
    display    "text" | "color" | "both"  — how the result is shown on screen
    colors     {"under", "ok", "over"}     texts {"under", "ok", "over"}

For each teacher the most specific rule wins (teacher > subject > stage > all teachers; a later rule
beats an earlier one of the same specificity). Teachers no rule covers fall back to their own
target_weekly_periods. Every rule also gets a summary of its group (subject / stage / list of teachers)."""
from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select

from app.arabic import count, g, teacher_title
from app.errors import ApiError
from app.extensions import db
from app.models import Card, ConstraintRule, Lesson, Section, Stage, Subject, Teacher, Timetable

KIND = "weekly_load"
MODES = ("exact", "range", "min", "max", "target")
DISPLAYS = ("text", "color", "both")
DEFAULT_COLORS = {"under": "#c2410c", "ok": "#15803d", "over": "#b91c1c"}
DEFAULT_TEXTS = {"under": ("نقص", "Under"), "ok": ("مكتمل", "Complete"), "over": ("زيادة", "Over")}


def _bad(field_, reason, message=None):
    d = {"field": f"params.{field_}", "reason": reason}
    if message:
        d["message"] = message
    return ApiError("validation", 400, details=d)


def _int(v, name, required=False):
    if v is None or v == "":
        if required:
            raise _bad(name, "required", "أدخل عدد الحصص")
        return None
    if isinstance(v, bool) or not isinstance(v, int) or v < 0 or v > 80:
        raise _bad(name, "integer 0–80")
    return v


def normalize_params(p: dict) -> dict:
    if not isinstance(p, dict):
        raise _bad("", "must be an object")
    out = {"name": str(p.get("name") or "").strip()[:120]}
    for k, model in (("stage_ids", Stage), ("subject_ids", Subject), ("teacher_ids", Teacher)):
        raw = p.get(k) or []
        if not isinstance(raw, list):
            raise _bad(k, "must be a list")
        ids = []
        for x in raw:
            try:
                u = uuid.UUID(str(x))
            except ValueError:
                raise _bad(k, "invalid uuid")
            if db.session.get(model, u) is None:
                raise _bad(k, "unknown_reference")
            ids.append(str(u))
        out[k] = list(dict.fromkeys(ids))
    mode = p.get("mode") or "exact"
    if mode not in MODES:
        raise _bad("mode", f"one of {list(MODES)}")
    out["mode"] = mode
    out["value"] = _int(p.get("value"), "value", required=mode == "exact")
    out["min"] = _int(p.get("min"), "min", required=mode in ("range", "min"))
    out["max"] = _int(p.get("max"), "max", required=mode in ("range", "max"))
    out["tolerance"] = _int(p.get("tolerance"), "tolerance") or 0
    if mode == "range" and out["min"] > out["max"]:
        raise _bad("max", "min > max", "يجب ألّا يقل الحد الأعلى عن الحد الأدنى")
    out["count"] = p.get("count") if p.get("count") in ("all", "scope") else "all"
    out["basis"] = p.get("basis") if p.get("basis") in ("assigned", "placed") else "assigned"
    out["display"] = p.get("display") if p.get("display") in DISPLAYS else "both"
    colors = p.get("colors") or {}
    texts = p.get("texts") or {}
    out["colors"], out["texts"], out["texts_en"] = {}, {}, {}
    for k in ("under", "ok", "over"):
        c = str(colors.get(k) or DEFAULT_COLORS[k])
        if not (len(c) in (4, 7) and c.startswith("#")):
            raise _bad(f"colors.{k}", "hex colour")
        out["colors"][k] = c
        out["texts"][k] = str(texts.get(k) or DEFAULT_TEXTS[k][0]).strip()[:40]
        out["texts_en"][k] = str((p.get("texts_en") or {}).get(k) or DEFAULT_TEXTS[k][1]).strip()[:40]
    return out


# ---------------------------------------------------------------------------
@dataclass
class Rule:
    id: str | None
    name: str
    params: dict
    order: int
    specificity: int = 0
    default: bool = False

    def covers(self, t: Teacher, t_subjects: set, t_stages: set) -> bool:
        p = self.params
        if p["teacher_ids"] and str(t.id) not in p["teacher_ids"]:
            return False
        if p["subject_ids"] and not (set(p["subject_ids"]) & t_subjects):
            return False
        if p["stage_ids"] and not (set(p["stage_ids"]) & t_stages):
            return False
        return True

    def bounds(self, t: Teacher) -> tuple[int | None, int | None]:
        p = self.params
        tol = p.get("tolerance") or 0
        m = p["mode"]
        if m == "exact":
            return p["value"] - tol, p["value"] + tol
        if m == "target":
            if t.target_weekly_periods is None:
                return None, None
            return t.target_weekly_periods - tol, t.target_weekly_periods + tol
        if m == "range":
            return p["min"], p["max"]
        if m == "min":
            return p["min"], None
        return None, p["max"]


def _expected_text(lo, hi, en=False) -> str:
    if lo is not None and hi is not None:
        return str(lo) if lo == hi else f"{lo}–{hi}"
    if lo is not None:
        return f"≥ {lo}" if en else f"{lo} على الأقل"
    if hi is not None:
        return f"≤ {hi}" if en else f"{hi} على الأكثر"
    return "—"


@dataclass
class LoadContext:
    tt: Timetable
    teachers: dict
    lessons: list
    sections: dict
    rules: list = field(default_factory=list)

    # periods per teacher, split by subject and stage so a rule can count only its scope
    def tally(self):
        assigned = defaultdict(list)   # tid -> [(subject_id, stage_ids, assigned, placed)]
        placed_by_lesson = defaultdict(int)
        for c in db.session.scalars(select(Card).where(Card.timetable_id == self.tt.id, Card.weekday_id.is_not(None))):
            placed_by_lesson[c.lesson_id] += c.duration
        for l in self.lessons:
            stages = set()
            for tg in l.targets:
                s = self.sections.get(tg.section_id)
                if s is not None:
                    stages.add(str(s.grade.stage_id))
            for tid in l.teacher_ids:
                assigned[tid].append((str(l.subject_id), stages, l.periods_per_week, placed_by_lesson.get(l.id, 0)))
        return assigned


def _rules(tt: Timetable) -> list[Rule]:
    rows = db.session.scalars(select(ConstraintRule).where(
        ConstraintRule.timetable_id == tt.id, ConstraintRule.kind == KIND, ConstraintRule.is_active.is_(True))
        .order_by(ConstraintRule.created_at)).all()
    out = []
    for i, r in enumerate(rows):
        try:
            p = normalize_params(r.params or {})
        except ApiError:
            continue   # a rule pointing at something deleted since: ignore it rather than fail the page
        spec = (4 if p["teacher_ids"] else 0) + (2 if p["subject_ids"] else 0) + (1 if p["stage_ids"] else 0)
        out.append(Rule(str(r.id), p["name"], p, i, spec))
    return out


def _default_rule() -> Rule:
    p = {"name": "", "stage_ids": [], "subject_ids": [], "teacher_ids": [], "mode": "target", "value": None,
         "min": None, "max": None, "tolerance": 0, "count": "all", "basis": "assigned", "display": "both",
         "colors": dict(DEFAULT_COLORS), "texts": {k: v[0] for k, v in DEFAULT_TEXTS.items()},
         "texts_en": {k: v[1] for k, v in DEFAULT_TEXTS.items()}}
    return Rule(None, "", p, -1, -1, True)


def evaluate(tt: Timetable, lang: str = "ar") -> dict:
    teachers = {t.id: t for t in db.session.scalars(select(Teacher))}
    lessons = list(db.session.scalars(select(Lesson).where(Lesson.timetable_id == tt.id)))
    sections = {s.id: s for s in db.session.scalars(select(Section))}
    ctx = LoadContext(tt, teachers, lessons, sections)
    tally = ctx.tally()
    rules = _rules(tt)
    default = _default_rule()
    subjects = {str(s.id): s for s in db.session.scalars(select(Subject))}
    stages = {str(s.id): s for s in db.session.scalars(select(Stage))}

    rows = []
    by_rule = defaultdict(list)
    for tid, t in sorted(teachers.items(), key=lambda kv: kv[1].name_ar):
        items = tally.get(tid, [])
        t_subjects = {s for s, _st, _a, _p in items} | {str(s.id) for s in t.subjects}
        t_stages = {x for _s, st, _a, _p in items for x in st} | {str(s.id) for s in t.stages}
        covering = [r for r in rules if r.covers(t, t_subjects, t_stages)]
        rule = max(covering, key=lambda r: (r.specificity, r.order)) if covering else default
        p = rule.params
        lo, hi = rule.bounds(t)
        if rule.default and lo is None and hi is None:
            if not items:
                continue
        in_scope = items
        if p["count"] == "scope":
            in_scope = [x for x in items if (not p["subject_ids"] or x[0] in p["subject_ids"])
                        and (not p["stage_ids"] or set(p["stage_ids"]) & x[1])]
        assigned = sum(x[2] for x in in_scope)
        placed = sum(x[3] for x in in_scope)
        actual = placed if p["basis"] == "placed" else assigned
        if lo is None and hi is None:
            status, delta = "none", 0
        elif lo is not None and actual < lo:
            status, delta = "under", lo - actual
        elif hi is not None and actual > hi:
            status, delta = "over", actual - hi
        else:
            status, delta = "ok", 0
        name = f"{teacher_title(t.gender)} {t.name_ar}"
        name_en = t.name_en or t.name_ar
        exp, exp_en = _expected_text(lo, hi), _expected_text(lo, hi, True)
        label = p["texts"].get(status, "") if status != "none" else ""
        label_en = p["texts_en"].get(status, "") if status != "none" else ""
        if status == "under":
            msg = f"{name}: {label} — {actual} من {exp}، بنقص {count(delta, 'period', 'gen')}"
            msg_en = f"{name_en}: {label_en} — {actual} of {exp_en}, {delta} short"
        elif status == "over":
            msg = f"{name}: {label} — {actual} من {exp}، بزيادة {count(delta, 'period', 'gen')}"
            msg_en = f"{name_en}: {label_en} — {actual} of {exp_en}, {delta} over"
        elif status == "ok":
            msg = f"{name}: {label} — {actual} من {exp}"
            msg_en = f"{name_en}: {label_en} — {actual} of {exp_en}"
        else:
            msg = f"{name}: {g(t.gender, 'لم يُحدَّد له نصاب', 'لم يُحدَّد لها نصاب')}"
            msg_en = f"{name_en}: no target set"
        row = {
            "teacher_id": str(t.id), "name": t.name_ar, "name_en": t.name_en, "gender": t.gender,
            "assigned": assigned, "placed": placed, "actual": actual, "min": lo, "max": hi,
            "expected": exp, "expected_en": exp_en, "status": status, "delta": delta,
            "label": label, "label_en": label_en, "color": p["colors"].get(status) if status != "none" else None,
            "display": p["display"], "rule_id": rule.id, "rule_name": rule.name, "default_rule": rule.default,
            "basis": p["basis"], "message": msg, "message_en": msg_en,
            "subjects": sorted({subjects[s].name_ar for s, *_ in items if s in subjects}),
        }
        rows.append(row)
        by_rule[rule.id].append(row)

    groups = []
    for r in rules:
        members = by_rule.get(r.id, [])
        p = r.params
        scope = []
        if p["stage_ids"]:
            scope.append(("المرحلة", "Stage", [stages[x].name_ar for x in p["stage_ids"] if x in stages]))
        if p["subject_ids"]:
            scope.append(("المبحث", "Subject", [subjects[x].name_ar for x in p["subject_ids"] if x in subjects]))
        if p["teacher_ids"]:
            scope.append(("المعلمون", "Teachers", [teachers[uuid.UUID(x)].name_ar for x in p["teacher_ids"]
                                                    if uuid.UUID(x) in teachers]))
        lo_sum = sum(m["min"] for m in members if m["min"] is not None) if all(m["min"] is not None for m in members) else None
        hi_sum = sum(m["max"] for m in members if m["max"] is not None) if all(m["max"] is not None for m in members) else None
        actual = sum(m["actual"] for m in members)
        n = {k: sum(1 for m in members if m["status"] == k) for k in ("under", "ok", "over", "none")}
        if not members:
            status = "none"
        elif lo_sum is not None and actual < lo_sum:
            status = "under"
        elif hi_sum is not None and actual > hi_sum:
            status = "over"
        else:
            status = "under" if n["under"] else "over" if n["over"] else "ok"
        scope_txt = "، ".join(f"{a}: {'، '.join(v)}" for a, _e, v in scope if v) or "جميع المعلمين"
        scope_en = "; ".join(f"{e}: {', '.join(v)}" for _a, e, v in scope if v) or "All teachers"
        exp = _expected_text(lo_sum, hi_sum)
        msg = (f"{r.name or scope_txt}: {p['texts'][status] if status != 'none' else 'لا يشمل أحداً'} — "
               f"{actual} من {exp}؛ {p['texts']['ok']}: {n['ok']}، {p['texts']['under']}: {n['under']}، {p['texts']['over']}: {n['over']}"
               if members else f"{r.name or scope_txt}: لا ينطبق على أي معلم")
        groups.append({
            "rule_id": r.id, "name": r.name, "scope": scope_txt, "scope_en": scope_en,
            "teachers": len(members), "actual": actual, "min": lo_sum, "max": hi_sum, "expected": exp,
            "counts": n, "status": status, "color": p["colors"].get(status), "display": p["display"],
            "label": p["texts"].get(status, ""), "message": msg,
        })

    summary = {k: sum(1 for r in rows if r["status"] == k) for k in ("under", "ok", "over", "none")}
    return {"timetable_id": str(tt.id), "teachers": rows, "groups": groups, "summary": summary,
            "rules": len(rules)}


def statuses_by_teacher(tt: Timetable) -> dict[str, dict]:
    return {r["teacher_id"]: r for r in evaluate(tt)["teachers"]}
