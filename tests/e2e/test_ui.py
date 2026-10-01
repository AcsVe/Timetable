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
    """day_index: 0 = first school day (works for both layouts: days as rows or as columns)."""
    return page.locator(f"table.tt-grid td.slot[data-di='{day_index}'][data-period='{period}']")


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


def test_orientation_toggle(page):
    open_grid(page, "الخامس / أ")
    expect(page.locator("table.tt-grid.days-rows")).to_be_visible()          # default: days as rows (ASC / SCL style)
    page.select_option("#grid-orient", "cols")
    expect(page.locator("table.tt-grid.days-rows")).to_have_count(0)
    tray_chip(page, "الرياضيات").drag_to(cell(page, 2, 3))
    expect(cell(page, 2, 3).locator(".card-chip")).to_contain_text("الرياضيات")
    page.select_option("#grid-orient", "rows")
    expect(cell(page, 2, 3).locator(".card-chip")).to_contain_text("الرياضيات")


def test_whole_school_view_places_only_in_the_cards_rows(page):
    page.goto(f"{page.base}/#/grid")
    page.select_option("#grid-mode", "whole-sections")
    expect(page.locator("table.tt-grid.whole tbody tr")).to_have_count(6)
    page.select_option("#grid-stage", label="الأساسية")
    expect(page.locator("table.tt-grid.whole tbody tr")).to_have_count(4)
    rows = page.locator("table.tt-grid.whole tbody tr")
    row_5a = rows.nth(0)
    row_5b = rows.nth(1)
    chip = page.locator(".tray .card-chip").first
    chip.click()
    # the first tray card belongs to 5/A: its row is coloured, 5/B's row is left alone
    expect(row_5a.locator("td.slot.allowed").first).to_be_visible()
    expect(row_5b.locator("td.slot.allowed")).to_have_count(0)
    row_5b.locator("td.slot:not(.none)").first.click()
    expect(page.locator("#toast")).to_contain_text("لا تخص")
    row_5a.locator("td.slot.allowed").first.click()
    expect(page.locator("#toast")).to_contain_text("تم وضع الحصة")
    expect(page.locator("table.tt-grid.whole tbody tr").nth(0).locator(".card-chip")).to_have_count(1)


def test_section_quick_actions_and_class_teacher(page):
    page.goto(f"{page.base}/#/setup/sections")
    row = page.locator("table.data tbody tr", has_text="أ").first
    row.locator("button", has_text="تعديل").click()
    page.select_option("#f-class_teacher_id", label="أحمد خليل")
    page.click("#modal-form button[type=submit]")
    expect(page.locator("table.data")).to_contain_text("أحمد خليل")
    page.locator("table.data tbody tr", has_text="أحمد خليل").first.locator("button", has_text="الدروس").click()
    expect(page).to_have_url(re.compile("#/lessons"))
    expect(page.locator("table.data tbody tr[data-id]")).to_have_count(8)


def test_teacher_list_shows_period_counts(page):
    page.goto(f"{page.base}/#/setup/teachers")
    row = page.locator("table.data tbody tr", has_text="سارة يوسف")
    expect(row).to_contain_text("26")      # 4 basic sections × 4 + 2 secondary × 5


def test_navigation_scroll_and_anchors(page, live_server):
    """A sidebar link opens the page at its top (nothing hidden under the topbar); back restores the
    previous position; ?to= anchors land just below the pinned bars."""
    page.goto(f"{live_server}/#/lessons")
    page.wait_for_selector(".toolbar.sticky")
    page.evaluate("window.scrollTo(0, 600)")
    page.wait_for_timeout(200)
    y_before = page.evaluate("window.scrollY")
    page.click(".sidebar a[href='#/bells']")
    page.wait_for_selector("#templates")
    page.wait_for_timeout(200)
    assert page.evaluate("window.scrollY") == 0
    page.go_back()
    page.wait_for_selector(".toolbar.sticky")
    page.wait_for_timeout(300)
    assert page.evaluate("window.scrollY") == y_before
    page.goto(f"{live_server}/#/bells?to=assign")
    page.wait_for_selector("#assign")
    page.wait_for_timeout(300)
    top = page.evaluate("document.getElementById('assign').getBoundingClientRect().top")
    bar = page.evaluate("document.querySelector('.topbar').getBoundingClientRect().bottom")
    assert top >= bar
    page.click(".page-nav button >> nth=0")
    page.wait_for_timeout(800)
    top = page.evaluate("document.getElementById('templates').getBoundingClientRect().top")
    nav = page.evaluate("document.querySelector('.page-nav').getBoundingClientRect().bottom")
    assert top >= min(nav, 2000) - 1 or page.evaluate("window.scrollY") == 0


def test_import_asc_xml_preview_then_commit(page, tmp_path):
    from tests.test_import import ASC_XML
    f = tmp_path / "school.xml"
    f.write_text(ASC_XML, encoding="utf-8")
    # the start page leads straight to the import
    page.goto(f"{page.base}/#/home")
    expect(page.locator(".steps li")).to_have_count(9)
    page.click("#home-import")
    page.wait_for_selector("#import-file", state="attached")
    page.evaluate("document.getElementById('import-file').dataset.mark = '1'")
    page.set_input_files("#import-file", str(f))
    page.wait_for_timeout(500)
    # the view is rendered once: the chosen file is not wiped by a second render
    assert page.evaluate("document.getElementById('import-file').dataset.mark") == "1"
    page.click("summary:has-text('خيارات إضافية')")
    page.select_option("#import-stage", label="مرحلة جديدة…")
    page.fill("#import-stage-name", "مرحلة aSc")
    page.click("#import-preview")
    expect(page.locator("#import-summary h2")).to_contain_text("لم يُحفظ شيء")
    expect(page.locator("#import-summary")).to_contain_text("الدروس")
    page.click("#import-commit")
    expect(page.locator("#import-summary h2")).to_have_text("تم الاستيراد")
    expect(page.locator("#tt-select option:checked")).to_contain_text("مستورد: school")
    # the summary is not hidden under the top bar
    top = page.evaluate("document.getElementById('import-summary').getBoundingClientRect().top")
    bar = page.evaluate("document.querySelector('.topbar').getBoundingClientRect().bottom")
    assert top >= bar - 1
    page.click("text=فتح شبكة الجدول")
    page.wait_for_selector("#grid-entity")
    assert page.errors == []


PHONE_PAGES = ["grid", "lessons", "validate", "reports", "timetables", "bells", "availability", "import", "school",
               "setup/stages", "setup/grades", "setup/sections", "setup/divisions", "setup/subjects",
               "setup/teachers", "setup/rooms", "setup/academic-years", "setup/terms", "setup/weekdays",
               "setup/buildings", "setup/users"]


def test_phone_layout_never_scrolls_sideways(page):
    """On a phone the page itself never scrolls sideways (wide tables scroll inside their own box),
    and the top bar stays compact (two rows at most)."""
    page.set_viewport_size({"width": 390, "height": 844})
    wide = []
    for p in PHONE_PAGES:
        page.goto(f"{page.base}/#/{p}")
        page.wait_for_selector("#view h1, #view .title, #view table", timeout=10000)
        page.wait_for_timeout(250)
        sw = page.evaluate("document.documentElement.scrollWidth")
        if sw > 391:
            wide.append((p, sw))
    assert wide == []
    bar = page.evaluate("document.querySelector('.topbar').offsetHeight")
    assert bar <= 110, bar
    assert page.errors == []
