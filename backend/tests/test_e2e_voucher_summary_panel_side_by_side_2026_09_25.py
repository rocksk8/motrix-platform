"""傳票：分錄與「摘要來源」面板左右並排（使用者 2026-09-25：「目前是上下，需要額外拖曳到下面再回來上面填寫」）。

內容欄夠寬（約視窗 ≥1340px、字級標準）⇒ 左分錄、右來源面板（sticky、欄內捲動），點來源帶入後焦點回到該行摘要；
不夠寬（1024、字級「特」）⇒ 退回上下排，且不可橫向溢出。
觀測點：分錄表與面板的實際位置（getBoundingClientRect）、document.activeElement。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

from tests.test_e2e_case_mark_all_read_2026_09_24 import live_server  # noqa: F401  (live_server 是 fixture)

QNO = "MQ-VCSPLIT-01"
D = "Alpine.$data(document.querySelector('[x-data]'))"
BOX = """() => { const r = s => { const e = document.querySelector(s); if (!e) return null; const b = e.getBoundingClientRect();
  return { l: b.left, t: b.top, r: b.right, b: b.bottom } };
  return { lines: r('table.vc-lines'), panel: r('[data-testid=summary-panel]'), vw: innerWidth, vh: innerHeight,
           sw: document.documentElement.scrollWidth } }"""


def _seed(client, u, n=6):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
                      " created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (QNO, "已送出", "並排客戶", "並排專案", 1000, 952, json.dumps({}), "2026-01-01T00:00:00",
                       "2026-01-01T00:00:00", "已成案"))
        conn.commit()
    finally:
        conn.close()
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u[0], "password": u[1]}).json()["token"]}
    lines = [{"account_code": "6111", "debit": 100 * i, "credit": 0, "summary": f"第{i}行"} for i in range(1, n + 1)] \
        + [{"account_code": "1113", "debit": 0, "credit": 50 * n * (n + 1), "summary": "付現"}]
    r = client.post("/api/vouchers", headers=h, json={"summary": "並排", "lines": lines})
    assert r.status_code == 200, r.text[:300]
    return r.json()["id"]


def _open(browser, base, u, vid, width, height, zoom=None):
    ctx = browser.new_context(viewport={"width": width, "height": height})
    if zoom:
        ctx.add_init_script(f"try {{ localStorage.setItem('motrix_font_zoom', '{zoom}') }} catch (e) {{}}")
    page = ctx.new_page()
    page.goto(f"{base}/pages/login.html")
    page.fill('input[x-model="username"]', u[0])
    page.fill('input[x-model="password"]', u[1])
    page.click('button:has-text("登入")')
    page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=15000)
    page.goto(f"{base}/pages/voucher.html?id={vid}")
    page.wait_for_function(f"() => {{ try {{ return {D}.id == {vid} && {D}.lines.length && {D}.canEdit }} catch (e) {{ return false }} }}",
                           timeout=20000)
    page.wait_for_timeout(500)
    page.locator("textarea[x-model='l.summary']").nth(2).focus()        # 第 3 行摘要 ⇒ 面板出現
    page.locator("[data-testid=summary-panel]").wait_for(state="visible", timeout=5000)
    return page


@pytest.mark.e2e
def test_wide_screen_puts_the_source_panel_beside_the_lines(live_server, client, make_user):
    u = make_user(username="vcs_wide", role="superadmin")
    vid = _seed(client, u)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = _open(browser, live_server, u, vid, 1440, 900)
            b = page.evaluate(BOX)
            assert b["lines"]["r"] <= b["panel"]["l"], ("1440 寬應左右並排", b)
            assert b["panel"]["t"] < b["lines"]["b"], ("面板要與分錄同一列，不是在下面", b)
            assert b["lines"]["t"] < b["vh"] and b["panel"]["t"] < b["vh"], ("兩區都要在第一屏內", b)
            assert b["sw"] <= b["vw"], ("不可橫向溢出", b)
            # 帶入後焦點仍在該行摘要
            page.locator(f"[data-testid=summary-panel-case]:has-text('{QNO}')").click()
            page.wait_for_function(f"() => {D}.lines[2].summary.includes('{QNO}')", timeout=5000)
            page.wait_for_timeout(200)
            focused = page.evaluate("() => [...document.querySelectorAll(\"textarea[x-model='l.summary']\")].indexOf(document.activeElement)")
            assert focused == 2, ("帶入後焦點應回到第 3 行摘要", focused)
        finally:
            browser.close()


@pytest.mark.e2e
def test_the_panel_stays_in_view_while_scrolling_a_long_voucher(live_server, client, make_user):
    """分錄很多行時往下捲：右欄 sticky，停在導覽列下方、仍在畫面內（不必捲回上面才看得到來源）。"""
    u = make_user(username="vcs_long", role="superadmin")
    vid = _seed(client, u, n=30)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = _open(browser, live_server, u, vid, 1440, 900)
            b = page.evaluate(BOX)
            assert b["lines"]["r"] <= b["panel"]["l"], ("1440 寬應左右並排", b)
            page.evaluate("() => window.scrollBy(0, 600)")
            page.wait_for_timeout(300)
            top = page.evaluate("() => document.querySelector('[data-testid=summary-panel]').getBoundingClientRect().top")
            header = page.evaluate("() => document.querySelector('.mnav').getBoundingClientRect().bottom")
            assert header <= top < b["vh"], ("捲動後面板要停在導覽列下方", top, header)
        finally:
            browser.close()


@pytest.mark.e2e
@pytest.mark.parametrize("width,height,zoom", [(1024, 768, None), (1440, 900, "1.3")], ids=["1024", "font-xl"])
def test_narrow_or_large_font_falls_back_to_stacked(live_server, client, make_user, width, height, zoom):
    u = make_user(username="vcs_" + ("xl" if zoom else str(width)), role="superadmin")
    vid = _seed(client, u)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = _open(browser, live_server, u, vid, width, height, zoom)
            b = page.evaluate(BOX)
            assert b["panel"]["t"] >= b["lines"]["b"], ("應退回上下排", b)
            assert b["sw"] <= b["vw"], ("不可橫向溢出", b)
        finally:
            browser.close()
