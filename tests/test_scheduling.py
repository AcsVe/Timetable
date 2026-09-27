"""Lessons, cards, conflict rules, validation, timetable lifecycle."""
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.extensions import db


def lesson(s, subject, teachers, targets, ppw=1, duration=1, **extra):
    body = {"timetable_id": s["tt"], "subject_id": s[subject], "periods_per_week": ppw, "duration": duration,
            "teachers": [s[t] for t in teachers], "targets": targets, **extra}
    return s["api"].ok("post", "/api/lessons", body)


def place(s, card, day_dow, period, expect=200, **extra):
    body = {"version": card["version"], "weekday_id": s["days"][day_dow], "period_no": period, **extra}
    r = s["api"].patch(f"/api/cards/{card['id']}", body)
    assert r.status_code == expect, r.get_json()
    return r.get_json()


def sec(s, key, group=None):
    return {"section_id": s[key], "group_id": group}


# -- cards generation ---------------------------------------------------------
@pytest.mark.parametrize("ppw,dur,expected", [(5, 1, [1] * 5), (4, 2, [2, 2]), (5, 2, [2, 2, 1])])
def test_lesson_generates_cards(school, ppw, dur, expected):
    l = lesson(school, "math", ["t2"], [sec(school, "s5a")], ppw=ppw, duration=dur)
    assert sorted((c["duration"] for c in l["cards"]), reverse=True) == expected
    assert all(c["weekday_id"] is None for c in l["cards"])


def test_changing_periods_keeps_placed_cards(school):
    l = lesson(school, "math", ["t2"], [sec(school, "s5a")], ppw=3)
    placed = place(school, l["cards"][0], 7, 1)
    l2 = school["api"].ok("patch", f"/api/lessons/{l['id']}", {"version": l["version"], "periods_per_week": 1})
    assert [c["id"] for c in l2["cards"]] == [placed["id"]] and l2["cards_removed"] == 2


# -- teacher conflicts ----------------------------------------------------------
def test_teacher_conflict_across_stages_by_period_number(school):
    a = lesson(school, "math", ["t1"], [sec(school, "s5a")])
    b = lesson(school, "math", ["t1"], [sec(school, "s10a")])  # secondary: different bell times, same period no.
    place(school, a["cards"][0], 7, 2)
    r = place(school, b["cards"][0], 7, 2, expect=409)
    assert r["error"] == "placement_conflict" and r["details"][0]["code"] == "teacher_busy"
    assert "أحمد" in r["message"]
    place(school, b["cards"][0], 7, 3)  # other period is fine


def test_double_lesson_overlaps_by_range(school):
    a = lesson(school, "math", ["t2"], [sec(school, "s5a")], ppw=2, duration=2)
    b = lesson(school, "arabic", ["t2"], [sec(school, "s5b")])
    place(school, a["cards"][0], 7, 1)  # periods 1–2
    assert place(school, b["cards"][0], 7, 2, expect=409)["details"][0]["code"] == "teacher_busy"


def test_database_guard_rejects_double_booking_even_if_code_is_bypassed(school, app):
    a = lesson(school, "math", ["t2"], [sec(school, "s5a")])
    placed = place(school, a["cards"][0], 7, 1)
    with app.app_context():
        with pytest.raises(IntegrityError) as ei:
            db.session.execute(text(
                "INSERT INTO occupancy (timetable_id, card_id, resource_type, resource_id, weekday_id, periods, weeks) "
                "VALUES (:tt, :card, 'teacher', :t, :wd, int4range(1,2), int4range(1,2))"),
                {"tt": school["tt"], "card": placed["id"], "t": school["t2"], "wd": school["days"][7]})
        assert "ex_occupancy_no_overlap" in str(ei.value)
        db.session.rollback()


# -- class / group rules -------------------------------------------------------
def _pe_division(s):
    a = s["api"]
    d = a.ok("post", "/api/divisions", {"section_id": s["s5a"], "name": "أولاد/بنات"})
    boys = a.ok("post", "/api/groups", {"division_id": d["id"], "name_ar": "أولاد"})["id"]
    girls = a.ok("post", "/api/groups", {"division_id": d["id"], "name_ar": "بنات"})["id"]
    d2 = a.ok("post", "/api/divisions", {"section_id": s["s5a"], "name": "موسيقى/دراما"})
    music = a.ok("post", "/api/groups", {"division_id": d2["id"], "name_ar": "موسيقى"})["id"]
    return boys, girls, music


