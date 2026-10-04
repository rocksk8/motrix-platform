"""第 38 班前端：樂觀鎖衝突、完結／重新開啟失敗不誤導、載入失敗中文訊息、存檔有報價無的品項、無障礙、sticky／列印版面。
終點以頁面 DOM 與資料庫為準；失敗用 route 攔截模擬（403／422／500／斷線）。"""
import json
import os

import pytest

pytest.importorskip("playwright.sync_api")

from tests._requires import requires_module  # noqa: E402
from tests.test_e2e_case_concurrent_edit_2026_09_24 import _login  # noqa: F401

from modules.case.tests.test_e2e_settlement_actuals_2026_10_03 import NO, _seed, _settlement  # noqa: E402

pytestmark = requires_module("case", "本檔的題讀寫 M01（案件）的資料與頁面")

S = "Alpine.$data(document.body)"
SHOTS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "logs", "e2e-shots", "wip-t38-fe-05")


def _open(browser, base, user, width=1400):
    page = browser.new_context(viewport={"width": width, "height": 1000}).new_page()
    _login(page, base, *user)
    page.goto(f"{base}/pages/settlement.html?no={NO}")
    page.locator('[data-testid="stl-strip"]').wait_for(state="visible", timeout=20000)
    page.wait_for_function(f"() => {S}._actualsOk && {S}.summary.totalActualCost > 0", timeout=20000)
    return page


def _finalize_click(page):
    page.locator('[data-testid="stl-finalize"]').click()
    page.get_by_role("button", name="確認完結").click()


@pytest.mark.e2e
def test_optimistic_lock_conflict_never_overwrites(live_server, make_user, e2e_browser):
    sa = make_user(username="sa_sa", role="superadmin")
    _seed()
    a = _open(e2e_browser, live_server, sa)
    b = _open(e2e_browser, live_server, sa)
    b.evaluate(f"() => {{ {S}.settlement.memo = 'B-memo' }}")
    b.locator('[data-testid="stl-save-draft"]').click()
    b.wait_for_function(f"() => !{S}.saving", timeout=15000)
    assert _settlement()["memo"] == "B-memo"
    # A 還抱著舊版本：存檔 ⇒ 409 ⇒ 衝突橫幅＋錯誤訊息（role=alert），資料庫仍是 B 的；A 的存檔／完結鈕停用
    a.evaluate(f"() => {{ {S}.settlement.memo = 'A-memo' }}")
    a.locator('[data-testid="stl-save-draft"]').click()
    a.locator('[data-testid="stl-conflict"]').wait_for(state="visible", timeout=10000)
    err = a.locator('[data-testid="stl-toast-error"]').first
    assert err.get_attribute("role") == "alert" and err.get_attribute("aria-live") == "assertive"
    assert "重新載入" in a.locator('[data-testid="stl-conflict"]').inner_text()
    assert _settlement()["memo"] == "B-memo"                                        # 沒有被悄悄覆蓋
    assert a.locator('[data-testid="stl-save-draft"]').is_disabled() and a.locator('[data-testid="stl-finalize"]').is_disabled()
    with a.expect_navigation(wait_until="domcontentloaded"):
        a.locator('[data-testid="stl-conflict-reload"]').click()
    a.wait_for_function(f"() => {S}._actualsOk && {S}.settlement.memo === 'B-memo'", timeout=20000)
    assert not a.locator('[data-testid="stl-conflict"]').is_visible()
    assert a.locator('[data-testid="stl-save-draft"]').is_enabled()


