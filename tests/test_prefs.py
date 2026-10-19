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
