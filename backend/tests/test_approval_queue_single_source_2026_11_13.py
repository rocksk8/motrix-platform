# -*- coding: utf-8 -*-
"""待我簽核頁（UX P1.5）：摘要與列表同一個來源、流程中寫「卡在誰、已幾天」、手機可簽核。

之前同一頁有兩套「待我簽核」算法（摘要 myPendingCount 比 currentApprovers，列表 myItems 用 canApprove()），會分歧。
現在伺服器在每一項標 `mine`（與 `/api/approval-queue/count` 同一個 `_counts_for_me`），頁面三處都從它來。
"""
import json
import pathlib

import pytest

from core import source_tree
from tests._requires import requires_module

pytestmark = requires_module("case", "題目打 M01 的簽核佇列端點")
REPO = pathlib.Path(__file__).resolve().parents[2]


def _seed(quote_no, approvers, requested_by="applicant", at="2026-11-10T09:00:00", current=0):
    import db
    data = {"quoteNo": quote_no, "approval": {"requestedBy": requested_by, "requestedAt": at, "currentTier": current,
                                             "tiers": [{"approvers": [{"username": u, "displayName": u, "status": "pending"} for u in approvers]}]}}
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, sales_person, assigned_user_ids) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (quote_no, "待審核", "客戶" + quote_no, "專案", 1000, 952, json.dumps(data, ensure_ascii=False), at, at, "", requested_by, "[]"))
        conn.commit()
    finally:
        conn.close()


def _h(client, u, p):
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def test_queue_items_carry_mine_and_my_count_equals_badge_count(client, make_user):
    a = make_user("aq_a", role="sales", modules=["quotation"])
    b = make_user("aq_b", role="sales", modules=["quotation"])
    sa = make_user("aq_sa", role="superadmin")
    _seed("MQ-S-001", ["aq_a"])
    _seed("MQ-S-002", ["aq_a", "aq_b"])
    _seed("MQ-S-003", ["aq_b"])
    for u in (a, b, sa):
        h = _h(client, *u)
        q = client.get("/api/approval-queue", headers=h).json()
        items = [it for g in q["queue"] for it in g["items"]]
        assert all(isinstance(it.get("mine"), bool) for it in items)
        badge = client.get("/api/approval-queue/count", headers=h).json()["count"]
        assert q["myCount"] == sum(1 for it in items if it["mine"]) == badge, (u[0], q["myCount"], badge)
    qa = client.get("/api/approval-queue", headers=_h(client, *a)).json()
    mine = sorted(it["quoteNo"] for g in qa["queue"] for it in g["items"] if it["mine"])
    assert mine == ["MQ-S-001", "MQ-S-002"]


