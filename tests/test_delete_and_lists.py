"""Deleting a timetable with everything inside it, and renaming list items (floors, corridors…)
so the saved records follow."""
from tests.test_school_ops import ops  # noqa: F401  (fixture)


def test_timetable_with_contents_is_refused_then_deleted_with_cascade(ops):  # noqa: F811
    a, s = ops["api"], ops
    tt = a.ok("get", f"/api/timetables/{s['tt']}")
    r = a.delete(f"/api/timetables/{s['tt']}?version={tt['version']}")
    assert r.status_code == 409
    body = r.get_json()
    assert body["error"] == "has_dependents"
    assert body["details"]["lesson"] == 2 and body["details"]["card"] >= 10
    # a copy based on it does not block the delete
    a.ok("post", f"/api/timetables/{s['tt']}/copy", {"name": "نسخة"})
    a.ok("delete", f"/api/timetables/{s['tt']}?version={tt['version']}&cascade=1")
    names = [x["name"] for x in a.ok("get", "/api/timetables")["items"]]
    assert "نسخة" in names and len(names) == 1
    copy = a.ok("get", "/api/timetables")["items"][0]
    assert copy["based_on_id"] is None
    lessons = a.ok("get", f"/api/timetables/{copy['id']}/lessons")["items"]
    assert len(lessons) == 2           # the copy keeps its own lessons


def test_cascade_delete_needs_admin(ops):  # noqa: F811
    a, s = ops["api"], ops
    a.ok("post", "/api/users", {"email": "ed@school.test", "display_name": "محرر", "role": "stage_editor", "password": "password123", "stage_ids": [s["basic"]] if "basic" in s else []})
    tt = a.ok("get", f"/api/timetables/{s['tt']}")
    a.logout()
    a.login("ed@school.test")
    r = a.delete(f"/api/timetables/{s['tt']}?version={tt['version']}&cascade=1")
    assert r.status_code == 403


def test_renaming_a_floor_and_a_corridor_renames_saved_duties_and_exams(ops):  # noqa: F811
    a, s = ops["api"], ops
    d = a.ok("post", "/api/duty-assignments", {"term_id": s["term"], "duty_type": "الممرات",
                                               "location": "الطابق الأول › الممر الشرقي", "teacher_ids": [s["t1"]],
                                               "extra": {"zone": "أ"}})
    a.ok("post", "/api/duty-assignments", {"term_id": s["term"], "duty_type": "الممرات", "location": "الساحة"})
    m = a.ok("get", "/api/modules/duties")
    value = {"title": m["title"], "labels": {}, "lists": {**m["lists"], "locations": [
        "الطابق 1", "الطابق 1 › الممر أ", "الساحة"]},
        "extra_fields": [{"key": "zone", "label_ar": "المنطقة", "type": "select", "options": ["ب"]}]}
    r = a.ok("put", "/api/settings/module:duties", {"value": value, "renames": {
        "locations": {"الطابق الأول": "الطابق 1", "الطابق الأول › الممر الشرقي": "الطابق 1 › الممر أ"},
        "x:zone": {"أ": "ب"}}})
    assert r["renamed_records"] == 1
    got = a.ok("get", f"/api/duty-assignments/{d['id']}")
    assert got["location"] == "الطابق 1 › الممر أ" and got["extra"] == {"zone": "ب"}
    assert a.ok("get", "/api/modules/duties")["lists"]["locations"][1] == "الطابق 1 › الممر أ"
    # exams: the location sits inside each room
    e = a.ok("post", "/api/exam-sessions", {"term_id": s["term"], "exam_date": "2027-01-10", "subject_id": s["math"],
                                            "rooms": [{"room_id": s["room"], "location": "المبنى الرئيسي › الطابق الأول"}]})
    m = a.ok("get", "/api/modules/exams")
    a.ok("put", "/api/settings/module:exams", {"value": {"title": m["title"], "labels": {}, "lists": m["lists"],
                                                         "extra_fields": []},
                                               "renames": {"locations": {"المبنى الرئيسي › الطابق الأول": "المبنى أ › الطابق 1"}}})
    assert a.ok("get", f"/api/exam-sessions/{e['id']}")["rooms"][0]["location"] == "المبنى أ › الطابق 1"
    # an unknown list is refused
    r = a.put("/api/settings/module:exams", {"value": {"lists": {}}, "renames": {"floors": {"a": "b"}}})
    assert r.status_code == 400
