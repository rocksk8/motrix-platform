"""瀏覽器層級：簽核佇列的「轉簽」按鈕（2026-09-14）。

端點的規則（限最高管理者、原因必填、只換當層待簽人）在
`test_approval_reassign_history_2026_09_14.py`。這支確認畫面這一半：按鈕給對人、
對話框填完之後**資料庫裡的簽核人真的換了**——按鈕能按但沒接上端點是這個專案最
常見的失敗型態。

需要 `playwright`（見 `test_e2e_playwright_2026_09_07.py` 檔頭說明）。
"""
import json
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")

import uvicorn
from tests._ports import free_safe_port




def _login(page, base_url, username, password):
    page.goto(f"{base_url}/pages/login.html")
    page.fill('input[x-model="username"]', username)
    page.fill('input[x-model="password"]', password)
    page.click('button:has-text("登入")')
    page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=10000)


def _seed_pending_quote(quote_no, approver):
    """一張卡在 `approver` 身上的待簽核報價單（比照單元測試的 seed）。"""
    import db
    data = {
        "quoteNo": quote_no,
        "approval": {
            "requestedBy": "sales_x",
            "requestedByDisplay": "業務X",
            "requestedAt": "2026-09-14T09:00:00",
            "currentTier": 0,
            "tiers": [{"approvers": [{"username": approver, "displayName": approver,
                                      "status": "pending"}]}],
        },
    }
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, sales_person, assigned_user_ids) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "待審核", "轉簽客戶", "轉簽專案", 50000, 47619,
             json.dumps(data, ensure_ascii=False), "2026-09-14T09:00:00",
             "2026-09-14T09:00:00", "", "業務X", "[]"),
        )
        conn.commit()
    finally:
        conn.close()


def _approvers_of(quote_no):
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?",
                           (quote_no,)).fetchone()
    finally:
        conn.close()
    appr = json.loads(row["data_json"] or "{}").get("approval", {})
    return (appr.get("tiers") or [{}])[0].get("approvers") or []


@pytest.mark.e2e
def test_superadmin_can_reassign_from_queue(live_server, make_user, e2e_browser):
    """最高管理者在佇列裡按轉簽 → 填原因 → 簽核人在 data_json 裡真的換人。"""
    su, sp = make_user(username="aqr_su", role="superadmin")
    make_user(username="aqr_old", role="admin")
    make_user(username="aqr_new", role="admin")
    quote_no = "MQ-AQR-001"
    _seed_pending_quote(quote_no, "aqr_old")

    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, su, sp)
    page.goto(f"{live_server}/pages/approval-queue.html")
    page.wait_for_selector(f'text={quote_no}', timeout=15000)
    page.click(f'text={quote_no}')
    page.wait_for_selector('#aq-reassign-btn', state="visible", timeout=10000)

    page.click('#aq-reassign-btn')
    page.wait_for_selector('#aq-reassign-to', state="visible", timeout=5000)
    # 名單是非同步抓回來的，等選項真的出現再選
    page.wait_for_function(
        """() => document.querySelector('#aq-reassign-to')
                  && document.querySelector('#aq-reassign-to').options.length > 1""",
        timeout=10000)

    # 原因必填：先不填按下去，畫面要擋住而不是靜靜失敗
    page.select_option('#aq-reassign-to', "aqr_new")
    page.click('#aq-reassign-confirm')
    page.wait_for_selector('#aq-reassign-error', state="visible", timeout=5000)
    assert _approvers_of(quote_no)[0]["username"] == "aqr_old", "沒填原因就轉出去了"

    page.fill('#aq-reassign-reason', "原簽核人出差兩週，由副手代簽")
    page.click('#aq-reassign-confirm')
    # 觀測點放在資料庫：畫面上的對話框關掉只代表按鈕有反應
    for _ in range(50):
        if _approvers_of(quote_no)[0]["username"] == "aqr_new":
            break
        page.wait_for_timeout(200)
    a = _approvers_of(quote_no)[0]
    assert a["username"] == "aqr_new", a
    assert a["reassignedFrom"] == "aqr_old", a
    assert "出差兩週" in a["reassignReason"], a

    # 畫面也要跟著更新：轉簽成功後佇列要重整（先前寫成 this.load()，
    # 這個元件其實叫 loadQueue()——資料換了、畫面沒換，人會以為沒生效），
    # 而且「註明原因」要看得到（使用者要求「註記這筆簽核」）。
    page.wait_for_function(
        """() => {
             const el = document.querySelector('.aq-steps-timeline') || document.body;
             const t = el.innerText || '';
             return t.includes('aqr_new') && t.includes('轉簽自');
           }""",
        timeout=10000)
    assert "出差兩週" in page.inner_text("body"), "轉簽原因沒有顯示在佇列上"


@pytest.mark.e2e
def test_admin_has_no_reassign_button(live_server, make_user, e2e_browser):
    """反向控制：一般管理員看不到轉簽（後端也會 403）。"""
    u, p = make_user(username="aqr_admin", role="admin", modules=["quotation"])
    quote_no = "MQ-AQR-002"
    _seed_pending_quote(quote_no, "aqr_admin")

    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/approval-queue.html")
    page.wait_for_selector(f'text={quote_no}', timeout=15000)
    page.click(f'text={quote_no}')
    page.wait_for_timeout(600)
    assert page.locator('#aq-reassign-btn:visible').count() == 0, "管理員也看得到轉簽"
