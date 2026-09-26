"""瀏覽器層級：兩個人同時開同一張報價單時，畫面上真的跳警示（2026-09-14）。

後端的 presence API 有單元測試（`test_online_activity_2026_09_14.py`），但那證明不了
**使用者看得到**——警示條沒被插進 DOM、被別的元素蓋住、或腳本根本沒載入，API 測試
一樣全綠。這支開兩個瀏覽器 context（等於兩個人）同時進同一張單，直接看警示條。

需要 `playwright`（見 `test_e2e_playwright_2026_09_07.py` 檔頭說明）。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")

import uvicorn
from tests._e2e_login import inject_login  # noqa: E402
from tests._ports import free_safe_port
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')




def _login(page, base_url, username, password):
    inject_login(page, base_url, username, password)


def _seed_quote(quote_no="MQ-E2E-PRES"):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, sales_person, assigned_user_ids) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "草稿", "測客", "測專", 1000, 952,
             json.dumps({"quoteNo": quote_no, "customerName": "測客", "items": []},
                        ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "", "", "[]"),
        )
        conn.commit()
    finally:
        conn.close()
    return quote_no


@pytest.mark.e2e
def test_second_editor_sees_warning_bar(live_server, make_user, e2e_browser):
    """A 先開著，B 再開同一張 → B 的畫面上出現「A 目前也在編輯這一份」。"""
    a_u, a_p = make_user(username="e2e_pres_a", role="superadmin")
    b_u, b_p = make_user(username="e2e_pres_b", role="superadmin")
    quote_no = _seed_quote()

    browser = e2e_browser
    ctx_a = browser.new_context()
    ctx_b = browser.new_context()
    page_a = ctx_a.new_page()
    _login(page_a, live_server, a_u, a_p)
    page_a.goto(f"{live_server}/pages/quotation-form.html?id={quote_no}")
    page_a.wait_for_timeout(1200)          # 讓 A 的第一次心跳送出去

    page_b = ctx_b.new_page()
    _login(page_b, live_server, b_u, b_p)
    page_b.goto(f"{live_server}/pages/quotation-form.html?id={quote_no}")
    page_b.wait_for_selector("#motrix-presence-bar", state="visible", timeout=10000)
    text = page_b.inner_text("#motrix-presence-bar")
    assert "e2e_pres_a" in text or "也在編輯" in text, text


@pytest.mark.e2e
def test_single_editor_sees_no_warning(live_server, make_user, e2e_browser):
    """反向控制：只有一個人時不該跳警示——不然這條會變成永遠都在的裝飾。"""
    u, p = make_user(username="e2e_pres_solo", role="superadmin")
    quote_no = _seed_quote("MQ-E2E-SOLO")

    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/quotation-form.html?id={quote_no}")
    page.wait_for_timeout(1500)
    bar = page.locator("#motrix-presence-bar")
    assert bar.count() == 0 or not bar.is_visible(), page.inner_text("#motrix-presence-bar")
