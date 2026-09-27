import uuid

import pytest
from sqlalchemy import text

from pathlib import Path

from flask_migrate import upgrade

from app import create_app
from app.config import TestConfig
from app.extensions import db


from tests import helpers
from tests.helpers import make_user  # noqa: F401


@pytest.fixture(scope="session")
def app():
    # No app context stays pushed while tests run: each test-client request then gets
    # its own context (fresh session and `g`), exactly like production.
    app = create_app(TestConfig)
    helpers.APP = app
    with app.app_context():
        # Build the schema from the real Alembic migrations, so the tests also prove the migrations.
        db.session.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
        db.session.commit()
        upgrade(directory=str(Path(__file__).resolve().parent.parent / "migrations"))
    yield app


@pytest.fixture(autouse=True)
def clean(app):
    yield
    with app.app_context():
        tables = ", ".join(t.name for t in reversed(db.metadata.sorted_tables))  # alembic_version kept
        db.session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        db.session.commit()


@pytest.fixture
def ctx(app):
    """App context for tests that inspect the database directly (between requests)."""
    with app.app_context():
        yield db.session


class Api:
    """Test client wrapper: adds Idempotency-Key to every write automatically."""

    def __init__(self, client):
        self.c = client

    def _write(self, method, url, json=None, key=None, **kw):
        headers = kw.pop("headers", {})
        if key is not False:
            headers["Idempotency-Key"] = str(key or uuid.uuid4())
        return getattr(self.c, method)(url, json=json, headers=headers, **kw)

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, json=None, **kw):
        return self._write("post", url, json, **kw)

    def patch(self, url, json=None, **kw):
        return self._write("patch", url, json, **kw)

    def put(self, url, json=None, **kw):
        return self._write("put", url, json, **kw)

    def delete(self, url, json=None, **kw):
        return self._write("delete", url, json, **kw)

    def login(self, email, password="password123"):
        r = self.c.post("/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.get_json()
        return r

    def logout(self):
        self.c.post("/auth/logout", json={})

    def ok(self, method, url, json=None, status=(200, 201), **kw):
        r = getattr(self, method)(url, json=json, **kw) if method != "get" else self.get(url, **kw)
        assert r.status_code in (status if isinstance(status, tuple) else (status,)), (r.status_code, r.get_json())
        return r.get_json()


@pytest.fixture
def api(app):
    return Api(app.test_client())


@pytest.fixture
def admin(api):
    make_user("admin@school.test")
    api.login("admin@school.test")
    return api


@pytest.fixture
def school(admin):
    """A small school: 2 stages, Sun–Thu, bells per stage, 1 term, 1 draft timetable."""
    a = admin
    days = {}
    for dow, ar, order, sd in [(7, "الأحد", 1, True), (1, "الاثنين", 2, True), (2, "الثلاثاء", 3, True),
                               (3, "الأربعاء", 4, True), (4, "الخميس", 5, True), (5, "الجمعة", 6, False)]:
        days[dow] = a.ok("post", "/api/weekdays", {"iso_dow": dow, "name_ar": ar, "sort_order": order,
                                                     "is_school_day": sd})["id"]
    year = a.ok("post", "/api/academic-years", {"name": "2026/2027", "is_current": True})["id"]
    term = a.ok("post", "/api/terms", {"academic_year_id": year, "name_ar": "الأول", "ordinal": 1})["id"]
    basic = a.ok("post", "/api/stages", {"name_ar": "أساسي", "sort_order": 1})["id"]
    secondary = a.ok("post", "/api/stages", {"name_ar": "ثانوي", "sort_order": 2})["id"]
    g5 = a.ok("post", "/api/grades", {"stage_id": basic, "name_ar": "الخامس"})["id"]
    g10 = a.ok("post", "/api/grades", {"stage_id": secondary, "name_ar": "العاشر"})["id"]
    s5a = a.ok("post", "/api/sections", {"grade_id": g5, "name_ar": "أ"})["id"]
    s5b = a.ok("post", "/api/sections", {"grade_id": g5, "name_ar": "ب"})["id"]
    s10a = a.ok("post", "/api/sections", {"grade_id": g10, "name_ar": "أ"})["id"]

    # 6 periods with a break after period 3
    def slots(n=6, brk_after=3):
        out, slot, h = [], 1, 8 * 60
        for p in range(1, n + 1):
            out.append({"slot_no": slot, "kind": "lesson", "period_no": p,
                        "starts_at": f"{h // 60:02d}:{h % 60:02d}", "ends_at": f"{(h + 45) // 60:02d}:{(h + 45) % 60:02d}"})
            slot += 1
            h += 45
            if p == brk_after:
                out.append({"slot_no": slot, "kind": "break", "period_no": None, "label_ar": "الفسحة",
                            "starts_at": f"{h // 60:02d}:{h % 60:02d}", "ends_at": f"{(h + 20) // 60:02d}:{(h + 20) % 60:02d}"})
                slot += 1
                h += 20
        return out

    bell_basic = a.ok("post", "/api/bell-schedules", {"name_ar": "أساسي عادي", "stage_id": basic, "slots": slots()})["id"]
    bell_sec = a.ok("post", "/api/bell-schedules", {"name_ar": "ثانوي عادي", "stage_id": secondary,
                                                    "slots": slots(7, 4)})["id"]
    school_days = [days[d] for d in (7, 1, 2, 3, 4)]
    a.ok("post", "/api/bell-assignments/bulk", {"term_id": term, "stage_id": basic, "bell_schedule_id": bell_basic,
                                                 "weekday_ids": school_days})
    a.ok("post", "/api/bell-assignments/bulk", {"term_id": term, "stage_id": secondary, "bell_schedule_id": bell_sec,
                                                 "weekday_ids": school_days})
    math = a.ok("post", "/api/subjects", {"name_ar": "الرياضيات"})["id"]
    arabic = a.ok("post", "/api/subjects", {"name_ar": "اللغة العربية"})["id"]
    pe = a.ok("post", "/api/subjects", {"name_ar": "التربية الرياضية"})["id"]
    t1 = a.ok("post", "/api/teachers", {"name_ar": "أحمد", "stage_ids": [basic, secondary], "target_weekly_periods": 20})["id"]
    t2 = a.ok("post", "/api/teachers", {"name_ar": "سارة", "stage_ids": [basic]})["id"]
    t_pe_m = a.ok("post", "/api/teachers", {"name_ar": "خالد", "gender": "m", "stage_ids": [basic]})["id"]
    t_pe_f = a.ok("post", "/api/teachers", {"name_ar": "هدى", "gender": "f", "stage_ids": [basic]})["id"]
    tt = a.ok("post", "/api/timetables", {"term_id": term, "name": "مسودة 1"})
    return dict(days=days, school_days=school_days, term=term, basic=basic, secondary=secondary, g5=g5, g10=g10,
                s5a=s5a, s5b=s5b, s10a=s10a, bell_basic=bell_basic, bell_sec=bell_sec, math=math, arabic=arabic,
                pe=pe, t1=t1, t2=t2, t_pe_m=t_pe_m, t_pe_f=t_pe_f, tt=tt["id"], api=a)
