"""Holiday calendar and period plans: periods of the term, filling from the weekly plan, approval, and
the comparison with the timetable, absences and teacher loads."""
from datetime import date

import pytest

START, END = "2026-10-04", "2026-10-29"     # Sunday … Thursday: 4 weeks × 5 days = 20 days


@pytest.fixture
def planned(school):
    a, s = school["api"], school
    term = a.ok("get", f"/api/terms/{s['term']}")
    a.ok("patch", f"/api/terms/{s['term']}", {"version": term["version"], "start_date": START, "end_date": END})
    a.ok("post", "/api/holidays", {"name_ar": "عطلة رسمية", "date_from": "2026-10-15", "date_to": "2026-10-15"})
    a.ok("post", "/api/holidays", {"name_ar": "يوم نشاط", "date_from": "2026-10-20", "date_to": "2026-10-20",
                                   "kind": "activity", "stage_ids": [s["basic"]]})
    a.ok("put", "/api/curriculum/bulk", {"items": [{"grade_id": s["g5"], "subject_id": s["math"], "periods_per_week": 5}]})
    l = a.ok("post", "/api/lessons", {"timetable_id": s["tt"], "subject_id": s["math"], "periods_per_week": 5,
                                      "teachers": [s["t1"]], "targets": [{"section_id": s["s5a"]}]})
    for c, dow in zip(sorted(l["cards"], key=lambda c: c["created_at"]), (7, 1, 2, 3, 4)):
        a.ok("patch", f"/api/cards/{c['id']}", {"version": c["version"], "weekday_id": s["days"][dow], "period_no": 1})
    s["math_cards"] = {dow: c["id"] for c, dow in zip(sorted(l["cards"], key=lambda c: c["created_at"]), (7, 1, 2, 3, 4))}
    return s


def _analysis(a, s, plan, **q):
    qs = "&".join(f"{k}={v}" for k, v in {"timetable_id": s["tt"], "today": "2026-10-31", **q}.items())
    return a.ok("get", f"/api/plans/{plan['id']}/analysis?{qs}")


def test_term_plan_from_weekly_plan_with_holidays_absence_and_load(planned):
    a, s = planned["api"], planned
    plan = a.ok("post", "/api/plans", {"name": "خطة الفصل الأول", "term_id": s["term"], "stage_id": s["basic"],
                                       "period_type": "term"})
    per = a.ok("get", f"/api/plans/{plan['id']}/periods")
    assert per["school_days"] == 18 and per["all_days"] == 20 and len(per["periods"]) == 1   # 2 holidays for the basic stage
    r = a.ok("post", f"/api/plans/{plan['id']}/fill-weekly", {})
    key = f"{s['g5']}:{s['math']}"
    assert r["targets"][key] == {"term": 18}                     # 5 a week × 18 days ÷ 5
    # absent on Monday 5/10 (not covered) and Tuesday 6/10 (covered by a substitute)
    a.ok("post", "/api/absences", {"teacher_id": s["t1"], "date_from": "2026-10-05", "date_to": "2026-10-06"})
    a.ok("post", "/api/substitutions", {"timetable_id": s["tt"], "date": "2026-10-06", "card_id": s["math_cards"][2],
                                        "period_no": 1, "original_teacher_id": s["t1"], "substitute_teacher_id": s["t2"],
                                        "kind": "cover"})
    rep = _analysis(a, s, plan)
    row = next(x for x in rep["rows"] if x["section_id"] == s["s5a"] and x["subject_id"] == s["math"])
    assert (row["required"], row["scheduled"], row["status"]) == (18, 18, "ok")
    assert (row["lost"], row["covered"], row["due"], row["delivered"]) == (2, 1, 18, 16)
    other = next(x for x in rep["rows"] if x["section_id"] == s["s5b"] and x["subject_id"] == s["math"])
    assert other["status"] == "under" and other["scheduled"] == 0
    t1 = next(x for x in rep["teachers"] if x["teacher_id"] == s["t1"])
    # weekly load 20 × 19 school days (the all-stage holiday only) ÷ 5 = 76
    assert t1["quota"] == 76 and t1["scheduled"] == 18 and t1["status"] == "under" and t1["lost"] == 2
    # as of an earlier day only the past is due
    early = _analysis(a, s, plan, today="2026-10-08")
    row = next(x for x in early["rows"] if x["section_id"] == s["s5a"] and x["subject_id"] == s["math"])
    assert row["due"] == 5 and row["delivered"] == 3 and row["required_due"] == 5     # 18 × 5 of 18 days
    # reports
    for kind in ("plan-sections", "plan-teachers"):
        j = a.ok("get", f"/api/timetables/{s['tt']}/reports/{kind}?plan_id={plan['id']}")
        assert j["tables"][0]["rows"]
        for fmt in ("pdf", "xlsx"):
            assert a.get(f"/api/timetables/{s['tt']}/reports/{kind}?plan_id={plan['id']}&format={fmt}").status_code == 200


def test_weekly_and_monthly_periods_approval(planned):
    a, s = planned["api"], planned
    plan = a.ok("post", "/api/plans", {"name": "أسبوعية", "term_id": s["term"], "stage_id": s["basic"], "period_type": "week"})
    per = a.ok("get", f"/api/plans/{plan['id']}/periods")["periods"]
    assert [p["key"] for p in per] == ["2026-10-04", "2026-10-11", "2026-10-18", "2026-10-25"]
    assert [p["school_days"] for p in per] == [5, 4, 4, 5]
    r = a.ok("post", f"/api/plans/{plan['id']}/fill-weekly", {})
    assert r["targets"][f"{s['g5']}:{s['math']}"] == {"2026-10-04": 5, "2026-10-11": 4, "2026-10-18": 4, "2026-10-25": 5}
    wk = _analysis(a, s, plan, period="2026-10-11")
    row = next(x for x in wk["rows"] if x["section_id"] == s["s5a"] and x["subject_id"] == s["math"])
    assert (row["required"], row["scheduled"]) == (4, 4)
    # approval, and any change sends it back to draft
    p = a.ok("post", f"/api/plans/{plan['id']}/approve", {})
    assert p["status"] == "approved" and p["approved_by"]
    p = a.ok("patch", f"/api/plans/{plan['id']}", {"version": p["version"], "targets": {f"{s['g5']}:{s['math']}": {"2026-10-04": 6}}})
    assert p["status"] == "draft" and p["targets"] == {f"{s['g5']}:{s['math']}": {"2026-10-04": 6}}
    month = a.ok("post", "/api/plans", {"name": "شهرية", "term_id": s["term"], "period_type": "month"})
    assert [x["key"] for x in a.ok("get", f"/api/plans/{month['id']}/periods")["periods"]] == ["2026-10"]
    # bad period keys are refused; a term without dates is explained
    r = a.patch(f"/api/plans/{month['id']}", {"version": month["version"], "targets": {f"{s['g5']}:{s['math']}": {"oct": 3}}})
    assert r.status_code == 400


def test_term_without_dates_is_explained(school):
    a, s = school["api"], school
    plan = a.ok("post", "/api/plans", {"name": "خطة", "term_id": s["term"], "period_type": "term"})
    r = a.get(f"/api/plans/{plan['id']}/periods")
    assert r.status_code == 400 and "تاريخ" in r.get_json()["details"]["message"]
