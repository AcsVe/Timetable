"""Import from aSc (XML / .roz), Excel and CSV: preview, commit, re-import without duplicates."""
import io
import zlib

import pytest
from openpyxl import Workbook, load_workbook

from app.models import Card, Division, Grade, Lesson, Section, Stage, StudentGroup, Subject, Teacher

ASC_XML = """<?xml version="1.0" encoding="UTF-8"?>
<timetable ascttversion="2024.1" importtype="database" options="idprefix:X,daynumbering1">
  <periods options="canadd,export:silent" columns="period,name,short,starttime,endtime">
    <period name="1" short="1" period="1" starttime="7:45" endtime="8:30"/>
    <period name="2" short="2" period="2" starttime="8:30" endtime="9:15"/>
    <period name="3" short="3" period="3" starttime="9:35" endtime="10:20"/>
    <period name="4" short="4" period="4" starttime="10:20" endtime="11:05"/>
  </periods>
  <daysdefs options="canadd,copy,export:silent" columns="id,days,name,short">
    <daysdef id="*1" name="Every day" short="X" days="10000,01000,00100,00010,00001"/>
    <daysdef id="*2" name="Sunday" short="Su" days="10000"/>
  </daysdefs>
  <weeksdefs columns="id,weeks,name,short"><weeksdef id="*1" name="Every week" short="All" weeks="1"/></weeksdefs>
  <subjects columns="id,name,short,partner_id">
    <subject id="S1" name="الرياضيات" short="ر"/>
    <subject id="S2" name="التربية الرياضية" short="ريا"/>
    <subject id="S3" name="Science" short="Sc"/>
  </subjects>
  <teachers columns="id,firstname,lastname,name,short,gender,color,email,mobile,partner_id">
    <teacher id="T1" name="أحمد محمود" short="أح" gender="M" email="ahmad@x.test"/>
    <teacher id="T2" firstname="Huda" lastname="Saleh" short="HS" gender="F"/>
    <teacher id="T3" name="خالد" short="خ" gender="M"/>
  </teachers>
  <classrooms columns="id,name,short,capacity,buildingid,partner_id">
    <classroom id="R1" name="مختبر" short="مخ" capacity="30"/>
  </classrooms>
  <grades columns="grade,name,short"><grade grade="7" name="السابع" short="7"/></grades>
  <classes columns="id,name,short,classroomids,teacherid,grade,partner_id">
    <class id="C1" name="7أ" short="7أ" teacherid="T1" grade="7"/>
    <class id="C2" name="7ب" short="7ب" grade="7"/>
    <class id="C3" name="8A" short="8A"/>
  </classes>
  <groups columns="id,classid,name,entireclass,divisiontag,studentcount,studentids">
    <group id="G1" classid="C1" name="Entire class" entireclass="1" divisiontag="0"/>
    <group id="G2" classid="C1" name="بنين" entireclass="0" divisiontag="1" studentcount="14"/>
    <group id="G3" classid="C1" name="بنات" entireclass="0" divisiontag="1" studentcount="13"/>
    <group id="G4" classid="C2" name="Entire class" entireclass="1" divisiontag="0"/>
    <group id="G5" classid="C3" name="Entire class" entireclass="1" divisiontag="0"/>
  </groups>
  <lessons columns="id,classids,groupids,subjectid,periodspercard,periodsperweek,teacherids,classroomids,daysdefid,weeksdefid">
    <lesson id="L1" classids="C1" groupids="G1" subjectid="S1" periodspercard="1" periodsperweek="3.0" teacherids="T1" daysdefid="*1" weeksdefid="*1"/>
    <lesson id="L2" classids="C1" groupids="G2" subjectid="S2" periodspercard="2" periodsperweek="2.0" teacherids="T3" daysdefid="*1" weeksdefid="*1"/>
    <lesson id="L3" classids="C1" groupids="G3" subjectid="S2" periodspercard="2" periodsperweek="2.0" teacherids="T2" daysdefid="*1" weeksdefid="*1"/>
    <lesson id="L4" classids="C2,C3" groupids="G4,G5" subjectid="S3" periodspercard="1" periodsperweek="1.0" teacherids="T2" classroomids="R1" daysdefid="*1" weeksdefid="*1"/>
  </lessons>
  <cards columns="lessonid,period,days,weeks,classroomids">
    <card lessonid="L1" period="1" days="10000" weeks="1"/>
    <card lessonid="L1" period="2" days="01000" weeks="1"/>
    <card lessonid="L1" period="1" days="00100" weeks="1"/>
    <card lessonid="L2" period="3" days="10000" weeks="1"/>
    <card lessonid="L2" period="4" days="10000" weeks="1"/>
    <card lessonid="L3" period="3" days="10000" weeks="1"/>
    <card lessonid="L3" period="4" days="10000" weeks="1"/>
    <card lessonid="L4" period="1" days="01000" weeks="1" classroomids="R1"/>
  </cards>
</timetable>
"""


