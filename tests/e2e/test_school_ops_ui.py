"""Browser tests for the load rules, duty roster, exam timetable, grid colours and list bulk actions."""
import re

from playwright.sync_api import expect


def test_load_rule_from_the_screen(page):
    page.goto(f"{page.base}/#/loads")
    page.click("text=+ قاعدة نصاب جديدة")
    page.fill("#f-name", "نصاب الأساسية")
    page.locator("#f-stage_ids .multi-opts input").first.check()
    page.select_option("#f-mode", "range")
    page.fill("#f-min", "2")
    page.fill("#f-max", "30")
    page.select_option("#f-display", "text")
    page.click("#modal-form button[type=submit]")
    expect(page.locator("table.data").first).to_contain_text("نصاب الأساسية")
    expect(page.locator(".load-badge").first).to_be_visible()
    assert not page.errors


def test_duty_on_two_days_then_bulk_delete(page):
    page.goto(f"{page.base}/#/duties")
    page.click("text=+ مناوبة جديدة")
    days = page.locator("#f-weekday_ids .multi-opts input")
    days.nth(0).check()
    days.nth(1).check()
    page.fill("#f-duty_type", "الطابور الصباحي")
    page.fill("#f-location", "الساحة")
    page.locator("#f-teacher_ids .multi-opts input").first.check()
    page.click("#modal-form button[type=submit]")
    expect(page.locator("table.duty-grid")).to_contain_text("الطابور الصباحي")
    page.select_option("#duty-view", "list")
    expect(page.locator("table.data tbody tr")).to_have_count(2)
    page.locator("table.data thead input[type=checkbox]").check()
    page.click("text=حذف المحدد")
    page.click("#modal-form button.danger")
    expect(page.locator(".muted", has_text="لا توجد مناوبات")).to_be_visible()
    assert not page.errors


def test_exam_with_two_rooms_and_invigilators(page):
    page.goto(f"{page.base}/#/exams")
    page.click("text=+ امتحان جديد")
    page.fill("#f-exam_date", "2027-01-10")
    page.select_option("#f-subject_id", index=1)
    page.locator("#rinv-0 .multi-opts input").first.check()
    page.click("text=+ إضافة قاعة")
    page.locator("#rinv-1 .multi-opts input").first.check()
    page.click("#modal-form button[type=submit]")
    expect(page.locator("table.data tbody tr")).to_have_count(1)
    expect(page.locator(".notice")).to_contain_text("قاعتين")     # the same invigilator in two rooms is flagged
    assert not page.errors


def test_grid_colour_modes_and_search_in_setup(page):
    page.goto(f"{page.base}/#/grid")
    page.wait_for_selector("#grid-color")
    page.select_option("#grid-color", "none")
    expect(page.locator(".card-chip.plain").first).to_be_visible()
    page.select_option("#grid-color", "teacher")
    page.click("#grid-palette")
    expect(page.locator(".palette")).to_contain_text("ألوان المعلمين")
    page.goto(f"{page.base}/#/setup/teachers")
    page.fill(".search-box", "zzzz-no-match")
    expect(page.locator("text=لا توجد نتائج مطابقة للبحث")).to_be_visible()
    assert not page.errors


def test_reports_black_and_white_by_default(page):
    page.goto(f"{page.base}/#/reports")
    page.wait_for_selector("#report-style")
    expect(page.locator("#report-style")).to_have_value("plain")
    expect(page.locator(".report-preview")).to_have_class("report-preview plain")
    page.select_option("#report-kind", "stage-timetable")
    expect(page.locator(".report-table.compact")).to_be_visible()
    assert not page.errors


def test_absence_then_fair_automatic_cover(page):
    from tests.e2e.test_ui import cell, open_grid, tray_chip
    open_grid(page, "الخامس / أ")
    tray_chip(page, "العلوم").drag_to(cell(page, 0, 1))          # Sunday, period 1
    expect(page.locator("#toast")).to_contain_text("تم وضع الحصة")
    page.goto(f"{page.base}/#/cover?date=2026-10-04")             # a Sunday
    page.click("#add-absence")
    page.locator("#f-teacher_ids .multi-opts label", has_text="محمود").locator("input").check()
    page.fill("#f-reason", "إجازة مرضية")
    page.click("#modal-form button[type=submit]")
    expect(page.locator("select.decision")).to_have_count(1)
    page.click("#cover-auto")
    expect(page.locator("#toast")).to_contain_text("وُزِّعت: 1")
    expect(page.locator("select.decision")).to_have_value(re.compile("^t:"))
    page.click("text=رسائل البدلاء")
    expect(page.locator(".msg-text")).to_contain_text("للإشغال")
    assert "null" not in page.locator("#modal-form").inner_text()
    assert not page.errors


