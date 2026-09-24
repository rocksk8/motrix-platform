"""快速切換案件：前一件的後續載入晚到時，不可寫進目前這一件（2026-09-24）。

selectCase() 在 await（建立預設階段等）之後還會繼續重設狀態、指定成員名單、並對「前一件」
發出出貨單、完工單等子載入 ⇒ 連點 A、B，A 的後段晚到時，B 的畫面顯示 A 的出貨單、成員名單
變成 A 的，使用者按儲存成員就寫進 B。
觀測點：B 畫面上的資料，以及 B 在資料庫的成員名單（存檔後）。
"""
import json
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402

A = "MQ-STALE-A"
B = "MQ-STALE-B"
DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"


def _user_id(username):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()[0]
    finally:
        conn.close()


def _seed(no, *, stages, assigned, ship_note=None):
    import db
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        st = []
        for i, label in enumerate(stages):
            cur = conn.execute("INSERT INTO case_stages (quote_no, label, sort_order, done, created_at, updated_at)"
                               " VALUES (?,?,?,?,?,?)", (no, label, i, 0, now, now))
            st.append({"id": cur.lastrowid, "label": label, "done": False})
        cr = {"payment": {"items": []}, "stages": st}
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, quote_date, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (no, "已送出", "客戶" + no, "專案", 1000, 952,
             json.dumps({"dealTag": "已成案", "caseRecord": cr}, ensure_ascii=False),
             now, now, "已成案", "2026-08-01", json.dumps(assigned)))
        if ship_note:
            conn.execute(
                "INSERT INTO shipping_notes (note_no, quote_no, status, customer_name, items_json, data_json,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (ship_note, no, "草稿", "客戶" + no, "[]", "{}", now, now))
        conn.commit()
    finally:
        conn.close()


def _assigned(no):
    import db
    conn = db.get_db()
    try:
        return json.loads(conn.execute("SELECT assigned_user_ids FROM quotations WHERE quote_no=?",
                                       (no,)).fetchone()[0] or "[]")
    finally:
        conn.close()




@pytest.mark.e2e
def test_the_earlier_cases_late_subloads_do_not_land_on_the_current_case(live_server, make_user, e2e_browser):
    u = make_user(username="stale_e1", role="admin")
    make_user(username="stale_member", role="sales")
    member = _user_id("stale_member")
    _seed(A, stages=[], assigned=[member], ship_note="SN-STALE-A")   # 沒有階段 ⇒ 頁面會替 A 建預設階段
    _seed(B, stages=["B施工"], assigned=[])
    browser = e2e_browser
    page = browser.new_context().new_page()
    page.on("dialog", lambda d: d.accept())
    inject_login(page, live_server, u[0], u[1])
    page.goto(f"{live_server}/pages/case-management.html")
    page.wait_for_function(f"() => {DATA_JS} && {DATA_JS}.session && {DATA_JS}.session.token",
                           timeout=20000)
    delayed = []

    def _slow_first_stage_post(route):
        if route.request.method == "POST" and not delayed:
            delayed.append(1)
            time.sleep(2.0)
        route.continue_()

    page.route(f"**/api/quotations/{A}/stages", _slow_first_stage_post)
    page.evaluate(f"() => {{ {DATA_JS}.selectCase('{A}') }}")
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{A}'",
                           timeout=10000)
    page.evaluate(f"async () => {{ await {DATA_JS}.selectCase('{B}') }}")
    page.wait_for_timeout(4000)      # A 的後段（其餘 4 個預設階段＋子載入）都回來了
    state = page.evaluate(f"""() => {{ const c = {DATA_JS}; return {{
        no: c.selected.quote_no,
        notes: (c.shippingNotes || []).map(n => n.noteNo || n.note_no),
        assigned: c.assignedUserIds,
        stages: (c.cr.caseRecord.stages || []).map(s => s.label),
    }} }}""")
    assert state["no"] == B, state
    assert "SN-STALE-A" not in state["notes"], state
    assert state["assigned"] == [], state
    assert state["stages"] == ["B施工"], state
    page.evaluate(f"async () => {{ await {DATA_JS}.saveAssignedUsers() }}")
    assert _assigned(B) == [], "A 的成員名單被存進 B"
