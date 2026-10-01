"""Exam timetable, duty roster, conditional load rules, bulk delete and the new report kinds."""
import io

import pytest
from openpyxl import load_workbook

from app.reports.data import KINDS


def url(s, kind, **q):
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    return f"/api/timetables/{s['tt']}/reports/{kind}?{qs}"


@pytest.fixture
def ops(school):
    a, s = school["api"], school
    a.ok("post", "/api/school", {"name_ar": "مدرسة الاختبار"})
    room = a.ok("post", "/api/rooms", {"name_ar": "قاعة 1"})["id"]
    s["room"] = room
    math = a.ok("post", "/api/lessons", {"timetable_id": s["tt"], "subject_id": s["math"], "periods_per_week": 4,
                                         "teachers": [s["t1"]], "targets": [{"section_id": s["s5a"]}]})
    a.ok("post", "/api/lessons", {"timetable_id": s["tt"], "subject_id": s["arabic"], "periods_per_week": 6,
                                  "teachers": [s["t2"]], "targets": [{"section_id": s["s5a"]}]})
    c = math["cards"][0]
    # Sunday period 1 = 08:00–08:45 for the basic stage
    a.ok("patch", f"/api/cards/{c['id']}", {"version": c["version"], "weekday_id": s["days"][7], "period_no": 1})
    return s


# ---------------------------------------------------------------- configuration
def test_module_config_defaults_rename_and_extra_fields(ops):
    a = ops["api"]
    m = a.ok("get", "/api/modules/duties")
    assert "الطابور الصباحي" in m["lists"]["duty_types"] and m["labels"]["location"]["ar"] == "الموقع"
    a.ok("put", "/api/settings/module:duties", {"value": {
        "title": {"ar": "جدول المناوبات الأسبوعي", "en": ""},
        "labels": {"location": {"ar": "المكان", "en": "Place"}},
        "lists": {"locations": ["الطابق الأول>الممر الشرقي", "الطابق الأول › الممر الشرقي", "الساحة"]},
        "extra_fields": [{"key": "floor_lead", "label_ar": "مسؤول الطابق", "type": "teachers", "parent": "location"}]}})
    m = a.ok("get", "/api/modules/duties")
    assert m["title"]["ar"] == "جدول المناوبات الأسبوعي" and m["labels"]["location"]["ar"] == "المكان"
    assert m["lists"]["locations"] == ["الطابق الأول › الممر الشرقي", "الساحة"]     # normalised, de-duplicated
    assert m["extra_fields"][0]["parent"] == "location"
    bad = a.put("/api/settings/module:duties", json={"value": {"extra_fields": [{"key": "Bad Key", "label_ar": "x"}]}})
    assert bad.status_code == 400


# ---------------------------------------------------------------- exams
def test_exam_sessions_rooms_invigilators_and_clashes(ops):
    a, s = ops["api"], ops
    base = {"term_id": s["term"], "exam_date": "2027-01-10", "starts_at": "09:00", "ends_at": "10:30",
            "stage_id": s["basic"], "grade_ids": [s["g5"]]}
    e1 = a.ok("post", "/api/exam-sessions", {**base, "subject_id": s["math"], "rooms": [
        {"room_id": s["room"], "location": "الطابق الأول", "section_ids": [s["s5a"]], "teacher_ids": [s["t2"]],
         "extra": {"seats": 30}}]})
    assert e1["rooms"][0]["teacher_ids"] == [s["t2"]] and e1["rooms"][0]["extra"] == {"seats": 30}
    a.ok("post", "/api/exam-sessions", {**base, "starts_at": "10:00", "ends_at": "11:00", "subject_id": s["arabic"],
                                        "rooms": [{"room_id": s["room"], "teacher_ids": [s["t2"]], "section_ids": [s["s5b"]]}]})
    codes = {i["code"] for i in a.ok("get", f"/api/school-ops/check?term_id={s['term']}&what=exams")["exams"]}
    assert {"invigilator_clash", "exam_room_clash"} <= codes
    # a subject or a title is required; end before start is refused
    assert a.post("/api/exam-sessions", json={**base}).status_code == 400
    assert a.post("/api/exam-sessions", json={**base, "title": "x", "ends_at": "08:00"}).status_code == 400
    t = a.ok("get", url(s, "exam-schedule"))["tables"][0]
    assert t["rows"][0][6] == "الرياضيات" and "سارة" in t["rows"][0][-1]
    inv = a.ok("get", url(s, "invigilation"))["tables"][0]
    assert inv["rows"][0][:2] == ["سارة", 2]


