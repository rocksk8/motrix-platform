"""瀏覽器端對端：營運報表 UX 密度（C5，2026-11-11）。

預設：只顯示 3 張 KPI（本期新成案／本期收款／未收款），其餘收在「更多指標」；13 個頁籤分成 業績／現金／風險 三組、
一個都沒少；沒有資料時有一句說明。展開狀態記在 localStorage（try/catch——取不到時頁面照常、預設收合）。
只動呈現，不動資料、權限與頁籤內容。
"""
import datetime
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

PRIMARY = ["本期新成案", "本期收款", "未收款"]
FOLDED_SAMPLE = ["精算覆蓋率", "在製訂單", "合約總應收", "手續費合計"]
TABS = {
    "perf": ["目標達成率", "圖表分析", "業務員績效", "案件清單", "利潤分析", "客戶歷史"],
    "cash": ["已收款", "未收款", "月支出", "資金水位"],
    "risk": ["帳齡分析", "保固預警", "與總帳差異"],
}


def _open(live_server, make_user, e2e_browser, name, init_script=None, viewport=None):
    username, password = make_user(username=name, role="superadmin")
    page = e2e_browser.new_page(viewport=viewport or {"width": 1440, "height": 900})
    inject_login(page, live_server, username, password)
    if init_script:
        page.context.add_init_script(init_script)
    page.goto(f"{live_server}/pages/reports.html")
    page.wait_for_selector("[data-testid=kpi-more-toggle]", timeout=20000)
    return page


def _visible_kpi_labels(page):
    return page.evaluate("""() => [...document.querySelectorAll('.kpi-card__lbl')]
        .filter(e => e.offsetParent !== null).map(e => e.innerText.trim())""")


@pytest.mark.e2e
def test_default_shows_three_kpis_and_empty_hint(live_server, make_user, e2e_browser):
    page = _open(live_server, make_user, e2e_browser, "e2e_rd1")
    assert _visible_kpi_labels(page) == PRIMARY
    assert not page.locator("[data-testid=kpi-more]").is_visible()
    assert "更多指標" in page.locator("[data-testid=kpi-more-toggle]").inner_text()
    hint = page.locator("[data-testid=reports-empty-hint]")
    assert hint.is_visible() and "尚無資料，建立第一張報價單後這裡會出現統計" in hint.inner_text()
    # 展開後，原本的其餘指標都在（含「收支」那組）
    page.click("[data-testid=kpi-more-toggle]")
    page.wait_for_selector("[data-testid=kpi-more]", state="visible")
    shown = _visible_kpi_labels(page)
    for lbl in PRIMARY + FOLDED_SAMPLE + ["當月收入", "當月支出"]:
        assert any(x.startswith(lbl) for x in shown), "%s 展開後應看得到（目前：%s）" % (lbl, shown)
    assert len(shown) == 15, "KPI 共 15 張（3 常駐＋12 收在更多指標），實際 %s" % shown
    # 再按一次收回
    page.click("[data-testid=kpi-more-toggle]")
    page.wait_for_selector("[data-testid=kpi-more]", state="hidden")
    assert _visible_kpi_labels(page) == PRIMARY


@pytest.mark.e2e
def test_kpi_fold_state_is_remembered_per_viewer(live_server, make_user, e2e_browser):
    page = _open(live_server, make_user, e2e_browser, "e2e_rd2")
    page.click("[data-testid=kpi-more-toggle]")
    page.wait_for_selector("[data-testid=kpi-more]", state="visible")
    page.reload()
    page.wait_for_selector("[data-testid=kpi-more-toggle]", timeout=20000)
    assert page.locator("[data-testid=kpi-more]").is_visible(), "重新整理後應記住展開"
    assert page.evaluate("localStorage.getItem('motrix_reports_kpi_more')") == "1"