@pytest.mark.e2e
def test_finalize_and_reopen_failures_do_not_mislead(live_server, make_user, e2e_browser):
    sa = make_user(username="sa_sa", role="superadmin")
    _seed()
    page = _open(e2e_browser, live_server, sa)
    calls = {"get": 0, "put": 0}
    mode = {"v": "422"}

    def handler(route):
        req = route.request
        if req.method == "PUT":
            calls["put"] += 1
            if mode["v"] == "abort":
                return route.abort()
            if mode["v"] == "pass":
                return route.continue_()
            code = {"422": 422, "403": 403, "500": 500}[mode["v"]]
            return route.fulfill(status=code, content_type="application/json", body=json.dumps({"detail": "測試：後端拒絕"}))
        calls["get"] += 1
        return route.continue_()

    page.route("**/api/quotations/*/settlement", handler)
    # 422：訊息含後端檢核文字；本頁維持草稿；失敗後重新取得狀態（GET 次數增加）；錯誤訊息停留 ≥ 5 秒（10 秒）
    g0 = calls["get"]
    _finalize_click(page)
    err = page.locator('[data-testid="stl-toast-error"]').first
    err.wait_for(state="visible", timeout=10000)
    assert "完結失敗" in err.inner_text() and "測試：後端拒絕" in err.inner_text()
    assert page.evaluate(f"() => {S}.settlement.status") == "draft" and page.evaluate(f"() => {S}.settlement.finalizedAt") in ("", None)
    page.wait_for_function(f"() => !{S}.saving", timeout=5000)
    assert calls["get"] > g0, calls                                                   # 重新取得伺服器狀態
    page.wait_for_timeout(5000)
    assert err.is_visible()                                                           # 10 秒訊息，5 秒後還在
    assert not page.locator('[data-testid="stl-conflict"]').is_visible()             # 狀態與伺服器一致，不誤報衝突
    # 403：不洩漏後端字串，給中文權限說明；仍是草稿
    mode["v"] = "403"
    _finalize_click(page)
    page.locator('[data-testid="stl-toast-error"]', has_text="沒有權限").first.wait_for(state="visible", timeout=10000)
    assert page.evaluate(f"() => {S}.settlement.status") == "draft"
    # 500：伺服器暫時無法處理，資料沒有被改動；不顯示後端原文
    mode["v"] = "500"
    _finalize_click(page)
    t500 = page.locator('[data-testid="stl-toast-error"]', has_text="伺服器暫時無法處理").first
    t500.wait_for(state="visible", timeout=10000)
    assert "測試：後端拒絕" not in t500.inner_text()
    # 純網路錯誤：中文說明、不再 GET（無從取得）
    mode["v"] = "abort"
    g1 = calls["get"]
    _finalize_click(page)
    page.locator('[data-testid="stl-toast-error"]', has_text="網路連線失敗").first.wait_for(state="visible", timeout=10000)
    page.wait_for_function(f"() => !{S}.saving", timeout=5000)
    assert calls["get"] == g1 and page.evaluate(f"() => {S}.settlement.status") == "draft"
    # 真的完結（放行）⇒ 重新開啟被 403：畫面維持「已完結」，不是假裝草稿
    mode["v"] = "pass"
    _finalize_click(page)
    page.wait_for_function(f"() => {S}.settlement.status === 'finalized' && !{S}.saving", timeout=15000)
    assert _settlement()["status"] == "finalized"
    mode["v"] = "403"
    page.locator('[data-testid="stl-reopen"]').click()
    page.locator('[data-testid="stl-reopen-modal"] textarea, [data-testid="stl-reopen-modal"] input').first.fill("測試理由")
    page.locator('[data-testid="stl-reopen-modal"]').get_by_role("button", name="重新開啟").click()
    page.wait_for_function(f"() => !{S}.saving && {S}.reopenErr", timeout=10000)
    assert "重新開啟失敗" in page.evaluate(f"() => {S}.reopenErr") and "沒有權限" in page.evaluate(f"() => {S}.reopenErr")
    assert page.evaluate(f"() => {S}.settlement.status") == "finalized"
    assert _settlement()["status"] == "finalized"


@pytest.mark.e2e
def test_load_failures_show_chinese_messages(live_server, make_user, e2e_browser):
    sa = make_user(username="sa_sa", role="superadmin")
    _seed()
    for mode, expect in (("404", "找不到這張報價單"), ("500", "伺服器暫時無法處理"), ("abort", "網路連線失敗")):
        page = e2e_browser.new_context(viewport={"width": 1200, "height": 900}).new_page()
        _login(page, live_server, *sa)

        def make(m):
            def handler(route, *_):
                if route.request.method != "GET":
                    return route.continue_()
                if m == "abort":
                    return route.abort()
                return route.fulfill(status=int(m), content_type="application/json", body=json.dumps({"detail": "內部細節不該顯示"}))
            return handler

        handler = make(mode)
        page.route("**/api/quotations/*/settlement", handler)
        page.goto(f"{live_server}/pages/settlement.html?no={NO}", wait_until="domcontentloaded")
        banner = page.locator('[data-testid="stl-load-error"]')
        banner.wait_for(state="visible", timeout=15000)
        assert expect in banner.inner_text() and "內部細節" not in banner.inner_text(), (mode, banner.inner_text())
        assert banner.get_attribute("role") == "alert" and "重新載入" in banner.inner_text()


@pytest.mark.e2e
def test_orphan_saved_items_are_listed_read_only(live_server, make_user, e2e_browser):
    import db
    sa = make_user(username="sa_sa", role="superadmin")
    _seed()
    page = _open(e2e_browser, live_server, sa)
    page.locator('[data-testid="stl-save-draft"]').click()
    page.wait_for_function(f"() => !{S}.saving", timeout=15000)
    assert not page.locator('[data-testid="stl-orphans"]').is_visible()
    c = db.get_db()
    try:
        d = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        d["settlement"]["items"].append({"id": "gone", "origDescription": "已刪除的品項", "actualTotalCost": 321, "adoptSystem": True})
        c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), NO))
        c.commit()
    finally:
        c.close()
    page.reload()
    page.locator('[data-testid="stl-orphans"]').wait_for(state="visible", timeout=20000)
    row = page.locator('[data-testid="stl-orphan-gone"]')
    assert "321" in row.inner_text() and page.locator('[data-testid="stl-orphans"] input, [data-testid="stl-orphans"] select, [data-testid="stl-orphans"] button').count() == 0
    s = page.evaluate(f"() => ({{...{S}.summary}})")
    assert s["itemActualTotal"] == 10500 + 800 and s["totalActualCost"] == 10500 + 800 + 950          # 不計入任何金額


