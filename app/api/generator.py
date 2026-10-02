"""Generator runs: instant feasibility check, start (in the background), progress, cancel, history.

The run works in a background thread of the web process; its state lives in `generator_run`, so any
web worker can answer "how far is it?" and accept "stop". A run whose heartbeat stops (the server was
restarted) is marked failed instead of staying "running" for ever.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone

from flask import current_app, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import select

from app.api import api_bp
from app.api.idempotency import write_endpoint
from app.api.serialize import parse_uuid
from app.auth.permissions import require_admin
from app.errors import ApiError
from app.extensions import db
from app.models import GeneratorRun, Notification, Timetable
from app.models.base import utcnow
from app.rules import generator as G

STALE = timedelta(seconds=90)
LABELS = {"queued": "في الانتظار", "running": "جارٍ التوليد…", "solved": "اكتمل التوليد", "partial": "اكتمل التوليد مع حصص غير موضوعة", "infeasible": "تعذّر إيجاد حل",
          "timeout": "انتهت المهلة", "cancelled": "أُوقف التوليد", "failed": "فشل التوليد",
          "feasibility_failed": "فشل فحص الجدوى"}


def _tt(tt_id) -> Timetable:
    tt = db.session.get(Timetable, parse_uuid(tt_id, "timetable_id"))
    if tt is None:
        raise ApiError("not_found", 404)
    return tt


def serialize_run(r: GeneratorRun) -> dict:
    out = r.to_dict()
    out["label"] = LABELS.get(r.status, r.status)
    return out


def _mark_stale(r: GeneratorRun):
    if r.status in ("queued", "running") and r.heartbeat_at and utcnow() - r.heartbeat_at > STALE:
        r.status, r.finished_at = "failed", utcnow()
        r.message = "توقف الخادم أثناء التوليد (أُعيد تشغيله)؛ شغّل المولّد مرة أخرى"
        db.session.commit()


@api_bp.get("/timetables/<tt_id>/generator/feasibility")
@login_required
def generator_feasibility(tt_id):
    tt = _tt(tt_id)
    issues = G.feasibility(tt)
    pb = G.Problem(tt, "full")
    for c in pb.cards:
        if not c.domain:
            issues.append({"code": "no_slot", "level": "error",
                           "message": f"«{pb.lesson_label(c.lesson)}»: لا توجد أي خانة صالحة لبطاقة طولها {count_word(c.duration)} (التوقيت أو أوقات عدم التوفر)",
                           "message_en": "A card has no valid slot at all"})
    total = sum(c.duration for c in pb.cards)
    return jsonify({"ok": not issues, "issues": issues, "cards": len(pb.cards), "periods": total,
                    "locked": sum(1 for c in pb.cards if c.locked),
                    "placed": sum(c.duration for c in pb.cards if c.cur is not None)})


def count_word(n: int) -> str:
    from app.arabic import count
    return count(n, "period")


@api_bp.post("/timetables/<tt_id>/generator/runs")
@write_endpoint
def start_generator(tt_id):
    require_admin(current_user)
    tt = _tt(tt_id)
    data = request.get_json(silent=True) or {}
    mode = data.get("mode") or "full"
    if mode not in ("full", "repair", "fill"):
        raise ApiError("validation", 400, details={"field": "mode"})
    target = data.get("target") or "new"
    if target not in ("new", "same"):
        raise ApiError("validation", 400, details={"field": "target"})
    if target == "same" and tt.status != "draft":
        raise ApiError("validation", 400, details={"field": "target", "message": "لا يُكتب الناتج في جدول منشور أو مؤرشف؛ اختر «مسودة جديدة»"})
    busy = db.session.scalars(select(GeneratorRun).where(GeneratorRun.timetable_id == tt.id,
                                                        GeneratorRun.status.in_(("queued", "running")))).first()
    if busy is not None:
        _mark_stale(busy)
        if busy.status in ("queued", "running"):
            raise ApiError("validation", 409, details={"message": "يعمل المولّد على هذا الجدول الآن؛ انتظر انتهاءه أو أوقفه"})
    params = G.normalize_params(data.get("params"))
    params["target"] = target
    params["name"] = (data.get("name") or "").strip()[:120]
    run = GeneratorRun(timetable_id=tt.id, mode=mode, status="queued", params=params, heartbeat_at=utcnow())
    issues = G.feasibility(tt)
    run.feasibility = issues
    if issues and not data.get("force"):
        run.status, run.finished_at = "feasibility_failed", utcnow()
        run.message = "في البيانات ما يجعل الحل مستحيلاً حسابياً؛ عالج الأخطاء أدناه أو شغّل مع «تجاهل فحص الجدوى»"
    db.session.add(run)
    db.session.flush()
    if run.status == "queued" and not current_app.config.get("GENERATOR_MANUAL"):
        start_thread(current_app._get_current_object(), run.id)
    return serialize_run(run), 201


def start_thread(app, run_id):
    threading.Thread(target=run_generator, args=(app, run_id), daemon=True, name=f"generator-{run_id}").start()


def run_generator(app, run_id):
    """The whole run (feasibility done already): solve, explain, write the result, notify."""
    import time
    with app.app_context():
        r = None
        for _ in range(50):   # the request that created the run may not have committed yet
            r = db.session.get(GeneratorRun, run_id)
            if r is not None:
                break
            db.session.rollback()
            time.sleep(0.1)
        if r is None or r.status != "queued":
            return
        try:
            _run(r)
        except Exception as e:   # pragma: no cover - reported to the user instead of a stuck run
            db.session.rollback()
            r = db.session.get(GeneratorRun, run_id)
            r.status, r.finished_at, r.message = "failed", utcnow(), f"خطأ غير متوقع: {str(e)[:300]}"
            db.session.commit()
            current_app.logger.exception("generator failed")


def _run(r: GeneratorRun):
    run_id = r.id
    r.status, r.started_at, r.heartbeat_at = "running", utcnow(), utcnow()
    db.session.commit()
    tt = db.session.get(Timetable, r.timetable_id)
    prm = dict(r.params)
    pb = G.Problem(tt, r.mode)
    before = G.metrics(pb, G.current_placement(pb))

    # progress and "stop" go through the database (plain SQL: no audit rows, no version bumps),
    # so every web worker sees them
    from sqlalchemy import update
    table = GeneratorRun.__table__
    engine = db.engine

    def on_progress(p):
        with engine.begin() as conn:
            conn.execute(update(table).where(table.c.id == run_id).values(progress=p, heartbeat_at=utcnow()))

    def should_stop():
        with engine.begin() as conn:
            conn.execute(update(table).where(table.c.id == run_id).values(heartbeat_at=utcnow()))
            params = conn.execute(select(table.c.params).where(table.c.id == run_id)).scalar_one()
        return bool((params or {}).get("stop"))

    out = G.solve(pb, prm, on_progress=on_progress, should_stop=should_stop)
    db.session.expire_all()
    r = db.session.get(GeneratorRun, run_id)
    r.progress = {**(r.progress or {}), "solutions": out.solutions, "elapsed": out.wall, "objective": out.objective}
    core = []
    if (out.status == "infeasible" or (out.status == "partial" and prm.get("explain"))):
        core = G.explain(pb, prm, time_limit=min(30, max(10, prm["time_limit"] // 2)))
    r.infeasible_core = core or None
    if out.status in ("solved", "partial"):
        after = G.metrics(pb, out.placement)
        moved = sum(1 for i, c in enumerate(pb.cards) if c.cur is not None and out.placement.get(i) != c.cur)
        after["moved_cards"] = moved
        if prm.get("target") == "same":
            target, card_map = tt, None
        else:
            from app.api.scheduling import copy_timetable_data
            import os
            from zoneinfo import ZoneInfo
            stamp = datetime.now(ZoneInfo(os.environ.get("APP_TIMEZONE", "Asia/Amman"))).strftime("%Y-%m-%d %H:%M")
            name = prm.get("name") or f"{tt.name} — مولَّد {stamp}"
            target, card_map = copy_timetable_data(tt, name)
        G.write_result(pb, out.placement, target, card_map)
        r.result_timetable_id = target.id
        r.metrics = {"before": before, "after": after}
    else:
        r.metrics = {"before": before}
    r.status, r.objective, r.message, r.finished_at = out.status, out.objective, out.message, utcnow()
    db.session.commit()
    # tell whoever started it (in-app notice + device alert)
    if r.created_by:
        title = f"{LABELS.get(r.status, r.status)} — {tt.name}"
        body = r.message or ""
        if r.metrics.get("after"):
            a = r.metrics["after"]
            body = f"وُضعت {a['periods_placed']} من {a['periods_total']} حصة؛ فراغات المعلمين: {a['teacher_gaps']}"
        db.session.add(Notification(user_id=r.created_by, kind="generator", title_ar=title, body={"text": body},
                                    url="#/generate"))
        try:
            from app.notify.webpush import push_to_user
            push_to_user(r.created_by, title, body, "/#/generate")
        except Exception:
            pass
        db.session.commit()


@api_bp.get("/timetables/<tt_id>/generator/runs")
@login_required
def list_runs(tt_id):
    tt = _tt(tt_id)
    rows = db.session.scalars(select(GeneratorRun).where(GeneratorRun.timetable_id == tt.id)
                              .order_by(GeneratorRun.created_at.desc()).limit(50)).all()
    for r in rows:
        _mark_stale(r)
    return jsonify({"items": [serialize_run(r) for r in rows]})


@api_bp.get("/generator/runs/<run_id>")
@login_required
def get_run(run_id):
    r = db.session.get(GeneratorRun, parse_uuid(run_id))
    if r is None:
        raise ApiError("not_found", 404)
    _mark_stale(r)
    return jsonify(serialize_run(r))


@api_bp.post("/generator/runs/<run_id>/stop")
@write_endpoint
def stop_run(run_id):
    require_admin(current_user)
    r = db.session.get(GeneratorRun, parse_uuid(run_id))
    if r is None:
        raise ApiError("not_found", 404)
    if r.status in ("queued", "running"):
        r.params = {**r.params, "stop": True}
        if r.status == "queued":
            r.status, r.finished_at, r.message = "cancelled", utcnow(), "أُوقف قبل أن يبدأ"
    db.session.flush()
    return serialize_run(r), 200


@api_bp.post("/generator/runs/bulk-delete")
@write_endpoint
def delete_runs():
    """Remove finished runs from the history (the timetables they produced are kept)."""
    require_admin(current_user)
    data = request.get_json(silent=True) or {}
    n = 0
    for i in data.get("ids") or []:
        r = db.session.get(GeneratorRun, parse_uuid(i))
        if r is not None and r.status not in ("queued", "running"):
            r.soft_delete()
            n += 1
    return {"deleted": n}, 200
