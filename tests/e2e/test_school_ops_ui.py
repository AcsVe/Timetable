"""Browser tests for the load rules, duty roster, exam timetable, grid colours and list bulk actions."""
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
