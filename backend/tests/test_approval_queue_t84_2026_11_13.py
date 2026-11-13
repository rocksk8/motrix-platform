# -*- coding: utf-8 -*-
"""簽核頁重排（T84，2026-11-13）：簽核依據（reasons）上卡片、單欄／雙欄版面、整頁空狀態、摘要格可點；
手機與桌機的核准／退回走同一組處理函式與同一個端點（沒有第二條寫入路徑）。"""
import json
import re

import pytest

from core import source_tree

pytest.importorskip("playwright.sync_api")


def _page():
    return source_tree.page_file("approval-queue.html").read_text(encoding="utf-8")


# ── 靜態：同一組處理函式 ───────────────────────────────────────────────────────────────────────
def test_every_approve_and_reject_button_goes_through_the_same_handlers():
    s = _page()
    clicks = re.findall(r'@click(?:\.stop)?="([^"]+)"', s)
    approve_like = {c for c in clicks if "approve" in c.lower() and "reject" not in c.lower()}
    reject_like = {c for c in clicks if c.lower().startswith(("quickreject", "openreject")) or c.startswith("doReject")}
    assert approve_like >= {"doApprove()", "quickApprove(item)"}, approve_like
    assert approve_like <= {"doApprove()", "quickApprove(item)"}, approve_like        # 沒有第三種核准入口
    assert {"openRejectModal()", "quickReject(item)"} <= reject_like, reject_like
    # 卡片快速鍵＝選中那一張再呼叫同一支（不另寫第二套寫入）
    assert "quickApprove(item) { this.selected = item; this.doApprove() }" in s
    assert "quickReject(item)  { this.selected = item; this.openRejectModal() }" in s
    # 底部固定列（手機）與抽屜按鈕（桌機）都是 aq-approve／aq-reject，走同一支
    for tid in ("aq-approve", "aq-reject"):
        assert f'data-testid="{tid}"' in s


def test_reasons_chip_uses_the_items_own_reasons_only():
    s = _page()
    assert "cardReasons(item).slice(0, 2)" in s and 'data-testid="aq-why"' in s
    assert "reasonsOf(item) {" in s and "typeof x === 'string'" in s          # 只收字串，其他形狀丟掉
    card = s.split('data-testid="aq-why"')[1][:700]
    assert "netMargin" not in card and "net_margin" not in card
    assert "/毛利/.test(t) ? '毛利率低於門檻' : t" in s         # 毛利類原因在卡片上合併成一句、不帶數字（PM 2026-11-13）


# ── e2e ───────────────────────────────────────────────────────────────────────────────────────
def _seed(quote_no, approver, requested_by="someone", reasons=None):
    import db
    at = "2026-11-10T09:00:00"
    data = {"quoteNo": quote_no, "approval": {"requestedBy": requested_by, "requestedAt": at, "currentTier": 0,
                                              "reasons": reasons or [],
                                              "tiers": [{"approvers": [{"username": approver, "displayName": approver,
                                                                        "status": "pending"}]}]}}
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, "
                     "updated_at, deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (quote_no, "待審核", "客戶" + quote_no, "專案", 1000, 952, json.dumps(data, ensure_ascii=False), at, at,
                      "", requested_by, "[]"))
        conn.commit()
    finally:
        conn.close()


def _open(page, live_server, login_as, user, quote_no=None):
    page.on("dialog", lambda d: d.accept())                              # 核准前的 confirm()：手機、桌機都一樣要按確定
    login_as(page, user)
    page.goto(f"{live_server}/pages/approval-queue.html")
    if quote_no:
        page.locator(f"[data-testid='aq-item-{quote_no}']").first.wait_for(state="visible", timeout=20000)


@pytest.mark.e2e
def test_card_shows_two_reasons_and_a_more_hint(live_server, make_user, new_page, login_as):
    u = make_user(username="t84_why", role="superadmin")
    _seed("MQ-T84-WHY", "t84_why", reasons=["毛利率低於門檻", "折讓超過 10%", "付款條件特殊"])
    page = new_page(viewport={"width": 1440, "height": 900})
    _open(page, live_server, login_as, u, "MQ-T84-WHY")
    why = page.locator("[data-testid='aq-item-MQ-T84-WHY']").first.locator("[data-testid=aq-why]")
    assert why.is_visible()
    assert why.locator(".aq-reason-tag").all_inner_texts() == ["毛利率低於門檻", "折讓超過 10%"]
    assert "還有 1 項" in why.inner_text()


