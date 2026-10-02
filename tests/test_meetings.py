"""Meetings: lessons with members and no classes — they block their members, show in teacher
timetables and the meetings report, stay out of the teaching load, and the generator places them."""
from tests.test_generator import gen, run  # noqa: F401  (fixtures and helper)

SUNDAY = "2026-10-04"


def _meeting(a, s, title, teachers, **kw):
    return a.ok("post", "/api/lessons", {"timetable_id": s["tt"], "kind": "meeting", "title": title,
                                         "periods_per_week": 1, "teachers": [s[t] for t in teachers], **kw})


def test_meeting_blocks_members_and_stays_out_of_the_load(school):
    a, s = school["api"], school
    m = _meeting(a, s, "اجتماع قسم الرياضيات", ["t1", "t2"], bell_schedule_id=s["bell_basic"])
    assert m["kind"] == "meeting" and m["targets"] == [] and m["counts_load"] is False
    subj = a.ok("get", f"/api/subjects/{m['subject_id']}")
    assert subj["name_ar"] == "اجتماع"
    card = m["cards"][0]
    a.ok("patch", f"/api/cards/{card['id']}", {"version": card["version"], "weekday_id": s["days"][7], "period_no": 2})
    # a lesson of a member at the same time is refused, naming the meeting
    l = a.ok("post", "/api/lessons", {"timetable_id": s["tt"], "subject_id": s["math"], "periods_per_week": 1,
                                      "teachers": [s["t1"]], "targets": [{"section_id": s["s5a"]}]})
    c = l["cards"][0]
    r = a.patch(f"/api/cards/{c['id']}", {"version": c["version"], "weekday_id": s["days"][7], "period_no": 2})
    assert r.status_code == 409 and "اجتماع قسم الرياضيات" in r.get_json()["message"]
    # a period the meeting's timing does not have is refused
    m2 = _meeting(a, s, "اجتماع قصير", ["t_pe_m"], bell_schedule_id=s["bell_basic"])
    c2 = m2["cards"][0]
    r = a.patch(f"/api/cards/{c2['id']}", {"version": c2["version"], "weekday_id": s["days"][7], "period_no": 7})
    assert r.status_code == 409
    # the load: t1 has a 20-period target and one teaching period → "under" by 19 (the meeting is not counted)
    v = a.ok("get", f"/api/timetables/{s['tt']}/validate")
    under = [w for w in v["warnings"] if w["code"] in ("teacher_under_target", "load_rule_under") and w.get("teacher_id") == s["t1"]]
    assert under and "حصة واحدة" in under[0]["message"]
    assert not [e for e in v["errors"] if e.get("lesson_id") == m["id"]]
    # counted when asked
    m = a.ok("get", f"/api/lessons/{m['id']}")
    a.ok("patch", f"/api/lessons/{m['id']}", {"version": m["version"], "counts_load": True})
    v = a.ok("get", f"/api/timetables/{s['tt']}/validate")
    under = [w for w in v["warnings"] if w["code"] == "teacher_under_target" and w.get("teacher_id") == s["t1"]]
    assert "حصتان" in under[0]["message"]


def test_title_and_members_are_required_and_only_admins_manage_meetings(school):
    a, s = school["api"], school
    r = a.post("/api/lessons", {"timetable_id": s["tt"], "kind": "meeting", "periods_per_week": 1, "teachers": [s["t1"]]})
    assert r.status_code == 400 and r.get_json()["details"]["field"] == "title"
    r = a.post("/api/lessons", {"timetable_id": s["tt"], "kind": "meeting", "title": "اجتماع", "periods_per_week": 1, "teachers": []})
    assert r.status_code == 400 and r.get_json()["details"]["field"] == "teachers"
    a.ok("post", "/api/users", {"email": "ed@school.test", "display_name": "محرر", "role": "stage_editor",
                                "password": "password123", "stage_ids": [s["basic"]]})
    a.logout()
    a.login("ed@school.test")
    r = a.post("/api/lessons", {"timetable_id": s["tt"], "kind": "meeting", "title": "اجتماع", "periods_per_week": 1,
                                "teachers": [s["t2"]]})
    assert r.status_code == 403


def test_reports_cover_copy_and_messages(school):
    a, s = school["api"], school
    room = a.ok("post", "/api/rooms", {"name_ar": "قاعة الاجتماعات"})["id"]
    m = _meeting(a, s, "اجتماع رؤساء الأقسام", ["t1", "t2"], bell_schedule_id=s["bell_basic"], preferred_room_id=room)
    c = m["cards"][0]
    a.ok("patch", f"/api/cards/{c['id']}", {"version": c["version"], "weekday_id": s["days"][7], "period_no": 2})
    rep = a.ok("get", f"/api/timetables/{s['tt']}/reports/meetings")
    row = rep["tables"][0]["rows"][0]
    assert row[0] == "اجتماع رؤساء الأقسام" and row[1] == "الأحد" and row[2] == "2" and "08:45" in row[3]
    assert row[4] == "قاعة الاجتماعات" and row[6] == 2
    for fmt in ("pdf", "xlsx"):
        assert a.get(f"/api/timetables/{s['tt']}/reports/meetings?format={fmt}").status_code == 200
    tg = a.ok("get", f"/api/timetables/{s['tt']}/reports/teacher-timetable?teacher_id={s['t1']}")
    assert any("اجتماع رؤساء الأقسام" in (e[0] if isinstance(e, list) else str(e))
               for cell in tg["grids"][0]["cells"] for e in cell["entries"])
    master = a.ok("get", f"/api/timetables/{s['tt']}/reports/teachers-master")
    assert any("اجتماع رؤساء الأقسام" in (x or "") for r in master["tables"][0]["rows"] for x in r[1:])
    # an absent member needs no cover for a meeting
    a.ok("post", "/api/absences", {"teacher_id": s["t1"], "date_from": SUNDAY, "date_to": SUNDAY})
    day = a.ok("get", f"/api/timetables/{s['tt']}/cover?date={SUNDAY}")
    assert day["needs"] == []
    # messages for the members
    msgs = a.ok("get", f"/api/timetables/{s['tt']}/meetings/messages")["messages"]
    assert len(msgs) == 2 and "اجتماع رؤساء الأقسام" in msgs[0]["text"] and "الأحد" in msgs[0]["text"]
    # a copied draft keeps the meeting
    cp = a.ok("post", f"/api/timetables/{s['tt']}/copy", {"name": "نسخة"})
    ls = a.ok("get", f"/api/timetables/{cp['id']}/lessons")["items"]
    assert [l["title"] for l in ls if l["kind"] == "meeting"] == ["اجتماع رؤساء الأقسام"]


def test_generator_finds_a_common_free_period(app, gen):  # noqa: F811
    a, s = gen["api"], gen
    _meeting(a, s, "اجتماع القسم", ["t1", "t2"], bell_schedule_id=s["bell_basic"])
    r = run(app, a, s)
    assert r["status"] == "solved", r
    new = r["result_timetable_id"]
    v = a.ok("get", f"/api/timetables/{new}/validate")
    assert v["summary"]["errors"] == 0, v["errors"]
    ls = a.ok("get", f"/api/timetables/{new}/lessons")["items"]
    meet = next(l for l in ls if l["kind"] == "meeting")
    assert meet["cards"][0]["weekday_id"] is not None
