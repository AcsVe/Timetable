"""Print preview and print settings, frozen table headers, and the side menu's favourites and groups."""
from playwright.sync_api import expect

from tests.e2e.conftest import PASSWORD


def test_print_preview_shows_the_pdf_with_the_chosen_settings(page):
    page.goto(f"{page.base}/#/reports")
    page.select_option("#report-kind", "section-timetable")
    expect(page.locator(".report-grid").first).to_be_visible()
    page.select_option("#print-header", "0")
    page.select_option("#print-size", "xlarge")
    page.click("#print-preview-btn")
    dlg = page.locator("#print-preview")
    expect(dlg).to_be_visible()
    src = page.get_attribute("#print-preview iframe", "src")
    assert "format=pdf" in src and "disposition=inline" in src and "header=0" in src and "size=xlarge" in src
    r = page.request.get(page.base + src)
    assert r.ok and r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].startswith("inline") and r.body()[:4] == b"%PDF"
    expect(page.locator("#print-now")).to_be_visible()
    dlg.locator("button", has_text="إغلاق").click()
    expect(page.locator("#print-preview")).to_have_count(0)
    # the settings are remembered
    page.reload()
    page.wait_for_selector("#print-size")
    assert page.input_value("#print-size") == "xlarge" and page.input_value("#print-header") == "0"
    assert page.errors == []


def test_master_timetable_keeps_its_header_row_and_first_column_in_view(page):
    page.goto(f"{page.base}/#/reports")
    page.select_option("#report-kind", "stage-timetable")
    box = page.locator(".report-block .grid-scroll").first
    expect(box.locator("tbody tr").first).to_be_visible()
    res = box.evaluate("""s => {
        s.scrollTop = 200; s.scrollLeft = -400;   // RTL: scrolling towards the later columns
        const th = s.querySelector('thead'), first = s.querySelector('tbody tr:nth-child(3) > :first-child');
        return { head: th.getBoundingClientRect().top - s.getBoundingClientRect().top,
                 col: s.getBoundingClientRect().right - first.getBoundingClientRect().right,
                 scrolled: s.scrollTop };
    }""")
    if res["scrolled"]:      # the demo table may be short enough not to scroll at all
        assert abs(res["head"]) < 2, res
    assert abs(res["col"]) < 20, res


def test_side_menu_favourites_and_folded_groups_follow_the_user(page, browser, live_server):
    page.click('.nav-star[data-route="reports"]')
    page.click('button.nav-title[data-group="system"]')
    expect(page.locator(".nav-favs .nav-fav-list a")).to_have_text(["التقارير"])
    expect(page.locator('.nav-group[data-group="system"]')).to_have_class("nav-group collapsed")
    expect(page.locator('button.nav-title[data-group="system"]')).to_have_attribute("aria-expanded", "false")
    page.wait_for_timeout(800)      # saved after a short pause
    # another device: nothing stored locally, the account brings the menu back
    ctx = browser.new_context(viewport={"width": 390, "height": 844})
    other = ctx.new_page()
    other.goto(f"{live_server}/auth/login")
    other.fill("#email", "admin@school.test")
    other.fill("#password", PASSWORD)
    other.click("button[type=submit]")
    other.wait_for_selector(".nav-fav-list a", state="attached")   # the phone menu is closed
    assert other.eval_on_selector_all(".nav-fav-list a", "e => e.map(x => x.textContent)") == ["التقارير"]
    assert other.get_attribute('.nav-group[data-group="system"]', "class") == "nav-group collapsed"
    # opening a page of a folded group unfolds it on screen
    other.goto(f"{live_server}/#/setup/weekdays")
    other.wait_for_timeout(400)
    assert "collapsed" not in other.get_attribute('.nav-group[data-group="system"]', "class")
    ctx.close()
    page.click('.nav-fav-list .nav-star')
    expect(page.locator(".nav-favs")).to_be_hidden()
    assert page.errors == []