def test_boys_and_girls_pe_share_a_period_with_two_teachers(school):
    boys, girls, _ = _pe_division(school)
    lb = lesson(school, "pe", ["t_pe_m"], [sec(school, "s5a", boys)])
    lg = lesson(school, "pe", ["t_pe_f"], [sec(school, "s5a", girls)])
    place(school, lb["cards"][0], 1, 4)
    place(school, lg["cards"][0], 1, 4)  # same division, different groups → allowed


def test_groups_from_different_divisions_conflict(school):
    boys, _, music = _pe_division(school)
    lb = lesson(school, "pe", ["t_pe_m"], [sec(school, "s5a", boys)])
    lm = lesson(school, "arabic", ["t2"], [sec(school, "s5a", music)])
    place(school, lb["cards"][0], 1, 4)
    assert place(school, lm["cards"][0], 1, 4, expect=409)["details"][0]["code"] == "class_busy"


def test_whole_section_conflicts_with_any_group(school):
    boys, _, _ = _pe_division(school)
    lb = lesson(school, "pe", ["t_pe_m"], [sec(school, "s5a", boys)])
    lw = lesson(school, "math", ["t2"], [sec(school, "s5a")])
    place(school, lw["cards"][0], 2, 1)
    assert place(school, lb["cards"][0], 2, 1, expect=409)["details"][0]["code"] == "class_busy"


def test_joint_lesson_blocks_both_sections(school):
    joint = lesson(school, "arabic", ["t2"], [sec(school, "s5a"), sec(school, "s5b")])
    other = lesson(school, "math", ["t1"], [sec(school, "s5b")])
    place(school, joint["cards"][0], 3, 5)
    assert place(school, other["cards"][0], 3, 5, expect=409)["details"][0]["code"] == "class_busy"


def test_two_teachers_on_one_card_needs_subject_permission(school):
    r = school["api"].post("/api/lessons", {"timetable_id": school["tt"], "subject_id": school["pe"],
                                            "periods_per_week": 1, "teachers": [school["t_pe_m"], school["t_pe_f"]],
                                            "targets": [sec(school, "s5a")]})
    assert r.status_code == 400 and r.get_json()["details"]["reason"] == "too_many_teachers"
    pe = school["api"].ok("get", f"/api/subjects/{school['pe']}")
    school["api"].ok("patch", f"/api/subjects/{pe['id']}", {"version": pe["version"], "max_teachers_per_block": 2})
    l = lesson(school, "pe", ["t_pe_m", "t_pe_f"], [sec(school, "s5a")])
    place(school, l["cards"][0], 7, 6)
    other = lesson(school, "math", ["t_pe_f"], [sec(school, "s5b")])
    assert place(school, other["cards"][0], 7, 6, expect=409)["details"][0]["code"] == "teacher_busy"


# -- bells, breaks, availability, locks ---------------------------------------------
def test_double_cannot_span_break_and_period_must_exist(school):
    l = lesson(school, "math", ["t2"], [sec(school, "s5a")], ppw=2, duration=2)
    assert place(school, l["cards"][0], 7, 3, expect=409)["details"][0]["code"] == "crosses_break"
    assert place(school, l["cards"][0], 7, 6, expect=409)["details"][0]["code"] == "period_not_in_schedule"
    assert place(school, l["cards"][0], 5, 1, expect=409)["details"][0]["code"] == "not_school_day"
    place(school, l["cards"][0], 7, 4)


def test_grade_specific_bell_overrides_stage(school):
    a = school["api"]
    short = a.ok("post", "/api/bell-schedules", {"name_ar": "قصير", "slots": [
        {"slot_no": 1, "kind": "lesson", "period_no": 1, "starts_at": "08:00", "ends_at": "08:40"},
        {"slot_no": 2, "kind": "lesson", "period_no": 2, "starts_at": "08:40", "ends_at": "09:20"}]})["id"]
    a.ok("post", "/api/bell-assignments/bulk", {"term_id": school["term"], "stage_id": school["basic"],
                                                 "grade_ids": [school["g5"]], "bell_schedule_id": short,
                                                 "weekday_ids": [school["days"][4]]})
    l = lesson(school, "math", ["t2"], [sec(school, "s5a")])
    assert place(school, l["cards"][0], 4, 3, expect=409)["details"][0]["code"] == "period_not_in_schedule"
    place(school, l["cards"][0], 7, 3)  # other days still use the stage schedule