def test_students_screen_bulk_move_and_mail_page(page):
    page.goto(f"{page.base}/#/setup/students")
    for name in ("أمل", "باسل"):
        page.click("text=+ إضافة")
        page.fill("#f-name_ar", name)
        page.select_option("#f-section_id", index=1)
        page.click("#modal-form button[type=submit]")
        expect(page.locator("table.data")).to_contain_text(name)
    page.locator("table.data thead input[type=checkbox]").check()
    page.click("text=نقل المحدد إلى شعبة")
    page.select_option("#f-section_id", index=2)
    page.click("#modal-form button[type=submit]")
    expect(page.locator("#toast")).to_contain_text("نُقل: 2")
    page.goto(f"{page.base}/#/mail")
    expect(page.locator(".notice.warn")).to_contain_text("غير مُعَدّ")
    page.fill("#mail-tenant_id", "not a tenant")
    page.click("#mail-save")
    expect(page.locator("#toast")).to_contain_text("Tenant ID")
    assert not page.errors


def test_generator_runs_in_the_background_and_opens_the_result(page, app):
    app.config["GENERATOR_MANUAL"] = False
    try:
        page.goto(f"{page.base}/#/generate")
        expect(page.locator(".notice.ok")).to_contain_text("فحص الجدوى")
        page.select_option("#gen-time", "30")
        page.click("#gen-start")
        expect(page.locator("#gen-open")).to_be_visible(timeout=90000)
        expect(page.locator(".gen-metrics")).to_contain_text("الحصص الموضوعة")
        page.click("#gen-open")
        expect(page.locator("#tt-select option:checked")).to_contain_text("مولَّد")
        assert not page.errors
    finally:
        app.config["GENERATOR_MANUAL"] = True


def test_delete_timetable_with_its_contents(page):
    page.goto(f"{page.base}/#/timetables")
    page.locator("td.actions").first.locator("button", has_text="نسخ كمسودة").click()
    page.fill("#f-name", "مسودة للحذف")
    page.click("#modal-form button[type=submit]")
    row = page.locator("table.data tbody tr", has_text="مسودة للحذف")
    row.locator("button", has_text="حذف").click()
    page.click("#modal-form button.danger")                       # first question: delete it?
    expect(page.locator("#modal-form")).to_contain_text("يحتوي على")   # then: what goes with it
    expect(page.locator("#modal-form")).to_contain_text("دروس")
    page.click("#modal-form button.danger")
    expect(page.locator("#toast")).to_contain_text("حُذف الجدول")
    expect(page.locator("table.data tbody tr", has_text="مسودة للحذف")).to_have_count(0)
    assert not page.errors


def test_rename_a_floor_and_add_a_corridor(page):
    page.goto(f"{page.base}/#/duties")
    page.click("text=+ مناوبة جديدة")
    page.locator("#f-weekday_ids .multi-opts input").first.check()
    page.fill("#f-duty_type", "الممرات")
    page.fill("#f-location", "الطابق الأول › الممر الشرقي")
    page.click("#modal-form button[type=submit]")
    expect(page.locator("table.duty-grid")).to_contain_text("الممر الشرقي")
    page.click("#edit-lists")
    floors = page.locator("#list-locations .tree-node", has=page.locator("input.tree-main[value='الطابق الأول']"))
    floors.locator("input.tree-main").fill("الطابق 1")
    floors.locator("input.tree-sub").first.fill("ممر الإدارة")
    floors.locator("button", has_text="+ ممر أو جزء").click()
    page.keyboard.type("ممر المختبرات")
    page.click("#modal-form button[type=submit]")
    expect(page.locator("#toast")).to_contain_text("عُدِّلت السجلات المرتبطة: 1")
    expect(page.locator("table.duty-grid")).to_contain_text("الطابق 1 › ممر الإدارة")
    page.click("#edit-lists")
    assert page.locator("#list-locations input.tree-sub").evaluate_all("xs => xs.map(x => x.value)").count("ممر المختبرات") == 1
    assert not page.errors


