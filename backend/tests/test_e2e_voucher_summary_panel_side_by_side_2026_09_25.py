"""傳票：點來源帶入後，焦點回到那一行的摘要格（keepSummaryFocus）。

📌 更正留著（2026-09-25）：這個檔原本守 4963170 的「分錄與摘要來源面板左右並排」（內容欄夠寬 ⇒ 右側 sticky 面板；
   不夠寬／字級「特」⇒ 上下排）。使用者以示意圖改成版型 A：帶入來源移到**分錄下方**（左案件、右已上傳檔案），
   右側面板與它的 container query 已移除 ⇒ 並排、sticky、退回上下排這三題作廢，版面改由
   `test_e2e_voucher_source_block_below_2026_09_25` 守。
   仍適用的只有「帶入後焦點回到那一行摘要」：使用者點完來源可以直接接著打字。
觀測點：document.activeElement。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402


QNO = "MQ-VCSPLIT-01"
D = "Alpine.$data(document.querySelector('[x-data]'))"


def _rendered(page):
    """PERF #6：等 Alpine 把這次狀態變化畫完（nextTick）＋瀏覽器實際畫出兩個影格。"""
    page.evaluate("() => new Promise(r => (window.Alpine ? Alpine.nextTick : (f => f()))(() => requestAnimationFrame(() => requestAnimationFrame(r))))")


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
    inject_login(page, base, u[0], u[1])
    page.goto(f"{base}/pages/voucher.html?id={vid}")
    page.wait_for_function(f"() => {{ try {{ return {D}.id == {vid} && {D}.lines.length && {D}.canEdit && {D}.sourcesLoaded }} catch (e) {{ return false }} }}",
                           timeout=20000)
    _rendered(page)   # PERF #6：原本固定等 500ms
    page.locator("textarea[x-model='l.summary']").nth(2).focus()        # 第 3 行摘要
    page.locator("[data-testid=src-block]").wait_for(state="visible", timeout=5000)
    return page


@pytest.mark.e2e
def test_picking_a_case_keeps_the_focus_on_that_lines_summary(live_server, make_user, e2e_browser, client):
    u = make_user(username="split_focus", role="superadmin")
    vid = _seed(client, u)
    page = _open(e2e_browser, live_server, u, vid, 1440, 900)
    page.click(f'[data-testid="src-case"]:has-text("{QNO}")')
    page.wait_for_function(f"() => {D}.lines[2].summary.includes('並排客戶')", timeout=5000)
    _rendered(page)
    idx = page.evaluate("() => [...document.querySelectorAll(\"textarea[x-model='l.summary']\")].indexOf(document.activeElement)")
    assert idx == 2, "點案件帶入後，焦點應該回到第 3 行摘要，實際 %s" % idx
