"""Auth, idempotency, optimistic locking, soft delete, sync, audit."""
import uuid
from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models import AppUser, AuditLog
from tests.helpers import make_user


# -- auth -------------------------------------------------------------------
def test_login_logout_and_me(api):
    make_user("a@x.test")
    assert api.c.post("/auth/login", json={"email": "a@x.test", "password": "bad"}).status_code == 401
    api.login("a@x.test")
    assert api.get("/auth/me").get_json()["user"]["role"] == "admin"
    api.logout()
    assert api.get("/api/stages").status_code == 401


def test_expired_substitute_account_is_rejected(api):
    make_user("sub@x.test", role="viewer", valid_until=datetime.now(timezone.utc) - timedelta(minutes=1))
    r = api.c.post("/auth/login", json={"email": "sub@x.test", "password": "password123"})
    assert r.status_code == 401


def test_account_expiring_mid_session_is_logged_out(api, app):
    uid = make_user("sub2@x.test", role="viewer", valid_until=datetime.now(timezone.utc) + timedelta(hours=1))
    api.login("sub2@x.test")
    assert api.get("/api/stages").status_code == 200
    with app.app_context():
        db.session.get(AppUser, uid).valid_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.session.commit()
    assert api.get("/api/stages").status_code == 401


def test_email_login_is_case_insensitive(api):
    make_user("Mixed@X.test")
    api.login("mixed@x.test")


# -- idempotency --------------------------------------------------------------
def test_write_without_key_is_refused(admin):
    r = admin.post("/api/stages", {"name_ar": "أساسي"}, key=False)
    assert r.status_code == 400 and r.get_json()["error"] == "idempotency_key_required"


def test_replayed_request_is_applied_once(admin):
    key = uuid.uuid4()
    r1 = admin.post("/api/stages", {"name_ar": "أساسي"}, key=key)
    r2 = admin.post("/api/stages", {"name_ar": "أساسي"}, key=key)
    assert r1.status_code == r2.status_code == 201
    assert r2.headers.get("Idempotent-Replayed") == "true"
    assert r1.get_json()["id"] == r2.get_json()["id"]
    assert len(admin.get("/api/stages").get_json()["items"]) == 1


def test_same_key_different_body_is_rejected(admin):
    key = uuid.uuid4()
    admin.post("/api/stages", {"name_ar": "أساسي"}, key=key)
    r = admin.post("/api/stages", {"name_ar": "ثانوي"}, key=key)
    assert r.status_code == 422


def test_failed_request_is_replayed_as_failure_not_reexecuted(admin):
    key = uuid.uuid4()
    r1 = admin.post("/api/grades", {"name_ar": "x"}, key=key)  # stage_id missing
    assert r1.status_code == 400
    r2 = admin.post("/api/grades", {"name_ar": "x"}, key=key)
    assert r2.status_code == 400 and r2.headers.get("Idempotent-Replayed") == "true"


def test_client_generated_id_is_accepted(admin):
    cid = str(uuid.uuid4())
    assert admin.ok("post", "/api/stages", {"id": cid, "name_ar": "أساسي"})["id"] == cid
    r = admin.post("/api/stages", {"id": cid, "name_ar": "آخر"})
    assert r.status_code == 409 and r.get_json()["error"] == "duplicate"


# -- optimistic locking & change_seq -----------------------------------------
def test_version_and_change_seq(admin):
    s = admin.ok("post", "/api/stages", {"name_ar": "أساسي"})
    assert s["version"] == 1
    r = admin.patch(f"/api/stages/{s['id']}", {"name_ar": "بدون نسخة"})
    assert r.status_code == 400  # version required
    s2 = admin.ok("patch", f"/api/stages/{s['id']}", {"version": 1, "name_ar": "الأساسي"})
    assert s2["version"] == 2 and s2["change_seq"] > s["change_seq"]
    stale = admin.patch(f"/api/stages/{s['id']}", {"version": 1, "name_ar": "قديم"})
    assert stale.status_code == 409 and stale.get_json()["error"] == "version_conflict"
    assert stale.get_json()["details"]["current"]["name_ar"] == "الأساسي"


def test_child_only_change_bumps_parent(school):
    a = school["api"]
    t = a.ok("get", f"/api/teachers/{school['t2']}")
    t2 = a.ok("patch", f"/api/teachers/{t['id']}", {"version": t["version"], "subject_ids": [school["math"]]})
    assert t2["version"] == t["version"] + 1 and t2["subject_ids"] == [school["math"]]


# -- soft delete & dependents -------------------------------------------------
def test_soft_delete_blocks_dependents_then_tombstones(admin):
    st = admin.ok("post", "/api/stages", {"name_ar": "أساسي"})
    g = admin.ok("post", "/api/grades", {"stage_id": st["id"], "name_ar": "الأول"})
    r = admin.delete(f"/api/stages/{st['id']}?version=1")
    assert r.status_code == 409 and r.get_json()["details"] == {"grade": 1}
    admin.ok("delete", f"/api/grades/{g['id']}?version=1")
    assert admin.get(f"/api/grades/{g['id']}").status_code == 404
    admin.ok("delete", f"/api/stages/{st['id']}?version=1")
    changes = admin.ok("get", f"/api/sync?since={st['change_seq'] - 1}")["changes"]
    tomb = [c for c in changes if c["data"]["id"] == st["id"]]
    assert tomb and tomb[-1]["deleted"] is True