@pytest.fixture
def base(admin):
    for dow, ar, order in [(7, "الأحد", 1), (1, "الاثنين", 2), (2, "الثلاثاء", 3), (3, "الأربعاء", 4), (4, "الخميس", 5)]:
        admin.ok("post", "/api/weekdays", {"iso_dow": dow, "name_ar": ar, "sort_order": order, "is_school_day": True})
    return admin


def upload(a, url, data: bytes, name: str, **form):
    headers = {} if url.endswith("preview") else None
    body = {"file": (io.BytesIO(data), name), **{k: v for k, v in form.items() if v is not None}}
    if headers is None:
        r = a.post(url, data=body, content_type="multipart/form-data")
    else:
        r = a.c.post(url, data=body, content_type="multipart/form-data")
    return r


def test_asc_preview_changes_nothing(base, ctx):
    r = upload(base, "/api/import/preview", ASC_XML.encode(), "school.xml", new_timetable_name="من aSc")
    assert r.status_code == 200, r.get_json()
    rep = r.get_json()
    assert rep["committed"] is False
    assert rep["summary"]["teachers"]["created"] == 3 and rep["summary"]["lessons"]["created"] == 4
    assert ctx.query(Teacher).count() == 0 and ctx.query(Lesson).count() == 0


def test_asc_import_builds_structure_and_places_cards(base, ctx):
    r = upload(base, "/api/import/commit", ASC_XML.encode(), "school.xml", new_timetable_name="من aSc",
               stage_name="المرحلة الأساسية")
    assert r.status_code == 200, r.get_json()
    rep = r.get_json()
    assert rep["errors"] == []
    assert rep["timetable"]["created"] and rep["timetable"]["name"] == "من aSc"
    assert rep["cards"] == {"placed": 6, "unplaced": 0}   # L1: 3 singles, L2/L3: one double each, L4: 1
    # grades: 'السابع' from the grades list, '8' split from the class name '8A'
    assert sorted(g.name_ar for g in ctx.query(Grade)) == ["8", "السابع"]
    assert {s.name_ar for s in ctx.query(Section)} == {"7أ", "7ب", "8A"}
    assert [st.name_ar for st in ctx.query(Stage)] == ["المرحلة الأساسية"]
    div = ctx.query(Division).one()
    assert sorted(g.name_ar for g in ctx.query(StudentGroup).filter_by(division_id=div.id)) == ["بنات", "بنين"]
    huda = ctx.query(Teacher).filter_by(name_ar="Huda Saleh").one()
    assert huda.gender == "f" and huda.name_en == "Huda Saleh"
    assert {s.name_ar for s in huda.subjects} == {"التربية الرياضية", "Science"}
    sec7a = ctx.query(Section).filter_by(name_ar="7أ").one()
    assert sec7a.class_teacher_id == ctx.query(Teacher).filter_by(short="أح").one().id
    # boys and girls PE share Sunday periods 3–4 (same division, different groups)
    pe = ctx.query(Subject).filter_by(name_ar="التربية الرياضية").one()
    pe_cards = ctx.query(Card).join(Lesson).filter(Lesson.subject_id == pe.id).all()
    assert sorted((c.period_no, c.duration) for c in pe_cards) == [(3, 2), (3, 2)]
    # a combined lesson for two sections of different grades
    sci = ctx.query(Lesson).join(Subject).filter(Subject.name_ar == "Science").one()
    assert len(sci.targets) == 2 and sci.cards[0].room_id is not None

    # the grid & validation accept the result
    v = base.ok("get", f"/api/timetables/{rep['timetable']['id']}/validate")
    assert v["errors"] == [], v["errors"]

    # Re-importing into the same timetable duplicates nothing
    r2 = upload(base, "/api/import/commit", ASC_XML.encode(), "school.xml", timetable_id=rep["timetable"]["id"],
                stage_name="المرحلة الأساسية")
    rep2 = r2.get_json()
    assert r2.status_code == 200, rep2
    assert all(v["created"] == 0 for v in rep2["summary"].values()), rep2["summary"]
    assert rep2["summary"]["lessons"]["unchanged"] == 4
    assert ctx.query(Lesson).count() == 4 and ctx.query(Teacher).count() == 3