def test_teacher_time_off(school):
    school["api"].ok("post", "/api/availability", {"timetable_id": school["tt"], "entity_type": "teacher",
                                                   "entity_id": school["t2"], "weekday_id": school["days"][2],
                                                   "period_no": 1})
    l = lesson(school, "math", ["t2"], [sec(school, "s5a")])
    r = place(school, l["cards"][0], 2, 1, expect=409)
    assert r["details"][0]["code"] == "unavailable"


def test_locked_card_cannot_move(school):
    l = lesson(school, "math", ["t2"], [sec(school, "s5a")])
    c = place(school, l["cards"][0], 7, 1, is_locked=True)
    r = school["api"].patch(f"/api/cards/{c['id']}", {"version": c["version"], "weekday_id": school["days"][1],
                                                      "period_no": 1})
    assert r.status_code == 409 and r.get_json()["details"]["reason"] == "card_locked"
    place(school, c, 1, 1, is_locked=False)


def test_unplace_frees_the_teacher(school):
    a = lesson(school, "math", ["t2"], [sec(school, "s5a")])
    b = lesson(school, "arabic", ["t2"], [sec(school, "s5b")])
    ca = place(school, a["cards"][0], 7, 1)
    school["api"].ok("patch", f"/api/cards/{ca['id']}", {"version": ca["version"], "weekday_id": None,
                                                        "period_no": None})
    place(school, b["cards"][0], 7, 1)


def test_changing_lesson_teacher_rechecks_placed_cards(school):
    a = lesson(school, "math", ["t1"], [sec(school, "s5a")])
    b = lesson(school, "arabic", ["t2"], [sec(school, "s5b")])
    place(school, a["cards"][0], 7, 1)
    place(school, b["cards"][0], 7, 1)
    b = school["api"].ok("get", f"/api/lessons/{b['id']}")
    r = school["api"].patch(f"/api/lessons/{b['id']}", {"version": b["version"], "teachers": [school["t1"]]})
    assert r.status_code == 409 and r.get_json()["details"][0]["code"] == "teacher_busy"
    # nothing changed
    assert school["api"].ok("get", f"/api/lessons/{b['id']}")["teachers"][0]["teacher_id"] == school["t2"]


def test_room_conflict_and_type(school):
    a = school["api"]
    lab = a.ok("post", "/api/rooms", {"name_ar": "مختبر", "room_type": "lab"})["id"]
    gym = a.ok("post", "/api/rooms", {"name_ar": "الملعب", "room_type": "gym", "is_shared": True})["id"]
    l1 = lesson(school, "math", ["t1"], [sec(school, "s5a")])
    l2 = lesson(school, "arabic", ["t2"], [sec(school, "s5b")])
    place(school, l1["cards"][0], 7, 1, room_id=lab)
    assert place(school, l2["cards"][0], 7, 1, expect=409, room_id=lab)["details"][0]["code"] == "room_busy"
    pe = a.ok("get", f"/api/subjects/{school['pe']}")
    a.ok("patch", f"/api/subjects/{pe['id']}", {"version": pe["version"], "requires_room_type": "gym"})
    l3 = lesson(school, "pe", ["t_pe_m"], [sec(school, "s5b")])
    assert place(school, l3["cards"][0], 7, 2, expect=409, room_id=lab)["details"][0]["code"] == "room_type_mismatch"
    l4 = lesson(school, "pe", ["t_pe_f"], [sec(school, "s5a")])
    place(school, l3["cards"][0], 7, 2, room_id=gym)
    place(school, l4["cards"][0], 7, 2, room_id=gym)  # shared room holds both


# -- drag & drop helpers ----------------------------------------------------------
def test_check_and_allowed_slots(school):
    a = lesson(school, "math", ["t2"], [sec(school, "s5a")])
    b = lesson(school, "arabic", ["t2"], [sec(school, "s5b")])
    place(school, a["cards"][0], 7, 1)
    chk = school["api"].ok("post", f"/api/cards/{b['cards'][0]['id']}/check",
                           {"weekday_id": school["days"][7], "period_no": 1})
    assert chk["ok"] is False and chk["conflicts"][0]["code"] == "teacher_busy"
    grid = school["api"].ok("get", f"/api/cards/{b['cards'][0]['id']}/allowed-slots")
    assert len(grid["days"]) == 5 and len(grid["days"][0]["periods"]) == 6
    sunday = grid["days"][0]["periods"]
    assert sunday[0]["ok"] is False and sunday[0]["codes"] == ["teacher_busy"]
    assert all(c["ok"] for c in sunday[1:])