@pytest.mark.e2e
def test_page_works_when_local_storage_throws(live_server, make_user, e2e_browser):
    """瀏覽器擋住 localStorage 讀寫（無痕視窗／封鎖）⇒ 頁面照常、預設收合、按鈕仍可展開收合。
    只讓報表那把鍵拋例外，session 照樣能讀（否則連登入都沒了）。"""
    blocker = """(() => {
      const g = Storage.prototype.getItem, s = Storage.prototype.setItem;
      Storage.prototype.getItem = function (k) { if (k === 'motrix_reports_kpi_more') throw new Error('blocked'); return g.call(this, k); };
      Storage.prototype.setItem = function (k, v) { if (k === 'motrix_reports_kpi_more') throw new Error('blocked'); return s.call(this, k, v); };
    })();"""
    page = _open(live_server, make_user, e2e_browser, "e2e_rd3", init_script=blocker)
    assert _visible_kpi_labels(page) == PRIMARY
    page.click("[data-testid=kpi-more-toggle]")
    page.wait_for_selector("[data-testid=kpi-more]", state="visible")
    page.click("[data-testid=kpi-more-toggle]")
    page.wait_for_selector("[data-testid=kpi-more]", state="hidden")


@pytest.mark.e2e
def test_tabs_are_grouped_and_none_removed(live_server, make_user, e2e_browser):
    page = _open(live_server, make_user, e2e_browser, "e2e_rd4")
    groups = page.locator("[data-testid=tab-bar] .tab-group")
    assert groups.count() == 3
    assert [g.locator(".tab-group__lbl").inner_text().strip() for g in groups.all()] == ["業績", "現金", "風險"]
    total = 0
    for gid, names in TABS.items():
        texts = page.locator("[data-tab-group=%s] button.tab" % gid).all_inner_texts()
        total += len(texts)
        for n in names:
            assert any(n in t for t in texts), "%s 組缺少頁籤 %s（%s）" % (gid, n, texts)
    assert total == 13
    # 各組的頁籤仍然會切換
    page.click("[data-tab-group=risk] button.tab:has-text('與總帳差異')")
    page.wait_for_selector("[data-testid=gldiff-panel]", state="visible", timeout=10000)
    page.click("[data-tab-group=cash] button.tab:has-text('未收款')")
    page.wait_for_function(
        "() => Alpine.$data(document.querySelector('[x-data]')).activeTab === 'out'", timeout=10000)


@pytest.mark.e2e
def test_empty_hint_disappears_with_data(live_server, make_user, e2e_browser):
    import db
    today = datetime.date.today()
    data_json = json.dumps({
        "dealTag": "已成案",
        "caseRecord": {"payment": {"items": [{
            "id": 1, "type": "訂金", "pct": 100, "amount": 105000,
            "received": True, "receivedAt": today.isoformat() + "T00:00:00"}]}},
    }, ensure_ascii=False)
    username, password = make_user(username="e2e_rd5", role="superadmin")
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("MQ-RD-001", "已送出", "密度測客", "密度測專", 105000, 100000, data_json,
             today.isoformat() + "T00:00:00", today.isoformat() + "T00:00:00", "已成案", today.isoformat()))
        conn.commit()
    finally:
        conn.close()
    page = e2e_browser.new_page(viewport={"width": 1440, "height": 900})
    inject_login(page, live_server, username, password)
    page.goto(f"{live_server}/pages/reports.html")
    page.wait_for_selector("[data-testid=kpi-more-toggle]", timeout=20000)
    page.wait_for_function(
        "() => (Alpine.$data(document.querySelector('[x-data]')).summary.totalCases || 0) > 0", timeout=20000)
    assert not page.locator("[data-testid=reports-empty-hint]").is_visible()
    assert _visible_kpi_labels(page) == PRIMARY


@pytest.mark.e2e
def test_narrow_screen_no_horizontal_scroll(live_server, make_user, e2e_browser):
    page = _open(live_server, make_user, e2e_browser, "e2e_rd6", viewport={"width": 390, "height": 844})
    over = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert over <= 1, "手機寬度出現橫向捲動 %s px" % over