def test_recreate_after_soft_delete_respects_live_unique(admin):
    admin.ok("post", "/api/weekdays", {"iso_dow": 7, "name_ar": "الأحد"})
    assert admin.post("/api/weekdays", {"iso_dow": 7, "name_ar": "الأحد"}).status_code == 409
    wd = admin.ok("get", "/api/weekdays")["items"][0]
    admin.ok("delete", f"/api/weekdays/{wd['id']}?version=1")
    admin.ok("post", "/api/weekdays", {"iso_dow": 7, "name_ar": "الأحد"})


# -- sync ---------------------------------------------------------------------
def test_sync_pages_in_change_order(admin):
    for i in range(5):
        admin.ok("post", "/api/stages", {"name_ar": f"مرحلة {i}"})
    page1 = admin.ok("get", "/api/sync?since=0&limit=3")
    assert len(page1["changes"]) == 3 and page1["more"]
    page2 = admin.ok("get", f"/api/sync?since={page1['next']}&limit=3")
    names = [c["data"]["name_ar"] for c in page1["changes"] + page2["changes"]]
    assert names == [f"مرحلة {i}" for i in range(5)]


# -- audit & validation ---------------------------------------------------------
def test_audit_log_records_who_and_what(admin, ctx):
    key = uuid.uuid4()
    s = admin.ok("post", "/api/stages", {"name_ar": "أساسي"}, key=key)
    admin.ok("patch", f"/api/stages/{s['id']}", {"version": 1, "name_ar": "الأساسية"})
    rows = db.session.query(AuditLog).filter_by(entity_id=uuid.UUID(s["id"])).order_by(AuditLog.id).all()
    assert [r.action for r in rows] == ["create", "update"]
    assert rows[0].idempotency_key == key and rows[0].user_id is not None
    assert rows[1].diff["name_ar"] == ["أساسي", "الأساسية"]


def test_type_validation_messages(admin):
    r = admin.post("/api/weekdays", {"iso_dow": "seven", "name_ar": "x"})
    assert r.status_code == 400 and r.get_json()["details"]["field"] == "iso_dow"
    r = admin.post("/api/users", {"email": "x@y.z", "display_name": "x", "role": "god", "password": "12345678"})
    assert r.status_code == 400 and r.get_json()["details"]["field"] == "role"


def test_bell_schedule_rejects_overlapping_slots(admin):
    r = admin.post("/api/bell-schedules", {"name_ar": "x", "slots": [
        {"slot_no": 1, "kind": "lesson", "period_no": 1, "starts_at": "08:00", "ends_at": "08:45"},
        {"slot_no": 2, "kind": "lesson", "period_no": 2, "starts_at": "08:30", "ends_at": "09:15"},
    ]})
    assert r.status_code == 400 and r.get_json()["details"]["reason"] == "overlapping_or_unordered_times"


def test_settings_public_vs_admin(api):
    make_user("adm@x.test")
    make_user("v@x.test", role="viewer")
    api.login("adm@x.test")
    api.ok("put", "/api/settings/offline_edit_enabled", {"value": False})
    api.ok("put", "/api/settings/secret_thing", {"value": "x"})
    api.logout()
    api.login("v@x.test")
    assert api.ok("get", "/api/settings") == {"offline_edit_enabled": False}
    assert api.put("/api/settings/offline_edit_enabled", {"value": True}).status_code == 403


def test_initial_admin_bootstrap_only_once(app, monkeypatch, ctx):
    from app.models import AppUser
    monkeypatch.setenv("INITIAL_ADMIN_EMAIL", "boss@school.test")
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "longenough1")
    runner = app.test_cli_runner()
    assert runner.invoke(args=["seed-base"]).exit_code == 0
    assert runner.invoke(args=["seed-base"]).exit_code == 0     # idempotent
    monkeypatch.setenv("INITIAL_ADMIN_EMAIL", "other@school.test")
    assert runner.invoke(args=["seed-base"]).exit_code == 0     # an admin exists → nothing new
    assert [u.email for u in ctx.query(AppUser).all()] == ["boss@school.test"]


def test_seed_demo_once_into_empty_db(app, monkeypatch, ctx):
    from app.models import Stage
    monkeypatch.setenv("INITIAL_ADMIN_EMAIL", "boss@school.test")
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "longenough1")
    monkeypatch.setenv("SEED_DEMO", "1")
    runner = app.test_cli_runner()
    assert runner.invoke(args=["seed-base"]).exit_code == 0
    n = ctx.query(Stage).count()
    assert n == 2
    assert runner.invoke(args=["seed-base"]).exit_code == 0
    assert ctx.query(Stage).count() == n