def test_roz_wrapping_xml_is_read_and_binary_roz_is_explained(base):
    r = upload(base, "/api/import/preview", zlib.compress(ASC_XML.encode()), "school.roz")
    assert r.status_code == 200, r.get_json()
    r = upload(base, "/api/import/preview", b"\x00\x01ASC-binary" * 50, "school.roz")
    body = r.get_json()
    assert r.status_code == 400 and body["details"]["reason"] == "unsupported_roz"
    assert "aSc Timetables XML" in body["message"]


def test_asc_clash_is_left_unplaced_with_warning(base):
    xml = ASC_XML.replace('<card lessonid="L4" period="1" days="01000"', '<card lessonid="L4" period="2" days="01000"')
    # L1 has Monday period 2 for 7أ, L4 is taught by Huda (T2) — make it clash on the teacher instead:
    xml = xml.replace('teacherids="T1" daysdefid="*1" weeksdefid="*1"/>', 'teacherids="T2" daysdefid="*1" weeksdefid="*1"/>', 1)
    rep = upload(base, "/api/import/commit", xml.encode(), "x.xml").get_json()
    assert rep["cards"]["unplaced"] == 1
    assert any("مشغول" in w["message"] and "أحمد" not in w["message"] for w in rep["warnings"])


def _xlsx(sheets: dict) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for title, rows in sheets.items():
        ws = wb.create_sheet(title)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_template_downloads_and_imports_as_is(base, ctx):
    r = base.get("/api/import/template.xlsx")
    assert r.status_code == 200
    wb = load_workbook(io.BytesIO(r.data))
    assert wb.sheetnames == ["تعليمات", "المباحث", "القاعات", "المعلمون", "الشعب", "الدروس"]
    rep = upload(base, "/api/import/commit", r.data, "قالب.xlsx", new_timetable_name="تجربة").get_json()
    assert rep["error_count"] == 0, rep["errors"]
    s = rep["summary"]
    assert (s["subjects"]["created"], s["rooms"]["created"], s["teachers"]["created"], s["sections"]["created"],
            s["lessons"]["created"]) == (2, 2, 2, 2, 2)
    ahmad = ctx.query(Teacher).filter_by(name_ar="أحمد محمود").one()
    assert ahmad.gender == "m" and ahmad.target_weekly_periods == 24 and [x.name_ar for x in ahmad.stages] == ["المرحلة الأساسية"]
    math = ctx.query(Lesson).join(Subject).filter(Subject.name_ar == "الرياضيات").one()
    assert len(math.targets) == 2 and math.periods_per_week == 5
    pe = ctx.query(Lesson).join(Subject).filter(Subject.name_ar == "التربية الرياضية").one()
    assert [c.duration for c in pe.cards] == [2] and pe.preferred_room_id is not None


