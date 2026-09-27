"""Stage-scoped roles (decision #5)."""
from tests.helpers import make_user


def _editor(api, school, stage_key="basic", email="ed@x.test"):
    make_user(email, role="stage_editor", stages=[school[stage_key]])
    api.logout()
    api.login(email)
    return api


def test_stage_editor_limited_to_own_stage(school):
    a = _editor(school["api"], school)
    assert a.post("/api/grades", {"stage_id": school["basic"], "name_ar": "السادس"}).status_code == 201
    assert a.post("/api/grades", {"stage_id": school["secondary"], "name_ar": "الحادي عشر"}).status_code == 403
    # cannot move a record into a stage they don't own
    g = a.ok("get", f"/api/grades/{school['g5']}")
    r = a.patch(f"/api/grades/{g['id']}", {"version": g["version"], "stage_id": school["secondary"]})
    assert r.status_code == 403
    # global reference data is admin-only
    assert a.post("/api/subjects", {"name_ar": "العلوم"}).status_code == 403
    assert a.get("/api/users").status_code == 403


def test_stage_editor_lessons_scoped_by_targets(school):
    a = _editor(school["api"], school)
    ok = a.post("/api/lessons", {"timetable_id": school["tt"], "subject_id": school["math"], "periods_per_week": 2,
                                 "teachers": [school["t2"]], "targets": [{"section_id": school["s5a"]}]})
    assert ok.status_code == 201
    joint = a.post("/api/lessons", {"timetable_id": school["tt"], "subject_id": school["math"], "periods_per_week": 2,
                                    "teachers": [school["t1"]],
                                    "targets": [{"section_id": school["s5a"]}, {"section_id": school["s10a"]}]})
    assert joint.status_code == 403  # a joint lesson spanning two stages needs both


def test_stage_editor_can_edit_shared_teacher(school):
    a = _editor(school["api"], school)
    t = a.ok("get", f"/api/teachers/{school['t1']}")  # teaches in basic + secondary
    a.ok("patch", f"/api/teachers/{t['id']}", {"version": t["version"], "max_periods_per_day": 6})


def test_viewer_is_read_only(school):
    a = school["api"]
    make_user("v@x.test", role="viewer")
    a.logout()
    a.login("v@x.test")
    assert a.get("/api/grades").status_code == 200
    assert a.post("/api/grades", {"stage_id": school["basic"], "name_ar": "x"}).status_code == 403


def test_admin_cannot_lock_themselves_out(admin):
    me = admin.ok("get", "/auth/me")["user"]
    u = admin.ok("get", f"/api/users/{me['id']}")
    r = admin.patch(f"/api/users/{me['id']}", {"version": u["version"], "role": "viewer"})
    assert r.status_code == 400
    assert admin.delete(f"/api/users/{me['id']}?version={u['version']}").status_code == 400


def test_stage_editor_requires_stage(admin):
    r = admin.post("/api/users", {"email": "e@x.test", "display_name": "e", "role": "stage_editor",
                                  "password": "password123"})
    assert r.status_code == 400 and r.get_json()["details"]["field"] == "stage_ids"


def test_substitute_account_created_by_admin_works_immediately(school):
    a = school["api"]
    u = a.ok("post", "/api/users", {"email": "sub@x.test", "display_name": "بديل", "role": "stage_editor",
                                    "password": "password123", "stage_ids": [school["basic"]],
                                    "valid_until": "2099-01-01T00:00:00+00:00"})
    assert "password_hash" not in u
    a.logout()
    a.login("sub@x.test")
    assert a.post("/api/grades", {"stage_id": school["basic"], "name_ar": "السادس"}).status_code == 201
