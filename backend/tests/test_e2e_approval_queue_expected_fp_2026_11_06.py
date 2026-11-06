"""瀏覽器層級：簽核佇列核准時帶 expectedFp（簽核二擇一 S1b，2026-11-06）。

後端規則（比對、409、蓋章）在 modules/case/tests/test_content_fp_s1_2026_11_06.py。
這支確認畫面這一半：佇列頁核准的請求真的帶著『詳情當下算出的指紋』，被 409 擋下後會重載該筆詳情、
再按一次就帶新指紋簽成功。按鈕能按但沒帶指紋，是這個功能最容易的假綠燈。
"""
from tests._requires import requires_module  # noqa: E402
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

pytestmark = requires_module("case", "本檔的題打 M01（案件）的簽核佇列與報價單端點")

NO = "MQ-AQFP-001"


def _seed(approver):
    import db
    data = {"quoteNo": NO, "items": [{"name": "A", "qty": 1, "price": 100}],
            "approval": {"requestedBy": "sales_x", "requestedByDisplay": "業務X", "requestedAt": "2026-11-06T09:00:00",
                         "currentTier": 0,
                         "tiers": [{"approvers": [{"username": approver, "displayName": approver, "status": "pending"}]}]}}
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, "
                     "created_at, updated_at, deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (NO, "待審核", "指紋客戶", "指紋專案", 50000, 47619, json.dumps(data, ensure_ascii=False),
                      "2026-11-06T09:00:00", "2026-11-06T09:00:00", "", "業務X", "[]"))
        conn.commit()
    finally:
        conn.close()


def _edit_qty(qty):
    import db
    conn = db.get_db()
    try:
        d = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        d["items"][0]["qty"] = qty
        conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), NO))
        conn.commit()
    finally:
        conn.close()


def _state():
    import db
    conn = db.get_db()
    try:
        r = conn.execute("SELECT data_json, status FROM quotations WHERE quote_no=?", (NO,)).fetchone()
    finally:
        conn.close()
    d = json.loads(r["data_json"])
    return d["approval"]["tiers"][0]["approvers"][0], r["status"]


@pytest.mark.e2e
def test_queue_approve_sends_expected_fp_and_reloads_after_409(live_server, make_user, e2e_browser):
    u, p = make_user(username="aqfp_ap", role="admin", modules=["quotation"])
    _seed(u)
    page = e2e_browser.new_page()
    inject_login(page, live_server, u, p)

    page.on("dialog", lambda dlg: dlg.accept())          # 核准前的 confirm()、409 後的 alert()
    approves, details = [], []
    page.on("request", lambda rq: approves.append(rq.post_data_json) if rq.method == "POST" and rq.url.endswith("/approve") else None)
    page.on("response", lambda rs: details.append(rs) if "/api/approval-queue/detail" in rs.url else None)

    page.goto(f"{live_server}/pages/approval-queue.html")
    page.wait_for_selector(f'[data-testid="aq-item-{NO}"]', timeout=15000)
    page.click(f'[data-testid="aq-item-{NO}"]')
    page.wait_for_selector('[data-testid="aq-approve"]', state="visible", timeout=10000)
    for _ in range(50):
        if details:
            break
        page.wait_for_timeout(100)
    fp1 = details[-1].json()["contentFp"]
    assert fp1.startswith("1:")

    _edit_qty(5)                                        # 簽核人開著畫面時有人改了內容
    page.click('[data-testid="aq-approve"]')
    for _ in range(50):
        if len(details) >= 2:
            break
        page.wait_for_timeout(100)
    assert approves and approves[0].get("expectedFp") == fp1, "佇列頁核准沒把詳情的指紋帶回去：%s" % approves
    assert _state()[0]["status"] == "pending", "舊指紋被簽過去了"
    assert len(details) >= 2, "409 之後沒有重載該筆詳情"
    fp2 = details[-1].json()["contentFp"]
    assert fp2 != fp1

    page.click('[data-testid="aq-approve"]')            # 重看之後再簽：帶新指紋
    for _ in range(60):
        if _state()[0]["status"] == "approved":
            break
        page.wait_for_timeout(200)
    a, status = _state()
    assert a["status"] == "approved" and a["signedFp"] == fp2, a
    assert approves[-1].get("expectedFp") == fp2