@pytest.mark.e2e
def test_card_without_reasons_has_no_why_row(live_server, make_user, new_page, login_as):
    u = make_user(username="t84_nowhy", role="superadmin")
    _seed("MQ-T84-NOWHY", "t84_nowhy")
    page = new_page(viewport={"width": 1440, "height": 900})
    _open(page, live_server, login_as, u, "MQ-T84-NOWHY")
    assert not page.locator("[data-testid='aq-item-MQ-T84-NOWHY']").first.locator("[data-testid=aq-why]").is_visible()


@pytest.mark.e2e
def test_empty_state_replaces_the_two_empty_columns(live_server, make_user, new_page, login_as):
    u = make_user(username="t84_empty", role="sales", modules=["quotation"])
    page = new_page(viewport={"width": 1440, "height": 900})
    _open(page, live_server, login_as, u)
    box = page.locator("[data-testid=aq-empty]")
    box.wait_for(state="visible", timeout=20000)
    t = box.inner_text()
    assert "您送審的單據都簽完了" in t and "看今日工作事項" in t and "去報價單" in t and "回首頁" in t
    assert not page.locator(".aq-runway").first.is_visible()


@pytest.mark.e2e
def test_one_column_when_nothing_waits_on_others_and_two_columns_when_both(live_server, make_user, new_page, login_as):
    a = make_user(username="t84_col_a", role="sales", modules=["quotation"])
    make_user(username="t84_col_b", role="sales", modules=["quotation"])
    _seed("MQ-T84-COL1", "t84_col_a")                                  # 只有輪到 A 的單 ⇒ 右欄（流程中）是空的
    page = new_page(viewport={"width": 1440, "height": 900})
    _open(page, live_server, login_as, a, "MQ-T84-COL1")
    assert "aq-runway--one" in page.locator(".aq-runway").first.get_attribute("class")
    _seed("MQ-T84-COL2", "t84_col_b", requested_by="t84_col_a")      # A 送出、卡在 B ⇒ 兩欄都有東西
    page.reload()
    page.locator("[data-testid='aq-item-MQ-T84-COL2']").first.wait_for(state="visible", timeout=20000)
    assert "aq-runway--one" not in page.locator(".aq-runway").first.get_attribute("class")


@pytest.mark.e2e
def test_summary_tile_scrolls_to_its_column(live_server, make_user, new_page, login_as):
    a = make_user(username="t84_kpi_a", role="sales", modules=["quotation"])
    make_user(username="t84_kpi_b", role="sales", modules=["quotation"])
    _seed("MQ-T84-K1", "t84_kpi_a")
    _seed("MQ-T84-K2", "t84_kpi_b", requested_by="t84_kpi_a")
    page = new_page(viewport={"width": 390, "height": 600})            # 手機：兩欄直排，右欄在下面，才看得出有捲動
    _open(page, live_server, login_as, a, "MQ-T84-K2")
    # 捲動容器因版面而異（頁面可能短到無處可捲）⇒ 驗「點了之後確實對那一欄呼叫 scrollIntoView」，不量像素
    page.evaluate("window.__sc = []; Element.prototype.scrollIntoView = function () { window.__sc.push(this.id) }")
    for tid, col in (("aq-kpi-flow", "aq-col-flow"), ("aq-kpi-mine", "aq-col-mine")):
        tile = page.locator(f"[data-testid={tid}]")
        tile.wait_for(state="visible")
        assert tile.get_attribute("role") == "button" and tile.get_attribute("tabindex") == "0"
        tile.click()
        assert page.evaluate("window.__sc")[-1] == col


def _capture_write(page, trigger):
    got = []

    def on_req(r):
        if r.method == "POST" and re.search(r"/api/quotations/[^/]+/(approve|reject)$", r.url):
            got.append((r.method, r.url, r.post_data))
    page.on("request", on_req)
    trigger()
    page.wait_for_timeout(1500)
    assert got, "沒有送出任何核准／退回請求"
    m, url, body = got[-1]
    path = re.sub(r"^https?://[^/]+", "", url)
    path = re.sub(r"/api/quotations/[^/]+/", "/api/quotations/{no}/", path)
    keys = sorted(json.loads(body).keys()) if body else []
    return m, path, keys


