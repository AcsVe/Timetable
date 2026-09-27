"""End-to-end UI tests (Arabic RTL UI, drag & drop, conflicts, i18n, offline read-only)."""
import re

from playwright.sync_api import expect


def open_grid(page, section_label):
    page.goto(f"{page.base}/#/grid")
    page.wait_for_selector("#grid-entity")
    page.select_option("#grid-mode", "section")
    page.select_option("#grid-entity", label=section_label)
    page.wait_for_selector(".tray")


def cell(page, day_index, period):
    """day_index: 0 = first school day column."""
    return page.locator(f"table.tt-grid tbody tr:nth-child({period}) td.slot").nth(day_index)


def tray_chip(page, subject):
    return page.locator(".tray .card-chip", has_text=subject).first


def placed_count(page):
    return int(re.search(r"(\d+) / \d+", page.locator(".legend").last.inner_text()).group(1))


def test_shell_renders_rtl_without_errors(page):
    expect(page.locator("html")).to_have_attribute("dir", "rtl")
    expect(page.locator("#school-name")).to_have_text("مدرسة تجريبية")
    page.goto(f"{page.base}/#/lessons")
    expect(page.locator("h1.title")).to_contain_text("الدروس والتوزيع")
    expect(page.locator("table.data tbody tr[data-id]")).to_have_count(40)
    for route in ("timetables", "bells", "validate", "availability", "setup/teachers", "setup/divisions", "setup/users"):
        page.goto(f"{page.base}/#/{route}")
        page.wait_for_selector("h1.title")
        assert "null" not in page.locator("#view").inner_text()
    assert page.errors == []


def test_drag_and_drop_places_and_persists(page):
    open_grid(page, "الخامس / أ")
    assert placed_count(page) == 0
    tray_chip(page, "الرياضيات").drag_to(cell(page, 0, 1))
    expect(page.locator("#toast")).to_contain_text("تم وضع الحصة")
    expect(cell(page, 0, 1).locator(".card-chip")).to_contain_text("الرياضيات")
    page.reload()
    page.wait_for_selector(".tray")
    expect(cell(page, 0, 1).locator(".card-chip")).to_contain_text("الرياضيات")
    assert placed_count(page) == 1


def test_conflicting_cells_are_red_and_drop_is_refused(page):
    open_grid(page, "الخامس / أ")
    tray_chip(page, "الرياضيات").drag_to(cell(page, 0, 1))            # سارة: Sunday P1 in 5/A
    expect(page.locator("#toast")).to_contain_text("تم وضع الحصة")
    open_grid(page, "الخامس / ب")
    chip = tray_chip(page, "الرياضيات")                                  # سارة again, in 5/B
    chip.click()                                                         # tap-to-pick colours the grid
    expect(cell(page, 0, 1)).to_have_class(re.compile("blocked"))
    expect(cell(page, 0, 2)).to_have_class(re.compile("allowed"))
    assert "سارة" in cell(page, 0, 1).get_attribute("title")
    cell(page, 0, 1).click()                                             # try anyway
    expect(page.locator("#toast")).to_contain_text("مشغول")
    assert placed_count(page) == 0
    tray_chip(page, "الرياضيات").click()
    cell(page, 0, 2).click()                                             # tap-to-place on a green cell
    expect(page.locator("#toast")).to_contain_text("تم وضع الحصة")
    expect(cell(page, 0, 2).locator(".card-chip")).to_contain_text("الرياضيات")
    assert placed_count(page) == 1


def test_boys_and_girls_pe_share_a_cell(page):
    open_grid(page, "الخامس / أ")
    page.locator(".tray .card-chip", has_text="أولاد").first.drag_to(cell(page, 1, 4))
    expect(page.locator("#toast")).to_contain_text("تم وضع الحصة")
    page.locator(".tray .card-chip", has_text="بنات").first.drag_to(cell(page, 1, 4))
    expect(page.locator("#toast")).to_contain_text("تم وضع الحصة")
    expect(cell(page, 1, 4).locator(".card-chip")).to_have_count(2)
    # a music/drama group is a different division → the same cell is blocked
    page.locator(".tray .card-chip", has_text="موسيقى").first.click()
    expect(cell(page, 1, 4)).to_have_class(re.compile("blocked"))


