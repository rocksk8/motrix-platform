# -*- coding: utf-8 -*-
"""瀏覽器層級：核准前的「維持／編輯」彈窗（簽核二擇一 S5，2026-11-07）。

後端規則（旗標、409、confirmNote 強制、稽核）在 modules/case/tests/test_approve_choice_s5_2026_11_07.py。
這支確認畫面這一半——兩個核准入口（簽核佇列、報價單頁）共用同一支彈窗，而且 mode=on 遇到旗標單時**有操作路徑**（不會一直 409）：
- 佇列頁：旗標單 → 彈窗 → 新增原因要填說明才能按「維持核准」→ 請求帶 choice／confirmNote／expectedFp → 簽成功；取消不送請求；
  列表快速核准（沒載詳情）被 409 擋下後自動載入詳情再彈窗；
- 選「編輯內容」→ 轉到報價單頁（?reviewEdit=1）進入複查編輯 → 儲存走 POST /review-edit（只送真的改過的鍵）→ 編輯者的簽視為簽在新版；
- 報價單頁：轉簽旗標 → 彈窗（沒新增原因＝不用填說明）→ 簽成功；沒有旗標 ⇒ 不彈窗、維持原本的確認視窗（off 與今天相同）。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._requires import requires_module  # noqa: E402

pytestmark = requires_module("case", "本檔的題打 M01（案件）的簽核佇列與報價單端點")

NO = "MQ-AQCH-001"


def _set_mode(code):
    import db
    from helpers import settings_groups, settings_registry as SR       # noqa: F401
    from modules.case import content_fp as C
    c = db.get_db()
    try:
        SR.publish("quote_approval", {"reconfirm_mode": code}, reason="t", user="s5", conn=c)
        c.commit()
    finally:
        c.close()
    C._reset_mode_cache()


def _seed(approver, *, reconfirm=False, reassigned=False, cost=90.0, baseline_empty=True, next_tier=False):
    """單層；approver 是當層待簽人。reconfirm＝他簽過的版本過期（基準原因集合為空 ⇒ 目前的低毛利是新增原因）。"""
    import db
    from modules.case import content_fp as C
    entry = {"username": approver, "displayName": approver, "status": "pending"}
    data = {"quoteNo": NO, "customerName": "彈窗客戶", "projectName": "彈窗專案",
            "items": [{"id": "i1", "name": "A", "qty": 1, "cost": cost, "unitPrice": 100.0, "price": 100.0}],
            "tot": {"total": 105, "pretax": 100},
            "approval": {"requestedBy": "sales_x", "requestedByDisplay": "業務X", "requestedAt": "2026-11-07T09:00:00",
                         "currentTier": 0, "tiers": [{"approvers": [entry]}]}}
    if next_tier:                                              # 後面還有人沒簽 ⇒ 編輯者不是「最後一個待簽的人」，H2 才會自動重簽
        data["approval"]["tiers"].append({"approvers": [{"username": "aqch_next", "displayName": "aqch_next", "status": "pending"}]})
    if reconfirm:
        # 基準原因集合：空 ⇒ 目前的原因全是「新增」；＝目前的 ⇒ 沒有新增原因（一鍵維持）
        entry.update({"reconfirm": True, "signedFp": "1:old", "signedKeyHashes": {},
                      "signedReasonEntries": [] if baseline_empty else C.current_reasons_or_none(data)})
    if reassigned:
        entry["reassignedFrom"] = "someone"
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, "
                     "created_at, updated_at, deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (NO, "待審核", "彈窗客戶", "彈窗專案", 105, 100, json.dumps(data, ensure_ascii=False),
                      "2026-11-07T09:00:00", "2026-11-07T09:00:00", "", "業務X", "[]"))
        conn.commit()
    finally:
        conn.close()
    return C.content_fingerprint(data)


def _state():
    import db
    conn = db.get_db()
    try:
        r = conn.execute("SELECT data_json, status FROM quotations WHERE quote_no=?", (NO,)).fetchone()
        audits = [json.loads(x["detail"]) for x in conn.execute("SELECT detail FROM audit_log WHERE action='quotation.approve' AND target_id=?", (NO,))]
    finally:
        conn.close()
    d = json.loads(r["data_json"])
    return d, d["approval"]["tiers"][0]["approvers"][0], r["status"], audits


def _wait(pred, tries=60, ms=200, page=None):
    for _ in range(tries):
        if pred():
            return True
        page.wait_for_timeout(ms)
    return pred()


def _open_queue_item(page, live_server):
    page.goto(f"{live_server}/pages/approval-queue.html")
    page.wait_for_selector(f'[data-testid="aq-item-{NO}"]', timeout=15000)
    # 點列後 `selected` 先是列表那一筆、詳情（approveReview／contentFp）才非同步載入：只等按鈕可見會偶發在詳情到之前就按下去，
    # 走到「列表快速核准」路徑（先 POST → 409 → 載詳情 → 彈窗），與本檔其他題假設的「詳情已到、不送請求就跳彈窗」不同（T76 閘門抓到偶發紅）。
    # ⇒ 先等詳情回應，再給前端一個 tick 把它寫進畫面。
    with page.expect_response(lambda r: "/api/approval-queue/detail" in r.url and r.status == 200, timeout=10000):
        page.click(f'[data-testid="aq-item-{NO}"]')
    page.wait_for_selector('[data-testid="aq-approve"]', state="visible", timeout=10000)
    page.wait_for_timeout(300)


@pytest.mark.e2e
def test_queue_reconfirm_with_new_reason_needs_note_then_keeps(live_server, make_user, e2e_browser):
    u, p = make_user(username="aqch_ap", role="admin", modules=["quotation"])
    _set_mode(2)
    _seed(u, reconfirm=True)
    page = e2e_browser.new_page()
    inject_login(page, live_server, u, p)
    page.on("dialog", lambda dlg: dlg.accept())
    posts, details = [], []
    page.on("request", lambda rq: posts.append(rq.post_data_json) if rq.method == "POST" and rq.url.endswith("/approve") else None)
    page.on("response", lambda rs: details.append(rs) if "/api/approval-queue/detail" in rs.url else None)
    _open_queue_item(page, live_server)
    assert _wait(lambda: bool(details), page=page)
    fp = details[-1].json()["contentFp"]

    page.click('[data-testid="aq-approve"]')
    page.wait_for_selector('[data-testid="approve-choice-dialog"]', timeout=5000)
    assert "內容在你簽過之後有變動" in page.inner_text('[data-flag="reconfirm"]')
    assert "毛利率" in page.inner_text('[data-testid="approve-choice-reasons"]')
    assert page.is_disabled('[data-testid="approve-choice-keep"]'), "新增了需審核原因：沒填說明不能按「維持核准」"
    assert page.is_visible('[data-testid="approve-choice-edit"]')

    page.click('[data-testid="approve-choice-cancel"]')                        # 取消：不送請求、單據不動
    page.wait_for_selector('[data-testid="approve-choice-dialog"]', state="detached", timeout=3000)
    assert not posts and _state()[1]["status"] == "pending"

    page.click('[data-testid="aq-approve"]')
    page.wait_for_selector('[data-testid="approve-choice-dialog"]', timeout=5000)
    page.fill('[data-testid="approve-choice-note"]', "毛利掉了但客戶急單，我知道")
    assert not page.is_disabled('[data-testid="approve-choice-keep"]')
    page.click('[data-testid="approve-choice-keep"]')
    assert _wait(lambda: _state()[1]["status"] == "approved", page=page)
    d, entry, status, audits = _state()
    assert posts[-1]["choice"] == "keep" and posts[-1]["expectedFp"] == fp and posts[-1]["confirmNote"].startswith("毛利掉了")
    assert entry["signedFp"] == fp and "reconfirm" not in entry
    assert audits[-1]["flags"] == ["reconfirm"] and audits[-1]["choice"] == "keep" and audits[-1]["confirmNote"].startswith("毛利掉了")


@pytest.mark.e2e
def test_queue_quick_approve_of_flagged_item_is_not_stuck_on_409(live_server, make_user, e2e_browser):
    """mode=on 遇到旗標單：列表上的快速核准沒載詳情 ⇒ 第一次 409 ⇒ 自動載入詳情 ⇒ 彈窗 ⇒ 維持 ⇒ 簽成功（沒有操作路徑＝卡死的反面）。"""
    u, p = make_user(username="aqch_ap2", role="admin", modules=["quotation"])
    _set_mode(2)
    _seed(u, reassigned=True)
    page = e2e_browser.new_page()
    inject_login(page, live_server, u, p)
    page.on("dialog", lambda dlg: dlg.accept())
    statuses = []
    page.on("response", lambda rs: statuses.append(rs.status) if rs.url.endswith("/approve") and rs.request.method == "POST" else None)
    page.goto(f"{live_server}/pages/approval-queue.html")
    page.wait_for_selector(f'[data-testid="aq-item-{NO}"]', timeout=15000)
    quick = page.locator('[data-testid="aq-quick-approve"]')
    assert quick.count() >= 1, "列表上沒有快速核准按鈕"
    quick.first.click()
    page.wait_for_selector('[data-testid="approve-choice-dialog"]', timeout=8000)
    assert statuses[:1] == [409]
    assert "轉簽" in page.inner_text('[data-flag="reassigned"]')
    assert not page.is_visible('[data-testid="approve-choice-note"]'), "轉簽旗標沒有新增原因 ⇒ 不用填說明"
    page.click('[data-testid="approve-choice-keep"]')
    assert _wait(lambda: _state()[1]["status"] == "approved", page=page)
    assert _wait(lambda: statuses[-1:] == [200], page=page), statuses


@pytest.mark.e2e
def test_queue_edit_choice_goes_to_form_review_edit_and_resigns_the_editor(live_server, make_user, e2e_browser):
    u, p = make_user(username="aqch_ap3", role="admin", modules=["quotation"])
    _set_mode(2)
    _seed(u, reconfirm=True, cost=50.0, baseline_empty=False, next_tier=True)       # 基準＝目前的原因 ⇒ 沒有新增原因；後面還有一層 ⇒ 編輯者會被自動重簽
    page = e2e_browser.new_page()
    inject_login(page, live_server, u, p)
    page.on("dialog", lambda dlg: dlg.accept())
    reviews = []
    page.on("request", lambda rq: reviews.append(rq.post_data_json) if rq.method == "POST" and rq.url.endswith("/review-edit") else None)
    _open_queue_item(page, live_server)
    page.click('[data-testid="aq-approve"]')
    page.wait_for_selector('[data-testid="approve-choice-dialog"]', timeout=5000)
    assert not page.is_visible('[data-testid="approve-choice-note"]')
    page.click('[data-testid="approve-choice-edit"]')
    page.wait_for_url("**/quotation-form.html?id=*reviewEdit=1", timeout=10000)
    page.wait_for_selector('[data-testid="review-edit-bar"]', timeout=15000)
    page.evaluate("""() => { const el = document.querySelector('[x-data]'); const d = Alpine.$data(el); d.q.items[0].qty = 7; d.setDirty && d.setDirty() }""")
    page.click('[data-testid="review-edit-save"]')
    assert _wait(lambda: bool(reviews), page=page)
    d0, _e, _s, _a = _state()
    assert _wait(lambda: _state()[0]["items"][0]["qty"] == 7, page=page)
    d, entry, status, _audits = _state()
    sent = reviews[-1]["data"]
    # docType：讀取端點注入（資料庫欄位為準，舊單本文裡沒有這個鍵）；複查編輯端點會把它改回資料庫現值，所以頁面送回不算「多送」
    assert set(sent) <= set(d) | {"tot", "docType"}, "只送伺服器本文原有的鍵（加上真的改過的）：多出 %s" % (set(sent) - set(d))
    assert "isSigned" not in sent and "signedFiles" not in sent
    from modules.case import content_fp as C
    assert entry["status"] == "approved" and entry["signedFp"] == C.content_fingerprint(d), "H2：原已簽、正在複查的編輯者，簽視為已簽新版"
    assert "reconfirm" not in entry


@pytest.mark.e2e
def test_form_reassigned_flag_shows_dialog_and_keeps(live_server, make_user, e2e_browser):
    u, p = make_user(username="aqch_ap4", role="admin", modules=["quotation"])
    _set_mode(2)
    fp = _seed(u, reassigned=True, cost=50.0)
    page = e2e_browser.new_page()
    inject_login(page, live_server, u, p)
    page.on("dialog", lambda dlg: dlg.accept())
    posts = []
    page.on("request", lambda rq: posts.append(rq.post_data_json) if rq.method == "POST" and rq.url.endswith("/approve") else None)
    page.goto(f"{live_server}/pages/quotation-form.html?id={NO}")
    page.wait_for_selector('[data-testid="qf-approve-open-preview"]', state="visible", timeout=15000)
    page.click('[data-testid="qf-approve-open-preview"]')
    page.wait_for_selector('[data-testid="qf-approve-from-preview"]', state="visible", timeout=15000)
    page.click('[data-testid="qf-approve-from-preview"]')
    page.wait_for_selector('[data-testid="approve-choice-dialog"]', timeout=5000)
    assert "轉簽" in page.inner_text('[data-flag="reassigned"]')
    page.click('[data-testid="approve-choice-keep"]')
    assert _wait(lambda: _state()[1]["status"] == "approved", page=page)
    assert posts[-1]["choice"] == "keep" and posts[-1]["expectedFp"] == fp, "`?id=` 載入路徑要帶 expectedFp（原本只有 loadQuote() 路徑會設）"


@pytest.mark.e2e
def test_form_without_flags_keeps_the_plain_confirm(live_server, make_user, e2e_browser):
    """off／沒旗標：不彈窗、走原本的 confirm()（與今天相同）。"""
    u, p = make_user(username="aqch_ap5", role="admin", modules=["quotation"])
    fp = _seed(u, cost=50.0)
    page = e2e_browser.new_page()
    inject_login(page, live_server, u, p)
    confirms, posts = [], []
    page.on("dialog", lambda dlg: (confirms.append(dlg.message), dlg.accept()))
    page.on("request", lambda rq: posts.append(rq.post_data_json) if rq.method == "POST" and rq.url.endswith("/approve") else None)
    page.goto(f"{live_server}/pages/quotation-form.html?id={NO}")
    page.wait_for_selector('[data-testid="qf-approve-open-preview"]', state="visible", timeout=15000)
    page.click('[data-testid="qf-approve-open-preview"]')
    page.wait_for_selector('[data-testid="qf-approve-from-preview"]', state="visible", timeout=15000)
    page.click('[data-testid="qf-approve-from-preview"]')
    assert _wait(lambda: _state()[1]["status"] == "approved", page=page)
    assert any("確認簽核通過" in m for m in confirms) and page.locator('[data-testid="approve-choice-dialog"]').count() == 0
    assert "choice" not in posts[-1] and posts[-1]["expectedFp"] == fp


@pytest.mark.e2e
def test_dialog_traps_focus_and_closes_on_escape_and_overlay(live_server, make_user, e2e_browser):
    """S6（K 審 S5 的備註）：彈窗開著時 Tab／Shift+Tab 不會跳到背後的頁面；Esc 與點遮罩都等於取消（不送請求）。"""
    u, p = make_user(username="aqch_ft", role="admin", modules=["quotation"])
    _set_mode(2)
    _seed(u, reconfirm=True)
    page = e2e_browser.new_page()
    inject_login(page, live_server, u, p)
    page.on("dialog", lambda dlg: dlg.accept())
    posts = []
    page.on("request", lambda rq: posts.append(1) if rq.method == "POST" and rq.url.endswith("/approve") else None)
    _open_queue_item(page, live_server)
    inside = "() => !!document.activeElement.closest('[data-testid=approve-choice-dialog]')"
    page.click('[data-testid="aq-approve"]')
    page.wait_for_selector('[data-testid="approve-choice-dialog"]', timeout=5000)
    for _ in range(7):                                                         # 比可聚焦元件數多按幾次：一直在彈窗內循環
        page.keyboard.press("Tab")
        assert page.evaluate(inside)
    for _ in range(7):
        page.keyboard.press("Shift+Tab")
        assert page.evaluate(inside)
    page.keyboard.press("Escape")
    page.wait_for_selector('[data-testid="approve-choice-dialog"]', state="detached", timeout=3000)
    page.click('[data-testid="aq-approve"]')
    page.wait_for_selector('[data-testid="approve-choice-dialog"]', timeout=5000)
    page.mouse.click(5, 5)                                                     # 點遮罩（彈窗外）
    page.wait_for_selector('[data-testid="approve-choice-dialog"]', state="detached", timeout=3000)
    assert not posts and _state()[1]["status"] == "pending"
