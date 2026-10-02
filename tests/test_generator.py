"""Automatic generator: full / repair / fill, hard rules respected, explanations when impossible."""
import pytest

from app.api.generator import run_generator
from app.extensions import db
from app.models import GeneratorRun


def _lesson(a, s, subject, teachers, targets, ppw, duration=1, room=None):
    body = {"timetable_id": s["tt"], "subject_id": s[subject], "periods_per_week": ppw, "duration": duration,
            "teachers": [s[t] for t in teachers], "targets": targets}
    if room:
        body["preferred_room_id"] = room
    return a.ok("post", "/api/lessons", body)


@pytest.fixture
def gen(school):
    a, s = school["api"], school
    d = a.ok("post", "/api/divisions", {"section_id": s["s5a"], "name": "بنين/بنات"})
    boys = a.ok("post", "/api/groups", {"division_id": d["id"], "name_ar": "بنين"})["id"]
    girls = a.ok("post", "/api/groups", {"division_id": d["id"], "name_ar": "بنات"})["id"]
    lab = a.ok("post", "/api/rooms", {"name_ar": "المختبر"})["id"]
    _lesson(a, s, "math", ["t1"], [{"section_id": s["s5a"]}], 5)
    _lesson(a, s, "math", ["t1"], [{"section_id": s["s5b"]}], 5)
    _lesson(a, s, "math", ["t1"], [{"section_id": s["s10a"]}], 4, duration=2)
    _lesson(a, s, "arabic", ["t2"], [{"section_id": s["s5a"]}], 6)
    _lesson(a, s, "arabic", ["t2"], [{"section_id": s["s5b"]}], 6, room=lab)
    _lesson(a, s, "arabic", ["t2"], [{"section_id": s["s10a"]}], 4, room=lab)
    _lesson(a, s, "pe", ["t_pe_m"], [{"section_id": s["s5a"], "group_id": boys}], 2)
    _lesson(a, s, "pe", ["t_pe_f"], [{"section_id": s["s5a"], "group_id": girls}], 2)
    return s


def run(app, a, s, **body):
    r = a.ok("post", f"/api/timetables/{s['tt']}/generator/runs", {"params": {"time_limit": 10, "workers": 2}, **body})
    if r["status"] == "queued":
        run_generator(app, __import__("uuid").UUID(r["id"]))
    return a.ok("get", f"/api/generator/runs/{r['id']}")


def test_feasibility_then_full_generation_is_valid(app, gen):
    a, s = gen["api"], gen
    f = a.ok("get", f"/api/timetables/{s['tt']}/generator/feasibility")
    assert f["ok"] and f["cards"] > 0 and f["placed"] == 0
    r = run(app, a, s)
    assert r["status"] == "solved", r
    after = r["metrics"]["after"]
    assert after["periods_placed"] == after["periods_total"] == 34
    assert after["same_day_repeats"] == 0
    new = r["result_timetable_id"]
    assert new and new != s["tt"]
    # the result passes the same validation as hand-made timetables
    v = a.ok("get", f"/api/timetables/{new}/validate")
    assert v["summary"]["errors"] == 0, v["errors"]
    # PE boys and girls run in parallel; the source draft is untouched
    cards = a.ok("get", f"/api/timetables/{s['tt']}/cards")["items"]
    assert all(c["weekday_id"] is None for c in cards)


def test_repair_and_fill_keep_existing_places(app, gen):
    a, s = gen["api"], gen
    first = run(app, a, s, target="same")
    assert first["status"] == "solved" and first["result_timetable_id"] == s["tt"]
    cards = a.ok("get", f"/api/timetables/{s['tt']}/cards")["items"]
    # add a lesson: fill places only the new cards
    _lesson(a, s, "arabic", ["t_pe_f"], [{"section_id": s["s5b"]}], 2)
    fill = run(app, a, s, mode="fill", target="same")
    assert fill["status"] == "solved" and fill["metrics"]["after"]["moved_cards"] == 0
    after = {c["id"]: (c["weekday_id"], c["period_no"]) for c in a.ok("get", f"/api/timetables/{s['tt']}/cards")["items"]}
    assert all(after[c["id"]] == (c["weekday_id"], c["period_no"]) for c in cards)
    rep = run(app, a, s, mode="repair", target="same")
    assert rep["status"] == "solved" and rep["metrics"]["after"]["moved_cards"] <= 6


def test_impossible_is_explained(app, gen):
    a, s = gen["api"], gen
    # Ahmad may only teach on Sunday: 14 periods + 2 doubles do not fit
    t = a.ok("get", f"/api/teachers/{s['t1']}")
    a.ok("patch", f"/api/teachers/{s['t1']}", {"version": t["version"], "max_days_per_week": 1})
    blocked = run(app, a, s)
    assert blocked["status"] == "feasibility_failed"               # caught by arithmetic before solving
    assert any("أحمد" in i["message"] for i in blocked["feasibility"])
    r = run(app, a, s, force=True)
    assert r["status"] == "partial"
    assert r["metrics"]["after"]["unplaced"]
    core = r["infeasible_core"]
    kinds = {c["kind"] for c in core}
    assert "max_days" in kinds and any("أحمد" in c["message"] for c in core)
    # strict mode: no partial result, the explanation alone
    r = run(app, a, s, force=True, params={"time_limit": 10, "allow_unplaced": False})
    assert r["status"] == "infeasible" and r["result_timetable_id"] is None and r["infeasible_core"]


def test_feasibility_failure_blocks_unless_forced(app, gen):
    a, s = gen["api"], gen
    _lesson(a, s, "math", ["t2"], [{"section_id": s["s5a"]}], 25)   # 5A now needs more periods than its week has
    r = a.ok("post", f"/api/timetables/{s['tt']}/generator/runs", {})
    assert r["status"] == "feasibility_failed" and any(i["code"] == "section_overloaded" for i in r["feasibility"])
    runs = a.ok("get", f"/api/timetables/{s['tt']}/generator/runs")["items"]
    assert len(runs) == 1
    assert a.ok("post", "/api/generator/runs/bulk-delete", {"ids": [runs[0]["id"]]})["deleted"] == 1


def test_stop_and_stale_runs(app, gen, ctx):
    a, s = gen["api"], gen
    r = a.ok("post", f"/api/timetables/{s['tt']}/generator/runs", {})
    assert a.ok("post", f"/api/generator/runs/{r['id']}/stop", {})["status"] == "cancelled"
    r = a.ok("post", f"/api/timetables/{s['tt']}/generator/runs", {})
    from datetime import timedelta
    from app.models.base import utcnow
    row = ctx.get(GeneratorRun, __import__("uuid").UUID(r["id"]))
    row.status, row.heartbeat_at = "running", utcnow() - timedelta(minutes=5)
    ctx.commit()
    assert a.ok("get", f"/api/generator/runs/{r['id']}")["status"] == "failed"
