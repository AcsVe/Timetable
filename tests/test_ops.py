"""Running on the school PC and the phone: backup and restore of the database, the phone's driver
(pg8000) error mapping, and the generator being reported as unavailable on the phone."""
import gzip
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parent.parent / "ops"
sys.path.insert(0, str(OPS))


def _scratch_url():
    base = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://postgres@/timetable_test?host=/tmp")
    return base.rsplit("/", 1)[0] + "/timetable_ops_test" + ("?" + base.split("?", 1)[1] if "?" in base else "")


needs_pg_tools = pytest.mark.skipif(not (shutil.which("pg_dump") or Path("/usr/lib/postgresql").exists()),
                                    reason="pg_dump / psql not installed")


def _bins():
    import glob
    found = sorted(glob.glob("/usr/lib/postgresql/*/bin"))
    if found:
        os.environ.setdefault("PG_BIN", found[-1])


@needs_pg_tools
def test_dump_restore_round_trip_with_safety_copy(school, tmp_path, monkeypatch):
    """The data of a real (migrated, filled) database goes to a .sql.gz and back into another database,
    in one transaction; the dump leaves out the Neon backup table; the fingerprint follows changes."""
    _bins()
    import pgtools
    src = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://postgres@/timetable_test?host=/tmp")
    dst = _scratch_url()
    pgtools.ensure_database(dst)
    gz = tmp_path / "a.sql.gz"
    pgtools.dump(src, str(gz))
    text = gzip.open(gz).read()
    assert b"CREATE TABLE public.teacher" in text and b"iaj_cloud_backups" not in text
    pgtools.restore(dst, str(gz))
    n, rev = pgtools.check(dst)
    assert n > 30 and rev != "-"
    assert pgtools.check(src) == (n, rev)
    fp = pgtools.fingerprint(dst)
    env = pgtools.conn_env(dst)
    subprocess.run([pgtools.find_bin("psql"), "-q", "-c",
                    "INSERT INTO audit_log (at, entity_type, entity_id, action) VALUES (now(), 'x', gen_random_uuid(), 'insert')"],
                   env=env, check=True)
    assert pgtools.fingerprint(dst) != fp
    # a failing restore changes nothing (single transaction)
    bad = tmp_path / "bad.sql.gz"
    with gzip.open(bad, "wb") as fh:
        fh.write(b"CREATE TABLE broken (;\n")
    with pytest.raises(SystemExit):
        pgtools.restore(dst, str(bad))
    assert pgtools.check(dst)[0] == n
    # restore.py: picks the newest backup, keeps a safety copy of what it replaces
    monkeypatch.setenv("DATABASE_URL", dst)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "bk" / "db").mkdir(parents=True)
    shutil.copy(gz, tmp_path / "bk" / "db" / "timetable-2026-01-01_080000.sql.gz")
    shutil.copy(gz, tmp_path / "bk" / "db" / "timetable-2026-01-02_080000-phone.sql.gz")
    import restore
    assert restore.pick(str(tmp_path / "bk"), "").endswith("2026-01-02_080000-phone.sql.gz")
    assert restore.pick(str(tmp_path / "bk"), "phone").endswith("-phone.sql.gz")
    monkeypatch.setattr(sys, "argv", ["restore.py", "--latest", str(tmp_path / "bk"), "--yes"])
    restore.main()
    assert list((tmp_path / "data").glob("before-restore-*.sql.gz"))
    # the marker refuses a phone backup older than the emergency start
    (tmp_path / "bk" / "db" / "ACTIVE_SITE.txt").write_text("phone 2026-01-03_000000")
    monkeypatch.setattr(sys, "argv", ["restore.py", "--latest", str(tmp_path / "bk"), "--tag", "phone", "--since-marker", "--yes"])
    with pytest.raises(SystemExit):
        restore.main()


def test_newer_pg_dump_lines_are_dropped_for_older_servers():
    import pgtools
    for line in (b"\\restrict abc\n", b"\\unrestrict abc\n", b"SET transaction_timeout = 0;\n", b"CREATE SCHEMA public;\n"):
        assert pgtools._SKIP.match(line)
    assert not pgtools._SKIP.match(b"CREATE TABLE public.teacher (\n")


def test_connection_settings_from_any_url_form():
    import pgtools
    e = pgtools.conn_env("postgresql+psycopg://postgres:p%40ss@localhost:5433/timetable")
    assert (e["PGHOST"], e["PGPORT"], e["PGUSER"], e["PGPASSWORD"], e["PGDATABASE"]) == ("localhost", "5433", "postgres", "p@ss", "timetable")
    assert "PGSSLMODE" not in e or e["PGSSLMODE"] != "require"
    n = pgtools.conn_env("postgres://u:x@ep-1.eu-central-1.aws.neon.tech/neondb")
    assert n["PGSSLMODE"] == "require" and n["PGPORT"] == "5432"


def test_pg8000_errors_map_like_psycopg():
    """The phone's driver gives the SQLSTATE in a dict; the same API errors come out."""
    from sqlalchemy.exc import IntegrityError
    from app.api.idempotency import integrity_to_api_error, pg_error

    class Pg8000Error(Exception):
        pass
    excl = Pg8000Error({"C": "23P01", "n": "ex_occupancy_no_overlap"})
    assert pg_error(excl) == ("23P01", "ex_occupancy_no_overlap")
    assert integrity_to_api_error(IntegrityError("x", {}, excl)).status == 409
    assert integrity_to_api_error(IntegrityError("x", {}, Pg8000Error({"C": "23503", "n": "fk"}))).status == 400


def test_generator_reports_it_is_unavailable_without_the_solver(school, monkeypatch):
    from app.api import generator as gen
    monkeypatch.setattr(gen, "solver_available", lambda: False)
    a = school["api"]
    r = a.post(f"/api/timetables/{school['tt']}/generator/runs", json={})
    body = r.get_json()
    assert r.status_code == 503 and body["details"]["reason"] == "solver_unavailable"
    assert "غير متاح على هذا الجهاز" in body["message"]


def test_server_files_are_complete():
    root = Path(__file__).resolve().parent.parent
    for f in ("serve.py", "1_setup.bat", "2_start.bat", "3_autostart.bat", "update.bat", "site_where.bat",
              "switch_to_server.bat", "back_to_server.bat", "backup_now.bat", "restore_backup.bat", "tt_on.bat",
              "tt_off.bat", "stop_autostart.bat", "neon_link.bat", "standby/phone.sh", "standby/gh_update.py",
              "standby/requirements-phone.txt"):
        assert (root / f).is_file(), f
    for bat in root.glob("*.bat"):
        assert b"\r\n" in bat.read_bytes(), bat.name       # Windows line endings
    assert b"\r\n" not in (root / "standby" / "phone.sh").read_bytes()
    req = (root / "requirements.txt").read_text()
    assert "waitress" in req and "pg8000" in req and "requests" in req
