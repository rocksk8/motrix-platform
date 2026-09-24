"""快速切換案件：先點的那件回應較晚抵達時，不可把畫面切回那一件（2026-09-24）。

selectCase() 取案件後直接 this.selected = data，沒有確認「這還是最後點的那一件」
⇒ 連點 A、B，A 的回應較晚回來，畫面停在 A（使用者以為在看 B）。
案件健康總覽的晚到題偶發紅燈即此成因。觀測點：selected.quote_no。
"""
import json
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402

A = "MQ-SEL-001"
B = "MQ-SEL-002"
DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"


def _seed(no, customer):
    import db
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        cur = conn.execute("INSERT INTO case_stages (quote_no, label, sort_order, done, created_at, updated_at)"
                           " VALUES (?,?,?,?,?,?)", (no, "施工", 0, 0, now, now))
        cr = {"payment": {"items": []}, "stages": [{"id": cur.lastrowid, "label": "施工", "done": False}]}
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (no, "已送出", customer, "專案", 1000, 952,
             json.dumps({"dealTag": "已成案", "caseRecord": cr}, ensure_ascii=False),
             now, now, "已成案", "2026-08-01"))
        conn.commit()
    finally:
        conn.close()




@pytest.mark.e2e
def test_a_late_response_for_the_earlier_click_does_not_switch_back(live_server, make_user, e2e_browser):
    u = make_user(username="sel_e1", role="admin")
    _seed(A, "先點客戶")
    _seed(B, "後點客戶")
    browser = e2e_browser
    page = browser.new_context().new_page()
    page.on("dialog", lambda d: d.accept())
    inject_login(page, live_server, u[0], u[1])
    page.goto(f"{live_server}/pages/case-management.html")
    page.wait_for_function(f"() => {DATA_JS} && {DATA_JS}.session && {DATA_JS}.session.token",
                           timeout=20000)
    # 只延後「取 A 這一件」的回應（精確路徑，不含 /close-gates 等子路徑）
    page.route(f"**/api/quotations/{A}", lambda route: (time.sleep(1.5), route.continue_()))
    page.evaluate(f"() => {{ {DATA_JS}.selectCase('{A}') }}")
    page.evaluate(f"async () => {{ await {DATA_JS}.selectCase('{B}') }}")
    page.wait_for_timeout(2500)
    assert page.evaluate(f"() => {DATA_JS}.selected.quote_no") == B