@pytest.mark.e2e
@pytest.mark.parametrize("action", ["approve", "reject"])
def test_mobile_and_desktop_hit_the_same_endpoint_with_the_same_body_shape(live_server, make_user, new_page, login_as, action):
    u = make_user(username="t84_same_" + action, role="superadmin")
    _seed("MQ-T84-D-" + action, u[0])
    _seed("MQ-T84-M-" + action, u[0])
    out = {}
    for label, vp, no in (("desktop", {"width": 1440, "height": 900}, "MQ-T84-D-" + action),
                          ("mobile", {"width": 390, "height": 800}, "MQ-T84-M-" + action)):
        page = new_page(viewport=vp)
        _open(page, live_server, login_as, u, no)
        card = page.locator(f"[data-testid='aq-item-{no}']").first

        def trig(page=page, card=card, label=label):
            if label == "desktop":                                          # 桌機：卡片上的快速鍵
                if action == "approve":
                    card.locator("[data-testid=aq-quick-approve]").click()
                else:
                    card.locator(".aq-card__act .btn-reject").first.click()
            else:                                                           # 手機：點開詳情，用底部固定的簽核列
                card.click()
                bar = page.locator("[data-testid=aq-actbar]")
                bar.wait_for(state="visible", timeout=10000)
                bar.locator(f"[data-testid=aq-{action}]").click()
            if action == "reject":                                          # 兩邊都要填原因才送得出去
                page.locator("[data-testid=reject-reason]").fill("T84 測試退回原因")
                page.locator("[data-testid=reject-confirm]").click()
        out[label] = _capture_write(page, trig)
        page.close()
    assert out["desktop"] == out["mobile"], out
    assert out["desktop"][0] == "POST" and out["desktop"][1].endswith("/" + action)


@pytest.mark.e2e
def test_card_margin_reasons_show_no_numbers_but_drawer_keeps_them(live_server, make_user, new_page, login_as):
    u = make_user(username="t84_margin", role="superadmin")
    _seed("MQ-T84-MARGIN", "t84_margin", reasons=["第 1 項毛利率 12.50% 低於 30%", "第 3 項毛利率 -100.00% 低於 30%", "付款條件特殊"])
    page = new_page(viewport={"width": 390, "height": 800})
    _open(page, live_server, login_as, u, "MQ-T84-MARGIN")
    card = page.locator("[data-testid='aq-item-MQ-T84-MARGIN']").first
    why = card.locator("[data-testid=aq-why]")
    assert why.locator(".aq-reason-tag").all_inner_texts() == ["毛利率低於門檻", "付款條件特殊"]    # 兩項毛利合成一句
    assert not re.search(r"\d", why.inner_text()), why.inner_text()
    card.click()                                                                                    # 完整數字在詳情抽屜
    page.locator(".aq-reasons").first.wait_for(state="visible", timeout=10000)
    assert "12.50%" in page.locator(".aq-reasons").first.inner_text()


@pytest.mark.e2e
def test_load_failure_shows_retry_and_recovers(live_server, make_user, new_page, login_as):
    u = make_user(username="t84_retry", role="superadmin")
    _seed("MQ-T84-RETRY", "t84_retry")
    page = new_page(viewport={"width": 1440, "height": 900})
    state = {"fail": True}

    def handler(route):
        if state["fail"]:
            route.fulfill(status=500, content_type="application/json", body=json.dumps({"detail": "boom"}))
        else:
            route.continue_()
    page.route("**/api/approval-queue", handler)
    _open(page, live_server, login_as, u)
    err = page.locator("[data-testid=aq-load-error]")
    err.wait_for(state="visible", timeout=20000)
    assert "讀取失敗，請重試" in err.inner_text() and not page.locator("[data-testid=aq-empty]").is_visible()
    state["fail"] = False
    page.locator("[data-testid=aq-retry]").click()
    page.locator("[data-testid='aq-item-MQ-T84-RETRY']").first.wait_for(state="visible", timeout=20000)
    assert not err.is_visible()


@pytest.mark.e2e
def test_summary_tiles_respond_to_space(live_server, make_user, new_page, login_as):
    a = make_user(username="t84_space_a", role="sales", modules=["quotation"])
    make_user(username="t84_space_b", role="sales", modules=["quotation"])
    _seed("MQ-T84-SP1", "t84_space_a")
    _seed("MQ-T84-SP2", "t84_space_b", requested_by="t84_space_a")
    page = new_page(viewport={"width": 390, "height": 600})
    _open(page, live_server, login_as, a, "MQ-T84-SP2")
    page.evaluate("window.__sc = []; Element.prototype.scrollIntoView = function () { window.__sc.push(this.id) }")
    page.locator("[data-testid=aq-kpi-flow]").focus()
    page.keyboard.press("Space")
    assert page.evaluate("window.__sc")[-1] == "aq-col-flow"
