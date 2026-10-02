"""Study plan: entered per grade × subject, compared with each section's lessons (split groups counted
once), missing lessons created and a section's own lesson corrected, imported from Excel."""
import io

from openpyxl import Workbook


def _plan(a, s, *items):
    return a.ok("put", "/api/curriculum/bulk", {"items": [
        {"grade_id": s[g], "subject_id": s[sub], "periods_per_week": n, "duration": d} for g, sub, n, d in items]})


def _check(a, s):
    return a.ok("get", f"/api/timetables/{s['tt']}/curriculum/check")


def _row(rep, s, sec, sub):
    return next(r for r in rep["rows"] if r["section_id"] == s[sec] and r["subject_id"] == s[sub])


def test_check_create_missing_and_correct(school):
    a, s = school["api"], school
    _plan(a, s, ("g5", "math", 5, 1), ("g5", "arabic", 6, 1), ("g5", "pe", 2, 2))
    a.ok("post", "/api/lessons", {"timetable_id": s["tt"], "subject_id": s["math"], "periods_per_week": 4,
                                  "teachers": [s["t1"]], "targets": [{"section_id": s["s5a"]}]})
    # PE split boys / girls: 2 periods each, taught at the same time → the section has 2, not 4
    d = a.ok("post", "/api/divisions", {"section_id": s["s5a"], "name": "بنين/بنات"})
    boys = a.ok("post", "/api/groups", {"division_id": d["id"], "name_ar": "بنين"})["id"]
    girls = a.ok("post", "/api/groups", {"division_id": d["id"], "name_ar": "بنات"})["id"]
    for t, g in (("t_pe_m", boys), ("t_pe_f", girls)):
        a.ok("post", "/api/lessons", {"timetable_id": s["tt"], "subject_id": s["pe"], "periods_per_week": 2, "duration": 2,
                                      "teachers": [s[t]], "targets": [{"section_id": s["s5a"], "group_id": g}]})
    # a subject outside the plan, without a teacher
    a.ok("post", "/api/lessons", {"timetable_id": s["tt"], "subject_id": s["arabic"], "periods_per_week": 6,
                                  "teachers": [], "targets": [{"section_id": s["s5b"]}]})
    rep = _check(a, s)
    assert _row(rep, s, "s5a", "math")["status"] == "under" and _row(rep, s, "s5a", "math")["fixable"]
    assert _row(rep, s, "s5a", "pe")["status"] == "ok" and _row(rep, s, "s5a", "pe")["actual"] == 2
    assert _row(rep, s, "s5a", "arabic")["status"] == "missing"
    assert _row(rep, s, "s5b", "arabic")["status"] == "ok" and _row(rep, s, "s5b", "arabic")["no_teacher"] == 1
    assert _row(rep, s, "s5b", "math")["status"] == "missing"
    assert [g["name"] for g in rep["no_plan_grades"]] == ["العاشر"]          # grades without a plan are not checked
    # the same issues on the validation page
    v = a.ok("get", f"/api/timetables/{s['tt']}/validate")
    codes = [w["code"] for w in v["warnings"]]
    assert codes.count("curriculum_missing") == 3 and "curriculum_under" in codes and "lesson_no_teacher" in codes
    msg = next(w["message"] for w in v["warnings"] if w["code"] == "curriculum_under")
    assert "الخامس / أ" in msg and "الرياضيات" in msg and "نقص 1" in msg
    # fix everything: 3 lessons created (one teacher assigned automatically), math of 5/أ corrected to 5
    a.ok("patch", f"/api/teachers/{s['t2']}", {"version": a.ok("get", f"/api/teachers/{s['t2']}")["version"],
                                               "subject_ids": [s["arabic"]]})
    r = a.ok("post", f"/api/timetables/{s['tt']}/curriculum/apply", {"assign_teacher": True})
    assert r["created"] == 3 and r["adjusted"] == 1 and r["assigned"] == 1 and not r["skipped"]
    rep = _check(a, s)
    assert all(x["status"] == "ok" for x in rep["rows"]), [x for x in rep["rows"] if x["status"] != "ok"]
    ls = a.ok("get", f"/api/timetables/{s['tt']}/lessons")["items"]
    arabic_5a = next(l for l in ls if l["subject_id"] == s["arabic"] and l["targets"][0]["section_id"] == s["s5a"])
    assert arabic_5a["teachers"][0]["teacher_id"] == s["t2"] and len(arabic_5a["cards"]) == 6
    math_5a = next(l for l in ls if l["subject_id"] == s["math"] and l["targets"][0]["section_id"] == s["s5a"])
    assert math_5a["periods_per_week"] == 5 and len(math_5a["cards"]) == 5
    # 0 removes a subject from the plan; deleting a subject removes it from the plan too
    r = _plan(a, s, ("g5", "pe", 0, 1))
    assert r["removed"] == 1


def test_copy_plan_and_shared_lessons_are_left_alone(school):
    a, s = school["api"], school
    g6 = a.ok("post", "/api/grades", {"stage_id": s["basic"], "name_ar": "السادس"})["id"]
    _plan(a, s, ("g5", "math", 5, 1), ("g5", "arabic", 6, 1))
    r = a.ok("post", "/api/curriculum/copy", {"from_grade_id": s["g5"], "to_grade_ids": [g6]})
    assert r["copied"] == 2
    a.ok("post", "/api/lessons", {"timetable_id": s["tt"], "subject_id": s["math"], "periods_per_week": 4,
                                  "teachers": [s["t1"]], "targets": [{"section_id": s["s5a"]}, {"section_id": s["s5b"]}]})
    rep = _check(a, s)
    row = _row(rep, s, "s5a", "math")
    assert row["status"] == "under" and row["shared"] and not row["fixable"]
    r = a.ok("post", f"/api/timetables/{s['tt']}/curriculum/apply", {"keys": [row["id"]]})
    assert r["created"] == 0 and r["skipped"][0]["reason"] == "shared"


def test_import_plan_from_excel(school):
    a, s = school["api"], school
    wb = Workbook()
    ws = wb.active
    ws.title = "الخطة الدراسية"
    ws.append(["الصف", "المبحث", "الحصص", "المدة"])
    ws.append(["الخامس، العاشر", "الرياضيات", 5, 1])
    ws.append(["5", "الحاسوب", 2, 2])          # a new subject is created; «5» matches «الخامس»
    ws.append(["الثالث", "العلوم", 3, 1])        # grade not found → warning
    buf = io.BytesIO()
    wb.save(buf)
    r = a.post("/api/import/commit", data={"file": (io.BytesIO(buf.getvalue()), "plan.xlsx")}, content_type="multipart/form-data")
    rep = r.get_json()
    assert r.status_code == 200 and rep["error_count"] == 0, rep
    assert rep["summary"]["curriculum"]["created"] == 3
    assert any("الثالث" in w["message"] for w in rep["warnings"])
    items = a.ok("get", "/api/curriculum")["items"]
    assert len(items) == 3 and {i["duration"] for i in items} == {1, 2}
