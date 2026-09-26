"""點進一筆有新動態的案件後，上方「N 筆案件有新動態」要跟著減一（D8-1，2026-09-24 開發機實走發現）。

未讀件數讀的是伺服器件數 caseCounts.unread（CM7）；_markCaseRead() 只清了該筆的紅點，沒動件數 ⇒
紅點消失、上方數字不變（3→3），要等下一次重抓件數才對。觀測點：畫面上的未讀列文字與 unreadCount()。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
import time
from datetime import datetime

import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


NOS = ("MQ-MARKONE-001", "MQ-MARKONE-002")
DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"


def _seed():
    import db
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        for no in NOS:
            conn.execute(
                "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
                " created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (no, "已送出", "客戶", "專案" + no[-1], 1000, 952, json.dumps({"dealTag": "已成案"}), now, now,
                 "已成案", "2026-08-01"))
        conn.commit()
    finally:
        conn.close()


@pytest.mark.e2e
def test_opening_one_unread_case_decrements_the_count(live_server, client, make_user, e2e_browser):
    u = make_user(username="mor_e1", role="admin")
    _seed()
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u[0], "password": u[1]}).json()["token"]}
    client.post("/api/reads/unread", headers=h, json={"kind": "case", "keys": []})
    time.sleep(1.1)
    import db
    conn = db.get_db()
    try:
        for no in NOS:
            conn.execute("INSERT INTO case_updates (quote_no, author, content, created_at) VALUES (?,?,?,?)",
                         (no, "別人", "新動態", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
    finally:
        conn.close()
    browser = e2e_browser
    page = browser.new_context().new_page()
    inject_login(page, live_server, u[0], u[1])
    page.goto(f"{live_server}/pages/case-management.html")
    bar = page.locator(".cm-unread-bar")
    bar.wait_for(state="visible", timeout=15000)
    page.wait_for_function(f"() => {DATA_JS}.unreadCount() === 2", timeout=10000)
    time.sleep(1.1)                          # 已讀時間要嚴格晚於動態時間（到秒）
    page.click(f".cm-card[data-quote-no='{NOS[0]}']")
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NOS[0]}'", timeout=10000)
    page.wait_for_timeout(800)
    assert not page.evaluate(f"() => {DATA_JS}.isUnread({DATA_JS}.selected)"), "點進去的那筆紅點沒清掉（前提不成立）"
    assert page.evaluate(f"() => {DATA_JS}.unreadCount()") == 1, "點進一筆後未讀件數沒有減少"
    assert "1 筆案件有新動態" in bar.inner_text(), bar.inner_text()