# ---------------------------------------------------------------- duties
def test_duty_roster_clash_lesson_overlap_copy_and_report(ops):
    a, s = ops["api"], ops
    sun = s["days"][7]
    a.ok("post", "/api/duty-assignments", {"term_id": s["term"], "weekday_id": sun, "duty_type": "الطابور الصباحي",
                                           "location": "الساحة", "starts_at": "08:10", "ends_at": "08:30",
                                           "teacher_ids": [s["t1"]]})
    a.ok("post", "/api/duty-assignments", {"term_id": s["term"], "weekday_id": None, "duty_type": "الممرات",
                                           "location": "الطابق الأول › الممر الشرقي", "time_label": "الاستراحة الأولى",
                                           "starts_at": "08:20", "ends_at": "08:40", "teacher_ids": [s["t1"], s["t2"]]})
    issues = a.ok("get", f"/api/school-ops/check?term_id={s['term']}&what=duties")["duties"]
    codes = [i["code"] for i in issues]
    assert "duty_clash" in codes and "duty_during_lesson" in codes
    lesson_issue = next(i for i in issues if i["code"] == "duty_during_lesson")
    assert "الرياضيات" in lesson_issue["message"] and "08:00–08:45" in lesson_issue["message"]
    roster = a.ok("get", url(s, "duty-roster"))["tables"][0]
    assert roster["columns"][1] == "الأحد" and any("أحمد" in (c or "") for r in roster["rows"] for c in r[1:])
    turned = a.ok("get", url(s, "duty-roster", layout="cols"))["tables"][0]
    assert turned["rows"][0][0] == "الأحد"
    per = a.ok("get", url(s, "duty-teachers"))["tables"][0]
    assert dict((r[0], r[1]) for r in per["rows"])["أحمد"] == 6        # 1 on Sunday + 5 (every day)
    year = a.ok("get", "/api/academic-years")["items"][0]["id"]
    t2 = a.ok("post", "/api/terms", {"academic_year_id": year, "name_ar": "الثاني", "ordinal": 2})["id"]
    assert a.ok("post", "/api/duty-assignments/copy", {"from_term_id": s["term"], "to_term_id": t2})["copied"] == 2
    assert len(a.ok("get", f"/api/duty-assignments?term_id={t2}")["items"]) == 2


def test_deleting_a_teacher_removes_them_from_duties_and_exams(ops):
    a, s = ops["api"], ops
    t = a.ok("post", "/api/teachers", {"name_ar": "مؤقت"})
    d = a.ok("post", "/api/duty-assignments", {"term_id": s["term"], "duty_type": "مغادرة الطلبة", "teacher_ids": [t["id"], s["t2"]]})
    e = a.ok("post", "/api/exam-sessions", {"term_id": s["term"], "exam_date": "2027-01-11", "title": "تجريبي",
                                            "rooms": [{"teacher_ids": [t["id"]]}]})
    a.ok("delete", f"/api/teachers/{t['id']}?version={t['version']}")
    assert a.ok("get", f"/api/duty-assignments/{d['id']}")["teacher_ids"] == [s["t2"]]
    assert a.ok("get", f"/api/exam-sessions/{e['id']}")["rooms"][0]["teacher_ids"] == []


# ---------------------------------------------------------------- load rules
def test_conditional_load_rules(ops):
    a, s = ops["api"], ops
    # no rule: Ahmad falls back to his own target (20), assigned 4
    st = {r["name"]: r for r in a.ok("get", f"/api/timetables/{s['tt']}/load-status")["teachers"]}
    assert st["أحمد"]["status"] == "under" and st["أحمد"]["default_rule"]
    # stage rule 4–6 for the basic stage, counting only that stage
    a.ok("post", "/api/constraint-rules", {"timetable_id": s["tt"], "kind": "weekly_load", "scope_type": "global",
         "params": {"name": "الأساسي", "stage_ids": [s["basic"]], "mode": "range", "min": 4, "max": 5, "count": "scope",
                    "display": "color", "colors": {"under": "#ff0000"}, "texts": {"over": "فائض"}}})
    # teacher rule beats the stage rule
    a.ok("post", "/api/constraint-rules", {"timetable_id": s["tt"], "kind": "weekly_load", "scope_type": "global",
         "params": {"teacher_ids": [s["t2"]], "mode": "exact", "value": 8}})
    data = a.ok("get", f"/api/timetables/{s['tt']}/load-status")
    st = {r["name"]: r for r in data["teachers"]}
    assert st["أحمد"]["status"] == "ok" and st["أحمد"]["rule_name"] == "الأساسي" and st["أحمد"]["display"] == "color"
    assert st["سارة"]["status"] == "under" and st["سارة"]["delta"] == 2
    assert st["سارة"]["message"] == "المعلم سارة: نقص — 6 من 8، بنقص حصتين"
    group = next(g for g in data["groups"] if g["name"] == "الأساسي")
    assert group["counts"]["ok"] >= 1
    msgs = [w["message"] for w in a.ok("get", f"/api/timetables/{s['tt']}/validate")["warnings"]]
    assert "المعلم سارة: نقص — 6 من 8، بنقص حصتين" in msgs
    bad = a.post("/api/constraint-rules", json={"timetable_id": s["tt"], "kind": "weekly_load", "scope_type": "global",
                                               "params": {"mode": "range", "min": 9, "max": 3}})
    assert bad.status_code == 400
    t = a.ok("get", url(s, "load-status", style="color"))["tables"]
    assert t[0]["cell_colors"] and len(t) == 2
    assert a.ok("get", url(s, "load-status"))["tables"][0]["cell_colors"] == []   # plain: no colours at all