@pytest.mark.e2e
def test_accessibility_labels_chart_descriptions_and_focusable_jumps(live_server, make_user, e2e_browser):
    sa = make_user(username="sa_sa", role="superadmin")
    _seed()
    page = _open(e2e_browser, live_server, sa)
    # 每一列的實際數量／單位成本／稅別／備註／來源標籤都有 aria-label，且含品項名稱與欄位
    rows = page.locator('tr[id^="stl-row-"]')
    assert rows.count() == 2
    for i in range(rows.count()):
        name = rows.nth(i).locator("td").nth(1).inner_text().strip().split("\n")[0]
        fields = rows.nth(i).locator("input, select")
        labels = fields.evaluate_all("els => els.map(e => e.getAttribute('aria-label') || '')")
        assert all(labels), (name, labels)
        joined = "｜".join(labels)
        for col in ("實際數量", "實際單位成本", "稅別", "備註"):
            assert col in joined and name in joined, (name, col, labels)
    # 圖表：群組有 aria-labelledby／aria-describedby，說明文字存在且含數字（表格同源）
    groups = page.locator('[data-testid="stl-charts"] [role="group"]')
    assert groups.count() == 3
    for i in range(3):
        did = groups.nth(i).get_attribute("aria-describedby")
        assert groups.nth(i).get_attribute("aria-labelledby")
        txt = page.locator("#" + did).text_content()
        assert txt and any(ch.isdigit() for ch in txt), (did, txt)
    assert "10,500" in page.locator("#stl-chd-pr").text_content()
    # 需處理的「前往」鈕：有 aria-label、可聚焦、Enter 能跳
    btns = page.locator('[data-testid^="stl-exc-"] button')
    assert btns.count() >= 1
    first = btns.first
    assert (first.get_attribute("aria-label") or "").startswith("前往：")
    first.focus()
    assert page.evaluate("() => document.activeElement && document.activeElement.tagName") == "BUTTON"
    page.keyboard.press("Enter")                                                        # 不丟例外、頁面仍可操作
    assert page.locator('[data-testid="stl-strip"]').is_visible()


@pytest.mark.e2e
def test_kpi_strip_sticky_threshold_and_print_layout(live_server, make_user, e2e_browser):
    sa = make_user(username="sa_sa", role="superadmin")
    _seed()
    page = _open(e2e_browser, live_server, sa)
    tops = "() => new Set([...document.querySelectorAll('[data-testid=\"stl-strip\"] .stl-k')].map(e => Math.round(e.getBoundingClientRect().top))).size"
    pos = "() => getComputedStyle(document.querySelector('[data-testid=\"stl-strip\"]')).position"
    for w, sticky in ((1250, True), (1440, True), (1100, False), (900, False)):
        page.set_viewport_size({"width": w, "height": 900})
        page.wait_for_timeout(300)
        assert (page.evaluate(pos) == "sticky") is sticky, (w, page.evaluate(pos))
        if sticky:
            assert page.evaluate(tops) == 1, (w, page.evaluate(tops))                 # sticky 時絕不折成兩列
    # 列印：固定 5 欄（單列）、不 sticky、工具列隱藏；用 A4 寬度
    page.set_viewport_size({"width": 794, "height": 1123})
    page.emulate_media(media="print")
    page.wait_for_timeout(300)
    assert page.evaluate(pos) == "static"
    assert page.evaluate(tops) == 1
    assert page.evaluate("() => getComputedStyle(document.querySelector('.stl-kpis')).gridTemplateColumns.split(' ').length") == 5
    assert page.locator(".stl-toolbar").evaluate("e => getComputedStyle(e).display") == "none"
    os.makedirs(SHOTS, exist_ok=True)
    page.screenshot(path=os.path.join(SHOTS, "print-a4.png"), full_page=False)
    page.emulate_media(media="screen")


@pytest.mark.e2e
def test_zero_sum_purchase_rows_replace_the_estimate_when_adopted(live_server, make_user, e2e_browser):
    """與後端 38 同規則：有採購列（即使相抵為 0）＋採用 ⇒ 取代估計（0），不是退回估計。"""
    sa = make_user(username="sa_sa", role="superadmin")
    _seed()
    page = _open(e2e_browser, live_server, sa)
    r = page.evaluate(f"""() => {{
        const d = {S}; const a = d.settlement.items[0];
        d.itemActuals['a'] = Object.assign({{}}, d.itemActuals['a'], {{ extra: {{ amount: 0, docs: [{{ expenseId: 1, amount: 0 }}] }} }});
        a.adoptSystem = true; d.calcItemCost(a); d.calcSummary();
        return {{ has: d.hasPurchase(a), actual: d.itemActual(a), est: d.estimateOf(a), total: d.summary.itemActualTotal }};
    }}""")
    assert r["has"] is True and r["actual"] == 0 and r["est"] == 10500, r
    assert r["total"] == 0 + 800, r                                                     # a 取代為 0；b 仍是 800