def test_short_day_has_no_sixth_period_and_unplace_via_tray(page):
    open_grid(page, "الخامس / أ")
    expect(cell(page, 4, 6)).to_have_class(re.compile("none"))           # Thursday: short-day template (5 periods)
    tray_chip(page, "العلوم").drag_to(cell(page, 4, 5))
    expect(page.locator("#toast")).to_contain_text("تم وضع الحصة")
    cell(page, 4, 5).locator(".card-chip").drag_to(page.locator(".tray"), target_position={"x": 30, "y": 15})
    expect(page.locator("#toast")).to_contain_text("أُزيلت الحصة")
    assert placed_count(page) == 0


def test_add_stage_through_modal_and_language_toggle(page):
    page.goto(f"{page.base}/#/setup/stages")
    page.click("text=+ إضافة")
    page.fill("#f-name_ar", "رياض الأطفال")
    page.click("#modal-form button[type=submit]")
    expect(page.locator("table.data")).to_contain_text("رياض الأطفال")
    page.click("#lang-toggle")
    expect(page.locator("html")).to_have_attribute("dir", "ltr")
    expect(page.locator("#sidebar a[data-route='grid']")).to_have_text("Timetable grid")
    expect(page.locator("h1.title")).to_have_text("Stages")
    page.click("#lang-toggle")
    expect(page.locator("html")).to_have_attribute("dir", "rtl")


def test_create_lesson_from_form(page):
    page.goto(f"{page.base}/#/lessons")
    page.click("text=+ درس جديد")
    page.select_option("#f-subject_id", label="العلوم")
    page.fill("#f-periods_per_week", "3")
    page.select_option("#f-duration", value="2")
    page.locator("#f-teachers label", has_text="محمود علي").locator("input").check()
    page.locator("#f-targets label", has_text="العاشر / أ — كامل الشعبة").locator("input").check()
    page.click("#modal-form button[type=submit]")
    expect(page.locator("#toast")).to_contain_text("تم الحفظ")
    expect(page.locator("table.data tbody tr[data-id]")).to_have_count(41)


def test_offline_is_read_only(page):
    open_grid(page, "الخامس / أ")
    tray_chip(page, "الرياضيات").drag_to(cell(page, 0, 1))
    expect(page.locator("#toast")).to_contain_text("تم وضع الحصة")
    page.reload()                       # make sure the service worker controls the page and data is cached
    page.wait_for_selector(".tray")
    page.wait_for_function("navigator.serviceWorker.controller !== null")
    page.context.set_offline(True)
    page.reload()
    page.wait_for_selector(".tray")
    expect(page.locator("#offline-banner")).to_be_visible()
    expect(cell(page, 0, 1).locator(".card-chip")).to_contain_text("الرياضيات")   # last loaded data is shown
    tray_chip(page, "العلوم").drag_to(cell(page, 0, 3))
    expect(page.locator("#toast")).to_contain_text("لا يوجد اتصال، لا يمكن الحفظ الآن")
    page.context.set_offline(False)


def test_reports_preview_and_exports(page):
    page.goto(f"{page.base}/#/reports")
    page.select_option("#report-kind", "stats-teachers")
    expect(page.locator(".report-table tbody tr").first).to_be_visible()
    expect(page.locator(".report-title")).to_have_text("إحصائيات المعلمين والنصاب")
    page.select_option("select[data-filter='teacher_id']", label="سارة يوسف")
    expect(page.locator(".report-table tbody tr:not(.total)")).to_have_count(1)
    with page.expect_download() as dl:
        page.click("#export-xlsx")
    assert dl.value.suggested_filename.endswith(".xlsx")
    with page.expect_download() as dl:
        page.click("#export-pdf")
    assert dl.value.suggested_filename.endswith(".pdf")
    page.select_option("#report-kind", "section-timetable")
    expect(page.locator(".report-grid").first).to_be_visible()


def test_logo_upload_from_school_page(page):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (80, 80), "#1f4e8c").save(buf, "PNG")
    page.goto(f"{page.base}/#/school")
    page.set_input_files("#logo-file", files=[{"name": "logo.png", "mimeType": "image/png", "buffer": buf.getvalue()}])
    expect(page.locator("#toast")).to_contain_text("تم رفع الشعار")
    expect(page.locator("#school-logo")).to_be_visible()