# -- validation report --------------------------------------------------------------
def test_validation_report(school):
    a = school["api"]
    t1 = a.ok("get", f"/api/teachers/{school['t1']}")
    a.ok("patch", f"/api/teachers/{t1['id']}", {"version": t1["version"], "target_weekly_periods": 2,
                                                  "max_periods_per_day": 1})
    l = lesson(school, "math", ["t1"], [sec(school, "s5a")], ppw=3)
    place(school, l["cards"][0], 7, 1)
    place(school, l["cards"][1], 7, 2)
    rep = a.ok("get", f"/api/timetables/{school['tt']}/validate")
    codes = {w["code"] for w in rep["warnings"]}
    assert {"unplaced", "teacher_over_target", "teacher_max_per_day"} <= codes
    assert rep["summary"]["periods_placed"] == 2 and rep["summary"]["periods_total"] == 3


def test_feasibility_section_overloaded(school):
    lesson(school, "math", ["t1"], [sec(school, "s5a")], ppw=20)
    lesson(school, "arabic", ["t2"], [sec(school, "s5a")], ppw=11)  # 31 > 5 days × 6 periods
    rep = school["api"].ok("get", f"/api/timetables/{school['tt']}/validate")
    err = [e for e in rep["errors"] if e["code"] == "section_overloaded"]
    assert err and err[0]["required"] == 31 and err[0]["available"] == 30


def test_bell_change_surfaces_in_validation_not_silently(school):
    a = school["api"]
    l = lesson(school, "math", ["t2"], [sec(school, "s5a")])
    place(school, l["cards"][0], 7, 6)
    bell = a.ok("get", f"/api/bell-schedules/{school['bell_basic']}")
    a.ok("patch", f"/api/bell-schedules/{bell['id']}", {"version": bell["version"], "slots": bell["slots"][:-1]})
    rep = a.ok("get", f"/api/timetables/{school['tt']}/validate")
    assert any(e["code"] == "period_not_in_schedule" for e in rep["errors"])


# -- lifecycle --------------------------------------------------------------------------
def test_copy_publish_archive(school):
    a = school["api"]
    l = lesson(school, "math", ["t2"], [sec(school, "s5a")], ppw=2)
    place(school, l["cards"][0], 7, 1, is_locked=True)
    copy = a.ok("post", f"/api/timetables/{school['tt']}/copy", {"name": "مسودة 2"})
    assert copy["cards_copied"] == 2 and copy["based_on_id"] == school["tt"]
    cards = a.ok("get", f"/api/timetables/{copy['id']}/cards")["items"]
    assert sum(1 for c in cards if c["weekday_id"]) == 1 and any(c["is_locked"] for c in cards)
    # independent occupancy: same teacher/slot is free in the copy only for its own cards
    tt1 = a.ok("get", f"/api/timetables/{school['tt']}")
    a.ok("post", f"/api/timetables/{school['tt']}/publish", {"version": tt1["version"]})
    tt2 = a.ok("get", f"/api/timetables/{copy['id']}")
    a.ok("post", f"/api/timetables/{copy['id']}/publish", {"version": tt2["version"]})
    assert a.ok("get", f"/api/timetables/{school['tt']}")["status"] == "archived"
    # archived timetables are read-only
    old = [c for c in a.ok("get", f"/api/timetables/{school['tt']}/cards")["items"] if not c["weekday_id"]][0]
    r = a.patch(f"/api/cards/{old['id']}", {"version": old["version"], "weekday_id": school["days"][1],
                                            "period_no": 1})
    assert r.status_code == 409 and r.get_json()["error"] == "timetable_readonly"


def test_publish_refuses_timetable_with_errors(school):
    lesson(school, "math", ["t1"], [sec(school, "s5a")], ppw=31)
    tt = school["api"].ok("get", f"/api/timetables/{school['tt']}")
    r = school["api"].post(f"/api/timetables/{school['tt']}/publish", {"version": tt["version"]})
    assert r.status_code == 409 and r.get_json()["details"]["reason"] == "timetable_has_errors"
    school["api"].ok("post", f"/api/timetables/{school['tt']}/publish", {"version": tt["version"], "force": True})


def test_delete_lesson_frees_slots(school):
    a = lesson(school, "math", ["t2"], [sec(school, "s5a")])
    b = lesson(school, "arabic", ["t2"], [sec(school, "s5b")])
    place(school, a["cards"][0], 7, 1)
    school["api"].ok("delete", f"/api/lessons/{a['id']}?version={a['version']}")
    place(school, b["cards"][0], 7, 1)