def test_meeting_from_its_page_shows_in_the_teacher_grid(page):
    page.goto(f"{page.base}/#/setup/teachers")
    row = page.locator("table.data tbody tr", has_text="محمود")
    row.locator("button", has_text="تعديل").click()
    page.check("#f-is_head")
    page.click("#modal-form button[type=submit]")
    expect(page.locator("table.data tbody tr", has_text="محمود")).to_contain_text("✓")
    page.goto(f"{page.base}/#/meetings")
    page.click("#add-meeting")
    page.fill("#f-title", "اجتماع رؤساء الأقسام")
    page.click("#add-heads")
    expect(page.locator("#f-teachers .count")).to_contain_text("1 من")
    page.select_option("#f-weekday_id", label="الأحد")
    page.fill("#f-period_no", "3")
    page.click("#modal-form button[type=submit]")
    expect(page.locator("table.data tbody tr")).to_contain_text("اجتماع رؤساء الأقسام")
    expect(page.locator("table.data tbody tr")).to_contain_text("الحصة 3")
    page.goto(f"{page.base}/#/reports")
    page.select_option("#report-kind", "meetings")
    expect(page.locator(".report-preview")).to_contain_text("اجتماع رؤساء الأقسام")
    assert not page.errors


def test_study_plan_matrix_check_and_create_missing_lessons(page):
    page.goto(f"{page.base}/#/curriculum")
    rows = page.locator(".plan-matrix tbody tr")
    expect(rows.first).to_be_visible()
    n = rows.count()
    for i in range(n):                             # the first grade: 2 periods of every subject
        cell = rows.nth(i).locator("input").first
        cell.fill("2")
        cell.press("Tab")                          # moving on keeps the focus (no redraw)
    expect(page.locator("#plan-save")).to_contain_text(f"({n})")
    page.click("#plan-save")
    expect(page.locator("#toast")).to_contain_text("تم الحفظ")
    expect(page.locator("#plan-apply-all")).to_be_visible()      # the check reloads after saving
    expect(page.locator(".stats")).to_contain_text("غير موجود")
    page.click("#plan-apply-all")
    expect(page.locator("#toast")).to_contain_text("دروس جديدة")
    page.goto(f"{page.base}/#/validate")
    expect(page.locator("body")).to_be_visible()
    assert not page.errors


def test_holiday_and_plan_builder(page):
    page.goto(f"{page.base}/#/setup/terms")
    page.locator("table.data tbody tr").first.locator("button", has_text="تعديل").click()
    page.fill("#f-start_date", "2026-09-06")
    page.fill("#f-end_date", "2027-01-14")
    page.click("#modal-form button[type=submit]")
    expect(page.locator("table.data tbody tr").first).to_contain_text("2026-09-06")
    page.goto(f"{page.base}/#/setup/holidays")
    page.click("text=+ إضافة")
    page.fill("#f-name_ar", "عطلة رسمية")
    page.fill("#f-date_from", "2026-09-17")
    page.fill("#f-date_to", "2026-09-17")
    page.click("#modal-form button[type=submit]")
    expect(page.locator("table.data")).to_contain_text("عطلة رسمية")
    page.goto(f"{page.base}/#/plans")
    page.click("#plan-new")
    page.fill("#f-name", "خطة شهرية")
    page.select_option("#f-period_type", "month")
    page.click("#modal-form button[type=submit]")
    expect(page.locator(".plan-matrix, p.muted").first).to_be_visible()
    page.check("text=كل المباحث")
    cell = page.locator(".plan-matrix tbody input").first
    cell.fill("12")
    cell.press("Tab")
    page.click("#plan-save")
    expect(page.locator("#toast")).to_contain_text("تم الحفظ")
    page.click("#plan-approve")
    expect(page.locator("h1 .chip")).to_contain_text("معتمدة")
    page.click("#plan-tab-analysis")
    expect(page.locator(".stats")).to_contain_text("نقص")
    page.select_option("#plan-view", "teachers")
    expect(page.locator("table.data")).to_contain_text("النصاب للفترة")
    assert not page.errors