def test_delegate_counts_as_mine_in_the_same_way_as_badge(client, make_user):
    """代理人：角標算、頁面也要算（同一個判斷，不會一邊有一邊沒有）；委派到期後兩邊一起不算。"""
    import db
    from datetime import date, timedelta
    make_user("aq_boss", role="sales", modules=["quotation"])
    d = make_user("aq_deputy", role="sales", modules=["quotation"])
    _seed("MQ-S-010", ["aq_boss"])
    h = _h(client, *d)
    assert client.get("/api/approval-queue", headers=h).json()["myCount"] == 0
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO approval_delegates (delegator_username, delegate_username, start_date, end_date, reason, active, created_by, created_at, updated_at) "
                     "VALUES (?,?,?,?,?,1,?,?,?)", ("aq_boss", "aq_deputy", (date.today() - timedelta(days=1)).isoformat(),
                                                      (date.today() + timedelta(days=3)).isoformat(), "測試", "aq_boss", "2026-01-01T00:00:00", "2026-01-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()
    q = client.get("/api/approval-queue", headers=h).json()
    items = [it for g in q["queue"] for it in g["items"]]
    assert q["myCount"] == 1 == client.get("/api/approval-queue/count", headers=h).json()["count"]
    assert [it["quoteNo"] for it in items if it["mine"]] == ["MQ-S-010"]


def test_page_uses_the_server_flag_and_has_no_second_algorithm():
    s = source_tree.page_file("approval-queue.html").read_text(encoding="utf-8")
    assert "isMine(i) { return i && typeof i.mine === 'boolean' ? i.mine : this.canApprove(i) }" in s
    assert "get myPendingCount() { return this.myItems.length }" in s
    assert "_isMeOrDelegate(a.username) && a.status !== 'approved')\n          }).length" not in s, "摘要又自己另算了一次"
    assert "get myItems()   { return this.flatItems.filter(i => this.isMine(i)) }" in s
    assert "get flowItems() { return this.flatItems.filter(i => !this.isMine(i)) }" in s


def test_flow_rows_say_stuck_with_whom_and_how_long():
    s = source_tree.page_file("approval-queue.html").read_text(encoding="utf-8")
    assert 'data-testid="aq-stuck" x-text="stuckText(item)"' in s
    assert "'待' + this.blockerOf(item).display + '處理，'" in s


def test_reject_vs_final_reject_is_explained_on_the_page():
    s = source_tree.page_file("approval-queue.html").read_text(encoding="utf-8")
    assert 'data-testid="aq-reject-hint"' in s and "送回申請人修改" in s and "這張單不再處理" in s


# ── 瀏覽器：摘要＝欄位件數；流程中寫卡在誰；手機操作列在畫面內 ─────────────────────────
@pytest.mark.e2e
def test_summary_equals_column_count_and_flow_rows_show_blocker(live_server, make_user, new_page, login_as):
    a = make_user("aq_e2e_a", role="sales", modules=["quotation"])
    make_user("aq_e2e_b", role="sales", modules=["quotation"])
    sa = make_user("aq_e2e_sa", role="superadmin")
    _seed("MQ-E-001", ["aq_e2e_a"])
    _seed("MQ-E-002", ["aq_e2e_b"])
    page = new_page(viewport={"width": 1440, "height": 900})
    login_as(page, sa)
    page.goto(f"{live_server}/pages/approval-queue.html")
    page.wait_for_selector("text=MQ-E-002", timeout=20000)
    summary = int(page.locator(".vm-andon__seg--mine .vm-andon__val").inner_text())
    col = int(page.locator(".aq-col").first.locator(".aq-col__count").inner_text().split()[0])
    assert summary == col
    stuck = page.locator("[data-testid=aq-stuck]").all_inner_texts()
    assert stuck and all(t.startswith("待") and "處理，" in t and ("已" in t or "今天" in t) for t in stuck), stuck
    assert any("aq_e2e_b" in t for t in stuck)


@pytest.mark.e2e
def test_mobile_action_bar_is_reachable_and_buttons_are_tappable(live_server, make_user, new_page, login_as):
    a = make_user("aq_m_a", role="sales", modules=["quotation"])
    _seed("MQ-M-001", ["aq_m_a"])
    page = new_page(viewport={"width": 390, "height": 760})
    login_as(page, a)
    page.goto(f"{live_server}/pages/approval-queue.html")
    page.wait_for_selector("text=MQ-M-001", timeout=20000)
    for sel in ("[data-testid=aq-quick-approve]", ".aq-card__act .btn-reject"):
        box = page.locator(sel).first.bounding_box()
        assert box and box["height"] >= 44 and box["x"] >= 0 and box["x"] + box["width"] <= 390, (sel, box)
    page.click("text=MQ-M-001")
    bar = page.locator("[data-testid=aq-actbar]")
    bar.wait_for(state="visible", timeout=10000)
    page.wait_for_timeout(500)
    box = bar.bounding_box()
    assert box and box["y"] + box["height"] <= 760 + 1, box          # 黏在畫面底部，不必捲到最底
    assert bar.locator("[data-testid=aq-approve]").is_visible() and bar.locator("[data-testid=aq-reject]").is_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "手機版出現橫向捲動"
