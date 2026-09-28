"""Browser tests: the real app served on a local port + headless Chromium (Playwright)."""
import threading

import pytest
from sqlalchemy import text
from werkzeug.serving import make_server

from app.demo import seed_demo
from app.extensions import db
from tests.helpers import make_user

playwright_api = pytest.importorskip("playwright.sync_api")

PASSWORD = "password123"


@pytest.fixture(autouse=True)
def clean():
    """Override the API-suite truncation; e2e tests reseed in `demo` instead."""
    yield


@pytest.fixture(scope="package", autouse=True)
def _leave_database_empty(app):
    """Whatever runs after the browser tests starts from an empty database, as the API tests expect."""
    yield
    with app.app_context():
        tables = ", ".join(t.name for t in reversed(db.metadata.sorted_tables))
        db.session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        db.session.commit()


@pytest.fixture(scope="session")
def live_server(app):
    server = make_server("127.0.0.1", 0, app, threaded=True)
    port = server.server_port
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


@pytest.fixture
def demo(app):
    with app.app_context():
        tables = ", ".join(t.name for t in reversed(db.metadata.sorted_tables))
        db.session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        db.session.commit()
    runner = app.test_cli_runner()
    assert runner.invoke(args=["seed-base"]).exit_code == 0
    admin_id = make_user("admin@school.test", password=PASSWORD)
    with app.app_context():
        info = seed_demo(app, admin_id)
    return info


@pytest.fixture(scope="session")
def browser():
    with playwright_api.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser, live_server, demo):
    ctx = browser.new_context(viewport={"width": 1400, "height": 950}, service_workers="allow")
    # Google Fonts are unreachable in CI sandboxes; don't let that slow the tests down.
    ctx.route("**/fonts.googleapis.com/**", lambda r: r.abort())
    ctx.route("**/fonts.gstatic.com/**", lambda r: r.abort())
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.set_default_timeout(10000)
    pg.base = live_server
    pg.goto(f"{live_server}/auth/login")
    pg.fill("#email", "admin@school.test")
    pg.fill("#password", PASSWORD)
    pg.click("button[type=submit]")
    pg.wait_for_selector("#tt-select option", state="attached")
    yield pg
    ctx.close()
