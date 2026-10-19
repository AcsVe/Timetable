"""Measure the generator on a real aSc export (compare with the timetable aSc made).

    BENCH_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost/timetable_bench \
        python tools/bench_asc.py data.xml out.json [time_limit=60] [with_bells=0]

ERASES the bench database (its name must contain "bench"), imports the file (optionally with the school's
bell-times sheet from tests/data), measures the aSc placement, runs the generator in full and repair modes,
and writes the metrics and validation results to out.json. School files are not kept in the repository.
"""
import io
import json
import sys
import time
import uuid
from pathlib import Path

import os

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from flask_migrate import upgrade  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import create_app  # noqa: E402
from app.config import TestConfig  # noqa: E402
from app.extensions import db  # noqa: E402


class BenchConfig(TestConfig):
    SQLALCHEMY_DATABASE_URI = os.environ.get("BENCH_DATABASE_URL", "")


def main():
    xml_path, out_path = sys.argv[1], sys.argv[2]
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 60
    with_bells = len(sys.argv) > 4 and sys.argv[4] == "1"
    if "bench" not in BenchConfig.SQLALCHEMY_DATABASE_URI.rsplit("/", 1)[-1]:
        sys.exit("Set BENCH_DATABASE_URL to a database whose name contains 'bench' (it is erased)")
    app = create_app(BenchConfig)
    with app.app_context():
        db.session.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
        db.session.commit()
        upgrade(directory=str(REPO / "migrations"))
    from tests import helpers
    helpers.APP = app
    helpers.make_user("admin@bench.test")
    c = app.test_client()
    assert c.post("/auth/login", json={"email": "admin@bench.test", "password": "password123"}).status_code == 200
    H = lambda: {"Idempotency-Key": str(uuid.uuid4())}  # noqa: E731
    for dow, ar, order in [(7, "الأحد", 1), (1, "الاثنين", 2), (2, "الثلاثاء", 3), (3, "الأربعاء", 4), (4, "الخميس", 5)]:
        r = c.post("/api/weekdays", json={"iso_dow": dow, "name_ar": ar, "sort_order": order, "is_school_day": True}, headers=H())
        assert r.status_code == 201, r.get_json()
    files = [(io.BytesIO(Path(xml_path).read_bytes()), "data.xml")]
    if with_bells:
        from openpyxl import Workbook
        from tests.data.bells_raed import rows
        wb = Workbook()
        ws = wb.active
        ws.title = "التوقيت"
        for row in rows():
            ws.append(row)
        buf = io.BytesIO()
        wb.save(buf)
        files.append((io.BytesIO(buf.getvalue()), "bells.xlsx"))
    t0 = time.time()
    r = c.post("/api/import/commit", data={"file": files, "new_timetable_name": "aSc"},
               content_type="multipart/form-data", headers=H())
    rep = r.get_json()
    out = {"import_status": r.status_code, "import_seconds": round(time.time() - t0, 1),
           "summary": rep.get("summary"), "cards": rep.get("cards"),
           "warnings": [w["message"] for w in rep.get("warnings", [])],
           "errors": [e["message"] for e in rep.get("errors", [])]}
    tt = rep["timetable"]["id"]
    out["validate_asc"] = c.get(f"/api/timetables/{tt}/validate").get_json()["summary"]
    out["feasibility"] = c.get(f"/api/timetables/{tt}/generator/feasibility").get_json()

    from app.api.generator import run_generator
    runs = {}
    for mode in ("full", "repair"):
        t0 = time.time()
        r = c.post(f"/api/timetables/{tt}/generator/runs", json={"mode": mode, "params": {"time_limit": limit}}, headers=H())
        body = r.get_json()
        assert r.status_code in (200, 201, 202), body
        if body["status"] == "queued":
            run_generator(app, uuid.UUID(body["id"]))
        res = c.get(f"/api/generator/runs/{body['id']}").get_json()
        res["wall_total"] = round(time.time() - t0, 1)
        new = res.get("result_timetable_id")
        if new:
            res["validate"] = c.get(f"/api/timetables/{new}/validate").get_json()["summary"]
        runs[mode] = res
    out["runs"] = runs
    Path(out_path).write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    print(json.dumps({k: v for k, v in out.items() if k != "runs"}, ensure_ascii=False, indent=1, default=str)[:6000])
    for mode, res in runs.items():
        m = res.get("metrics") or {}
        print(mode, res.get("status"), res.get("message"), "wall", res.get("wall_total"))
        for side in ("before", "after"):
            s = m.get(side) or {}
            print("  ", side, {k: s.get(k) for k in ("periods_total", "periods_placed", "teacher_gaps", "max_gaps_in_a_day",
                                                    "same_day_repeats", "class_idle_periods", "days_over_teacher_max")})
        print("   validate", res.get("validate"))


if __name__ == "__main__":
    main()
