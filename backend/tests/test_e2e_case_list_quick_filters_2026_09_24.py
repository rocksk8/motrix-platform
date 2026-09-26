"""案件頁清單常用篩選（2026-09-24 使用者表單）：頁面端。

「全部」頁籤改名「進行中」；四個常用篩選（我負責的／逾期階段／應收逾期／缺單據）送伺服器並顯示件數；
卡片標出缺哪一種單據；「只看有新動態」對全部案件（不只已載入的第一頁）。
觀測點：清單卡片、按鈕文字、未讀列文字。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
import threading
import time
from datetime import datetime

import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')

DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"


def _case(no, *, items=(), customer="客戶"):
    import db
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (no, "已送出", customer, "專案", 1000, 952,
             json.dumps({"dealTag": "已成案", "caseRecord": {"payment": {"items": list(items)}}},
                        ensure_ascii=False), now, now, "已成案", "2026-08-01"))
        conn.commit()
    finally:
        conn.close()




def _open(browser, base, user):
    page = browser.new_context().new_page()
    page.on("dialog", lambda d: d.accept())
    inject_login(page, base, user[0], user[1])
    page.goto(f"{base}/pages/case-management.html")
    page.wait_for_function(f"() => {DATA_JS} && {DATA_JS}.session && {DATA_JS}.session.token"
                           f" && !{DATA_JS}.loading && {DATA_JS}.caseCounts", timeout=20000)
    return page


def _card_nos(page):
    return page.evaluate("() => [...document.querySelectorAll('.cm-card[data-quote-no]')].map(e => e.dataset.quoteNo)")


@pytest.mark.e2e
def test_tab_renamed_and_quick_filter_with_count_and_reason(live_server, make_user, e2e_browser):
    u = make_user(username="qfe_1", role="admin")
    _case("MQ-QFE-LATE", items=[{"id": 1, "received": False, "expectedReceiptDate": "2020-01-01"}])
    _case("MQ-QFE-NOINV", items=[{"id": 1, "received": True, "invoiceNo": ""}])
    _case("MQ-QFE-OK")
    browser = e2e_browser
    page = _open(browser, live_server, u)
    tab = page.locator(".cm-list__tab").first
    assert tab.inner_text().strip().startswith("進行中"), tab.inner_text()
    recv = page.locator("[data-quick=recv_overdue]")
    assert recv.inner_text().split() == ["應收逾期", "1"], recv.inner_text()
    recv.click()
    page.wait_for_function("() => { const c = [...document.querySelectorAll('.cm-card[data-quote-no]')];"
                           " return c.length === 1 && c[0].dataset.quoteNo === 'MQ-QFE-LATE' }", timeout=10000)
    recv.click()
    page.locator("[data-quick=missing_docs]").click()
    page.wait_for_function("() => { const c = [...document.querySelectorAll('.cm-card[data-quote-no]')];"
                           " return c.length === 1 && c[0].dataset.quoteNo === 'MQ-QFE-NOINV' }", timeout=10000)
    card = page.locator(".cm-card[data-quote-no='MQ-QFE-NOINV']")
    assert card.locator("[data-testid=case-missing-doc]").inner_text() == "缺發票"


@pytest.mark.e2e
def test_unread_only_reaches_cases_outside_the_loaded_page(live_server, client, make_user, e2e_browser):
    u = make_user(username="qfe_2", role="admin")
    for i in range(130):
        _case(f"MQ-QFU-{i:04d}")
    # 未讀基準先建立，再由別人在最舊的那一件留動態（它不在第一頁）
    r = client.post("/api/auth/login", json={"username": u[0], "password": u[1]})
    h = {"Authorization": "Bearer " + r.json()["token"]}
    client.post("/api/reads/unread", headers=h, json={"kind": "case", "keys": []})
    time.sleep(1.1)
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO case_updates (quote_no, author, content, created_at) VALUES (?,?,?,?)",
                     ("MQ-QFU-0000", "別人", "新動態", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
    finally:
        conn.close()
    browser = e2e_browser
    page = _open(browser, live_server, u)
    assert "MQ-QFU-0000" not in _card_nos(page), "前提：最舊的一件不在第一頁"
    bar = page.locator(".cm-unread-bar")
    bar.wait_for(state="visible", timeout=10000)
    assert "1 筆案件有新動態" in bar.inner_text(), bar.inner_text()
    bar.click()
    page.wait_for_function("() => { const c = [...document.querySelectorAll('.cm-card[data-quote-no]')];"
                           " return c.length === 1 && c[0].dataset.quoteNo === 'MQ-QFU-0000' }", timeout=10000)