def test_xlsx_updates_existing_and_reports_row_errors(base, ctx):
    data = _xlsx({
        "Teachers": [["قائمة المعلمين"], ["Name", "Gender", "Email"], ["أحمد", "M", "a@x.test"], ["سارة", "انثى", ""]],
        "الشعب": [["المرحلة", "الصف", "الشعبة"], ["الأساسية", "الخامس", "أ"], ["الأساسية", "الخامس", "ب"]],
        "الدروس": [["المبحث", "الشعبة", "المعلم", "الحصص الأسبوعية"],
                   ["العلوم", "الخامس / أ ، الخامس/ب", "أحمد", 4],
                   ["العلوم", "السادس / أ", "أحمد", 4],          # unknown grade → stage is known, so it is created
                   ["الرسم", "أ", "سارة", 2],                   # ambiguous section name
                   ["الرسم", "الخامس / أ", "سارة", "كثير"]],    # bad number
    })
    rep = upload(base, "/api/import/commit", data, "d.xlsx", new_timetable_name="ت").get_json()
    rows = sorted((e["where"], e["row"]) for e in rep["errors"])
    assert rows == [("الدروس", 4), ("الدروس", 5)], rep["errors"]
    assert ctx.query(Teacher).filter_by(name_ar="سارة").one().gender == "f"
    # a second file with a changed e-mail updates, never duplicates
    data2 = _xlsx({"المعلمون": [["الاسم", "البريد الإلكتروني"], ["أحمد", "new@x.test"], ["احمد", ""]]})
    rep2 = upload(base, "/api/import/commit", data2, "t.xlsx").get_json()
    assert rep2["summary"]["teachers"] == {"created": 0, "updated": 1, "unchanged": 1}
    assert ctx.query(Teacher).filter_by(name_ar="أحمد").one().email == "new@x.test"


def test_csv_windows_arabic_semicolon(base, ctx):
    text = "المبحث;الاختصار;اللون\nالرياضيات;ر;4F81BD\nاللغة العربية;ع;\n"
    rep = upload(base, "/api/import/commit", text.encode("cp1256"), "subjects.csv", kind="subjects").get_json()
    assert rep["summary"]["subjects"]["created"] == 2, rep
    assert ctx.query(Subject).filter_by(name_ar="الرياضيات").one().color == "#4F81BD"


def test_import_is_admin_only_and_rejects_unknown_types(base, api):
    r = upload(base, "/api/import/preview", b"hello", "notes.pdf")
    assert r.status_code == 400 and r.get_json()["details"]["reason"] == "unsupported_file"
    from tests.helpers import make_user
    make_user("v@x.test", role="viewer")
    base.logout()
    api.login("v@x.test")
    r = upload(api, "/api/import/preview", ASC_XML.encode(), "a.xml")
    assert r.status_code == 403


def test_asc_with_several_stages_goes_to_its_own_stage(base, ctx):
    base.ok("post", "/api/stages", {"name_ar": "أساسي"})
    base.ok("post", "/api/stages", {"name_ar": "ثانوي"})
    rep = upload(base, "/api/import/commit", ASC_XML.encode(), "s.xml").get_json()
    assert rep["error_count"] == 0 and rep["summary"]["lessons"]["created"] == 4
    assert rep["summary"]["stages"]["created"] == 1
    assert {g.stage.name_ar for g in ctx.query(Grade)} == {"مستورد من aSc"}


def test_asc_cp1256_names_declared_as_1252_times_and_meetings(base, ctx):
    """Real aSc exports: Arabic typed in cp1256 but declared windows-1252, out-of-order period times,
    and department meetings (lessons without a class)."""
    xml = ASC_XML.replace('encoding="UTF-8"', 'encoding="windows-1252"')
    xml = xml.replace('starttime="7:45" endtime="8:30"', 'starttime="18:00" endtime="18:45"')
    xml = xml.replace('<lesson id="L4"', '<lesson id="M1" classids="" groupids="" subjectid="S1" periodspercard="1" '
                      'periodsperweek="1.0" teacherids="T1,T3" daysdefid="*1" weeksdefid="*1"/>\n    <lesson id="L4"')
    xml = xml.replace('</cards>', '<card lessonid="M1" period="4" days="00001" weeks="1"/></cards>')
    rep = upload(base, "/api/import/commit", xml.encode("cp1256"), "real.xml").get_json()
    assert rep["error_count"] == 0, rep["errors"]
    assert {g.name_ar for g in ctx.query(StudentGroup)} == {"بنين", "بنات"}
    from app.models import Availability, BellSlot
    starts = [s.starts_at.strftime("%H:%M") for s in ctx.query(BellSlot).filter_by(kind="lesson").order_by(BellSlot.period_no)]
    assert starts == ["07:25", "08:30", "09:35", "10:20"]
    assert ctx.query(Availability).count() == 2   # two teachers × one meeting slot
    assert any("اجتماع بلا شعبة" in w["message"] for w in rep["warnings"])
    assert any("صُحِّحت" in w["message"] for w in rep["warnings"])
