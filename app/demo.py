"""`flask seed-demo`: a small realistic school to try the UI with (goes through the real API)."""
from __future__ import annotations

import uuid

from flask import Flask


def seed_demo(app: Flask, admin_id: uuid.UUID) -> dict:
    client = app.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = str(admin_id)
        s["_fresh"] = True

    def call(method, url, body=None):
        r = getattr(client, method)(url, json=body, headers={"Idempotency-Key": str(uuid.uuid4())})
        if r.status_code >= 400:
            raise RuntimeError(f"{method.upper()} {url} -> {r.status_code}: {r.get_json()}")
        return r.get_json()

    days = {w["iso_dow"]: w["id"] for w in client.get("/api/weekdays").get_json()["items"]}
    school_days = [days[d] for d in (7, 1, 2, 3, 4)]
    if not client.get("/api/school").get_json()["items"]:
        call("post", "/api/school", {"name_ar": "مدرسة تجريبية", "name_en": "Demo School"})
    year = call("post", "/api/academic-years", {"name": f"تجريبي {uuid.uuid4().hex[:4]}", "is_current": False})
    term = call("post", "/api/terms", {"academic_year_id": year["id"], "name_ar": "الفصل الأول", "name_en": "Term 1", "ordinal": 1})

    def slots(n, brk_after, start=7 * 60 + 45):
        out, slot, m = [], 1, start
        for p in range(1, n + 1):
            out.append({"slot_no": slot, "kind": "lesson", "period_no": p,
                        "starts_at": f"{m // 60:02d}:{m % 60:02d}", "ends_at": f"{(m + 45) // 60:02d}:{(m + 45) % 60:02d}"})
            slot += 1
            m += 45
            if p in brk_after:
                out.append({"slot_no": slot, "kind": "break", "period_no": None, "label_ar": "الفسحة",
                            "starts_at": f"{m // 60:02d}:{m % 60:02d}", "ends_at": f"{(m + 20) // 60:02d}:{(m + 20) % 60:02d}"})
                slot += 1
                m += 20
        return out

    basic = call("post", "/api/stages", {"name_ar": "الأساسية", "name_en": "Basic", "sort_order": 1})["id"]
    sec = call("post", "/api/stages", {"name_ar": "الثانوية", "name_en": "Secondary", "sort_order": 2})["id"]
    b1 = call("post", "/api/bell-schedules", {"name_ar": "أساسي — عادي", "stage_id": basic, "slots": slots(7, {3})})["id"]
    b2 = call("post", "/api/bell-schedules", {"name_ar": "ثانوي — عادي", "stage_id": sec, "slots": slots(8, {4}, 7 * 60 + 30)})["id"]
    b3 = call("post", "/api/bell-schedules", {"name_ar": "يوم قصير", "stage_id": basic, "slots": slots(5, {3})})["id"]
    call("post", "/api/bell-assignments/bulk", {"term_id": term["id"], "stage_id": basic, "bell_schedule_id": b1, "weekday_ids": school_days[:4]})
    call("post", "/api/bell-assignments/bulk", {"term_id": term["id"], "stage_id": basic, "bell_schedule_id": b3, "weekday_ids": [school_days[4]]})
    call("post", "/api/bell-assignments/bulk", {"term_id": term["id"], "stage_id": sec, "bell_schedule_id": b2, "weekday_ids": school_days})

    sections = {}
    for stage, grades in ((basic, [("الخامس", "Grade 5"), ("السادس", "Grade 6")]), (sec, [("العاشر", "Grade 10")])):
        for i, (ar, en) in enumerate(grades):
            g = call("post", "/api/grades", {"stage_id": stage, "name_ar": ar, "name_en": en, "sort_order": i})["id"]
            for s_ar, s_en in (("أ", "A"), ("ب", "B")):
                sections[f"{ar}/{s_ar}"] = call("post", "/api/sections", {"grade_id": g, "name_ar": s_ar, "name_en": s_en})["id"]

    subj = {}
    for ar, en, color in (("اللغة العربية", "Arabic", "#f8d7a8"), ("الرياضيات", "Math", "#b9d7f7"),
                          ("العلوم", "Science", "#c5ecc3"), ("اللغة الإنجليزية", "English", "#e3cdf5"),
                          ("التربية الرياضية", "PE", "#fbe38e"), ("الموسيقى", "Music", "#f7c4d8"), ("الدراما", "Drama", "#d0e6e8")):
        subj[ar] = call("post", "/api/subjects", {"name_ar": ar, "name_en": en, "color": color})["id"]

    def teacher(ar, en, short, stages, subjects, gender=None, target=None):
        return call("post", "/api/teachers", {"name_ar": ar, "name_en": en, "short": short, "gender": gender,
                                              "stage_ids": stages, "subject_ids": [subj[s] for s in subjects],
                                              "target_weekly_periods": target, "max_periods_per_day": 6})["id"]

    T = {
        "arabic": teacher("أحمد خليل", "Ahmad Khalil", "أ.خليل", [basic], ["اللغة العربية"], "m", 20),
        "math": teacher("سارة يوسف", "Sara Yousef", "أ.سارة", [basic, sec], ["الرياضيات"], "f", 22),
        "science": teacher("محمود علي", "Mahmoud Ali", "أ.محمود", [basic, sec], ["العلوم"], "m", 20),
        "english": teacher("ليلى حسن", "Layla Hasan", "أ.ليلى", [basic, sec], ["اللغة الإنجليزية"], "f", 20),
        "pe_m": teacher("خالد سمير", "Khaled Samir", "أ.خالد", [basic], ["التربية الرياضية"], "m", 12),
        "pe_f": teacher("هدى ناصر", "Huda Nasser", "أ.هدى", [basic], ["التربية الرياضية"], "f", 12),
        "music": teacher("رامي فارس", "Rami Fares", "أ.رامي", [basic], ["الموسيقى"], "m", 10),
        "drama": teacher("نور سالم", "Nour Salem", "أ.نور", [basic], ["الدراما"], "f", 10),
        "arabic2": teacher("فاطمة عمر", "Fatima Omar", "أ.فاطمة", [sec], ["اللغة العربية"], "f", 16),
    }
    tt = call("post", "/api/timetables", {"term_id": term["id"], "name": "المسودة 1"})

    def lesson(subject, teachers, targets, ppw, duration=1):
        return call("post", "/api/lessons", {"timetable_id": tt["id"], "subject_id": subj[subject], "periods_per_week": ppw,
                                             "duration": duration, "teachers": [T[x] for x in teachers], "targets": targets})

    for name, sid in sections.items():
        is_basic = not name.startswith("العاشر")
        lesson("اللغة العربية", ["arabic" if is_basic else "arabic2"], [{"section_id": sid}], 5)
        lesson("الرياضيات", ["math"], [{"section_id": sid}], 4 if is_basic else 5)
        lesson("العلوم", ["science"], [{"section_id": sid}], 2 if is_basic else 4, duration=2 if not is_basic else 1)
        lesson("اللغة الإنجليزية", ["english"], [{"section_id": sid}], 3)
        if is_basic:
            pe = call("post", "/api/divisions", {"section_id": sid, "name": "أولاد/بنات"})["id"]
            boys = call("post", "/api/groups", {"division_id": pe, "name_ar": "أولاد", "name_en": "Boys"})["id"]
            girls = call("post", "/api/groups", {"division_id": pe, "name_ar": "بنات", "name_en": "Girls"})["id"]
            arts = call("post", "/api/divisions", {"section_id": sid, "name": "موسيقى/دراما"})["id"]
            mus = call("post", "/api/groups", {"division_id": arts, "name_ar": "موسيقى", "name_en": "Music"})["id"]
            dra = call("post", "/api/groups", {"division_id": arts, "name_ar": "دراما", "name_en": "Drama"})["id"]
            lesson("التربية الرياضية", ["pe_m"], [{"section_id": sid, "group_id": boys}], 2)
            lesson("التربية الرياضية", ["pe_f"], [{"section_id": sid, "group_id": girls}], 2)
            lesson("الموسيقى", ["music"], [{"section_id": sid, "group_id": mus}], 1)
            lesson("الدراما", ["drama"], [{"section_id": sid, "group_id": dra}], 1)
    return {"timetable_id": tt["id"], "term_id": term["id"], "sections": len(sections)}
