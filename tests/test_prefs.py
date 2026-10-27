"""Personal settings kept in the account: the side menu's favourites and folded groups."""
from app.models import AppUser, AuditLog


def test_menu_prefs_are_saved_per_user_without_audit_noise(admin, ctx):
    me = admin.ok("get", "/auth/me")["user"]
    assert me["ui_prefs"] == {}
    r = admin.c.put("/auth/me/prefs", json={"nav": {"favorites": ["reports", "grid", "reports"], "collapsed": ["system"]}})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["ui_prefs"]["nav"] == {"favorites": ["reports", "grid"], "collapsed": ["system"]}
    assert admin.ok("get", "/auth/me")["user"]["ui_prefs"]["nav"]["favorites"] == ["reports", "grid"]
    user = ctx.query(AppUser).filter_by(email="admin@school.test").one()
    version = user.version
    audits = ctx.query(AuditLog).count()
    admin.c.put("/auth/me/prefs", json={"nav": {"favorites": [], "collapsed": []}})
    ctx.expire_all()
    assert ctx.get(AppUser, user.id).version == version and ctx.query(AuditLog).count() == audits
    # bad input is refused, nothing changes
    for bad in ({"nav": "x"}, {"nav": {"favorites": [1]}}, {"nav": {"collapsed": ["x" * 200]}}):
        assert admin.c.put("/auth/me/prefs", json=bad).status_code == 400
    # each user has their own
    from tests.helpers import make_user
    make_user("viewer@school.test", role="viewer")
    admin.logout()
    admin.login("viewer@school.test")
    assert admin.ok("get", "/auth/me")["user"]["ui_prefs"] == {}
    admin.logout()
    assert admin.c.put("/auth/me/prefs", json={"nav": {}}).status_code == 401


def test_user_changes_own_password(admin):
    r = admin.c.post("/auth/me/password", json={"current_password": "wrong-one", "new_password": "newpass123"})
    assert r.status_code == 400 and r.get_json()["error"] == "bad_password"
    r = admin.c.post("/auth/me/password", json={"current_password": "password123", "new_password": "short"})
    assert r.status_code == 400
    r = admin.c.post("/auth/me/password", json={"current_password": "password123", "new_password": "newpass123"})
    assert r.status_code == 200
    admin.logout()
    assert admin.c.post("/auth/login", json={"email": "admin@school.test", "password": "password123"}).status_code == 401
    admin.login("admin@school.test", "newpass123")
    admin.logout()
    assert admin.c.post("/auth/me/password", json={}).status_code == 401


def test_login_page_shows_the_system_icon_until_a_logo_is_uploaded(api):
    page = api.c.get("/auth/login").get_data(as_text=True)
    assert "/static/brand/system.svg" in page and "auth-card" in page
    assert api.c.get("/static/brand/system.svg").status_code == 200