# ---------------------------------------------------------------- bulk delete
def test_bulk_delete_is_all_or_nothing(ops):
    a = ops["api"]
    r1 = a.ok("post", "/api/rooms", {"name_ar": "مختبر"})
    r2 = a.ok("post", "/api/rooms", {"name_ar": "مرسم"})
    stale = a.post("/api/rooms/bulk-delete", json={"items": [{"id": r1["id"], "version": r1["version"]},
                                                               {"id": r2["id"], "version": 99}]})
    assert stale.status_code == 409
    assert len(a.ok("get", "/api/rooms")["items"]) == 3
    ok = a.ok("post", "/api/rooms/bulk-delete", {"items": [{"id": r1["id"], "version": r1["version"]},
                                                          {"id": r2["id"], "version": r2["version"]}]})
    assert ok["count"] == 2 and len(a.ok("get", "/api/rooms")["items"]) == 1


# ---------------------------------------------------------------- reports
def test_master_timetable_both_ways_and_show_options(ops):
    a, s = ops["api"], ops
    t = a.ok("get", url(s, "stage-timetable", stage_id=s["basic"]))["tables"][0]
    assert t["group_header"][1] == {"label": "الأحد", "span": 6} and t["rows"][0][0] == "الخامس / أ"
    assert t["rows"][0][1].startswith("الرياضيات\nأحمد")
    t = a.ok("get", url(s, "stage-timetable", stage_id=s["basic"], layout="cols", show="section"))["tables"][0]
    assert t["columns"][1:] == ["الخامس / أ", "الخامس / ب"] and t["rows"][0][:2] == ["الأحد — 1", "الرياضيات"]
    g = a.ok("get", url(s, "section-timetable", section_id=s["s5a"], show="room"))["grids"][0]
    cell = next(c for c in g["cells"] if c["day"] == 0 and c["period"] == 1)
    assert cell["entries"][0] == ["الرياضيات"] and g["periods"][0]["time"] is None and g["footer"] is None
    free = a.ok("get", url(s, "free-teachers"))["grids"][0]
    sun1 = next(c for c in free["cells"] if c["day"] == 0 and c["period"] == 1)
    assert "أحمد" not in sun1["entries"][0][1] and "سارة" in sun1["entries"][0][1]
    m = a.ok("get", url(s, "teacher-sections", layout="cols"))["tables"][0]
    assert m["columns"][0] == "المعلم" and m["rows"][0][0] == "الخامس / أ" and m["totals"][0] == "المجموع"


def test_every_report_in_every_format(ops):
    a, s = ops["api"], ops
    a.ok("post", "/api/exam-sessions", {"term_id": s["term"], "exam_date": "2027-01-10", "subject_id": s["math"],
                                        "rooms": [{"room_id": s["room"], "teacher_ids": [s["t2"]]}]})
    a.ok("post", "/api/duty-assignments", {"term_id": s["term"], "duty_type": "الأنشطة", "teacher_ids": [s["t1"]]})
    for kind in KINDS:
        for layout in ("rows", "cols"):
            for style in ("plain", "color"):
                q = dict(layout=layout, style=style, signature="مدير المدرسة|الختم")
                assert a.get(url(s, kind, **q)).status_code == 200, kind
                r = a.get(url(s, kind, format="pdf", lang="en" if style == "color" else "ar", **q))
                assert r.status_code == 200 and r.data.startswith(b"%PDF"), (kind, layout, style)
                r = a.get(url(s, kind, format="xlsx", **q))
                assert r.status_code == 200, (kind, layout, style)
                wb = load_workbook(io.BytesIO(r.data))
                if style == "plain":   # black and white: no filled cell anywhere
                    for ws in wb.worksheets:
                        for row in ws.iter_rows():
                            for c in row:
                                assert c.fill.fill_type is None, (kind, c.coordinate)
