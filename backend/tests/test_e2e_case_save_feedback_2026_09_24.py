"""案件頁存檔回饋明顯化（2026-09-24 使用者表單）。

- 存檔失敗／同時編輯衝突 ⇒ 常駐橫幅（role=alert），不會幾秒後自己消失；衝突時橫幅上有
  「重新載入」「保留我的變更再試」；問題排除並存檔成功後橫幅消失
- 按「儲存」成功 ⇒ 明顯的成功提示（role=status）；自動存檔不跳提示（避免每 1.5 秒閃一次）
觀測點：畫面上的橫幅／提示。
"""
import json
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402

NO = "MQ-SAVEFB-001"
DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"
BANNER = "[data-testid=save-banner]"


def _seed():
    import db
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        cur = conn.execute("INSERT INTO case_stages (quote_no, label, sort_order, done, created_at, updated_at)"
                           " VALUES (?,?,?,?,?,?)", (NO, "施工", 0, 0, now, now))
        cr = {"payment": {"items": [{"id": 1, "type": "尾款", "pct": 100, "received": False, "receivedAt": "",
                                     "note": ""}]},
              "stages": [{"id": cur.lastrowid, "label": "施工", "done": False}]}
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (NO, "已送出", "客戶", "專案", 1000, 952,
             json.dumps({"dealTag": "已成案", "caseRecord": cr}, ensure_ascii=False),
             now, now, "已成案", "2026-08-01"))
        conn.commit()
    finally:
        conn.close()




def _open(browser, base, user):
    page = browser.new_context().new_page()
    page.on("dialog", lambda d: d.accept())
    inject_login(page, base, user[0], user[1])
    page.goto(f"{base}/pages/case-management.html?q={NO}")
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}'", timeout=20000)
    return page


@pytest.mark.e2e
def test_save_error_shows_a_persistent_banner_until_fixed(live_server, make_user, e2e_browser):
    u = make_user(username="sfb_e1", role="admin")
    _seed()
    browser = e2e_browser
    page = _open(browser, live_server, u)
    # 已收款卻沒填收款日期 ⇒ 存檔被擋
    page.evaluate(f"async () => {{ const c = {DATA_JS}; c.cr.caseRecord.payment.items[0].received = true;"
                  f" await c.saveCaseRecord() }}")
    banner = page.locator(BANNER)
    banner.wait_for(state="visible", timeout=5000)
    assert banner.get_attribute("role") == "alert"
    assert "收款日期" in banner.inner_text()
    page.wait_for_timeout(3000)
    assert banner.is_visible(), "錯誤橫幅不可以自己消失"
    page.evaluate(f"async () => {{ const c = {DATA_JS}; c.cr.caseRecord.payment.items[0].receivedAt = '2026-09-01';"
                  f" await c.saveCaseRecord() }}")
    banner.wait_for(state="hidden", timeout=5000)


@pytest.mark.e2e
def test_conflict_banner_offers_reload_and_keep(live_server, make_user, e2e_browser):
    u = make_user(username="sfb_e2", role="admin")
    _seed()
    browser = e2e_browser
    page = _open(browser, live_server, u)
    page.route(f"**/api/quotations/{NO}/case-record", lambda route: route.fulfill(
        status=409, content_type="application/json",
        body=json.dumps({"detail": {"code": "segment_conflict", "segments": ["payment"]}})))
    page.evaluate(f"async () => {{ const c = {DATA_JS}; c.cr.caseRecord.payment.items[0].note = 'x';"
                  f" await c.saveCaseRecord() }}")
    banner = page.locator(BANNER)
    banner.wait_for(state="visible", timeout=5000)
    assert "已被他人更新" in banner.inner_text()
    assert banner.locator("button:text-is('重新載入')").count() == 1
    assert banner.locator("button:text-is('保留我的變更再試')").count() == 1


@pytest.mark.e2e
def test_manual_save_shows_success_toast_but_autosave_does_not(live_server, make_user, e2e_browser):
    u = make_user(username="sfb_e3", role="admin")
    _seed()
    browser = e2e_browser
    page = _open(browser, live_server, u)
    toast = page.locator("[data-testid=save-toast]")
    page.evaluate(f"async () => {{ const c = {DATA_JS}; c.cr.caseRecord.payment.items[0].note = '自動';"
                  f" await c.saveCaseRecord() }}")
    page.wait_for_timeout(300)
    assert not toast.is_visible(), "自動存檔不跳提示"
    page.evaluate(f"() => {{ {DATA_JS}.cr.caseRecord.payment.items[0].note = '手動' }}")
    page.click(".cm-header .btn-save")
    toast.wait_for(state="visible", timeout=5000)
    assert toast.get_attribute("role") == "status"
    assert "已儲存" in toast.inner_text()
