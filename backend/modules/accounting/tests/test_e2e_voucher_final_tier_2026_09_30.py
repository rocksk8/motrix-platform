# -*- coding: utf-8 -*-
"""瀏覽器端對端（含截圖）：傳票最終關卡＝最高管理者（會計主管，系統規定）。

按鈕全走：送審、核准（出納／財務擋在最終層、最高管理者通過）、退回（填原因）、過帳、作廢（填原因）；
以動作終點狀態驗（傳票狀態欄與後端），不驗某一趟請求。截圖：D:\\開發測試檔\\shots\\<分支>\\。
"""
import json
import os
import tempfile
import subprocess

import pytest

import db

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

VC = "Alpine.$data(document.body)"
H = {k: '[data-testid="voucher-%s"]' % k for k in ("submit", "approve", "post", "sendback", "void", "reason", "reason-ok", "status")}


def _shot(page, name):
    try:
        br = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, timeout=10,
                            cwd=os.path.dirname(__file__)).stdout.strip() or "unknown"
        d = os.path.join(os.environ.get("MOTRIX_SHOTS_DIR") or os.path.join(tempfile.gettempdir(), "w4-shots"), br.replace("/", "_"))
        os.makedirs(d, exist_ok=True)
        page.set_viewport_size({"width": 1280, "height": 1250})           # 一屏拍完：不用 full_page（黏在頂端的導覽列會被拼進中段）
        page.evaluate("() => window.scrollTo(0, 0)")
        page.screenshot(path=os.path.join(d, name + ".png"), full_page=False)
    except Exception:  # noqa: BLE001  截圖失敗不影響驗證
        pass


_CTX = {}


def _api(base, method, path, token=None, body=None):
    """走 playwright 的請求物件（不是 urllib：NETGUARD 會擋測試自己對外連線）。"""
    r = _CTX["req"].fetch(base + path, method=method, data=json.dumps(body or {}),
                          headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
    assert r.ok, "%s %s -> %s %s" % (method, path, r.status, r.text()[:200])
    return r.json()


def _draft(base, user, pw, summary):
    tok = _api(base, "POST", "/api/auth/login", body={"username": user, "password": pw})["token"]
    r = _api(base, "POST", "/api/vouchers", tok, {"voucher_date": "2185-05-10", "summary": summary, "lines": [
        {"account_code": "1113", "summary": "x", "debit": 1000, "credit": 0}, {"account_code": "4111", "summary": "x", "debit": 0, "credit": 1000}]})
    return r["id"], tok


def _get(base, tok, vid):
    d = _api(base, "GET", "/api/vouchers/%d" % vid, tok)
    return d.get("voucher") or d


def _status(base, tok, vid):
    return _get(base, tok, vid).get("status")


def _open(page, base, user, pw, vid):
    inject_login(page, base, user, pw)
    page.goto("%s/pages/voucher.html" % base)
    page.wait_for_function("() => window.Alpine && %s && %s._accountsLoaded" % (VC, VC), timeout=20000)
    page.evaluate("(id) => %s.open(id)" % VC, vid)
    page.wait_for_selector(H["status"], state="visible", timeout=15000)


def _click(page, key):
    page.locator(H[key]).first.click()
    page.wait_for_function("() => { const d = %s; return d && !d.busy }" % VC, timeout=30000)
    page.evaluate("() => new Promise(r => Alpine.nextTick(r))")


def _reason(page, text):
    page.locator(H["reason"]).first.fill(text)
    _click(page, "reason-ok")


@pytest.mark.e2e
def test_final_tier_buttons_submit_approve_blocked_approve_post(live_server, make_user, e2e_browser):
    _CTX["req"] = e2e_browser.new_page().request
    fu, fp = make_user(username="e2e_ft_fin", role="staff", modules=["cashier", "finance"])
    su, sp = make_user(username="e2e_ft_sup", role="superadmin")
    vid, ftok = _draft(live_server, fu, fp, "最終關卡 e2e")
    stok = _api(live_server, "POST", "/api/auth/login", body={"username": su, "password": sp})["token"]
    page = e2e_browser.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    _open(page, live_server, fu, fp, vid)
    _shot(page, "voucher_final_1_draft")
    _click(page, "submit")
    assert _status(live_server, ftok, vid) == "待審核"
    _shot(page, "voucher_final_2_submitted")
    _click(page, "approve")                                             # 第一層（覆核）：出納／財務可簽
    assert _status(live_server, ftok, vid) == "簽核中"
    # 最終層：財務不是最高管理者 ⇒ 簽核／退回鍵停用，旁邊寫明原因（不是按下去才被拒絕）
    assert page.locator(H["approve"]).first.is_disabled() and page.locator(H["sendback"]).first.is_disabled()
    reason = page.locator("[data-testid=voucher-blocked-reason]").first
    assert reason.is_visible() and "最高管理者" in reason.inner_text()
    assert _status(live_server, ftok, vid) == "簽核中"
    _shot(page, "voucher_final_3_blocked_for_finance")
    page.close()

    page = e2e_browser.new_page()
    page.on("pageerror", lambda e: errs.append(str(e)))
    _open(page, live_server, su, sp, vid)
    _click(page, "approve")                                             # 最高管理者核准 ⇒ 已核准
    assert _status(live_server, stok, vid) == "已核准"
    _shot(page, "voucher_final_4_approved_by_superadmin")
    _click(page, "post")
    assert _status(live_server, stok, vid) == "已過帳"
    _shot(page, "voucher_final_5_posted")
    assert not errs, errs[:3]
    page.close()


@pytest.mark.e2e
def test_final_tier_buttons_send_back_and_void(live_server, make_user, e2e_browser):
    _CTX["req"] = e2e_browser.new_page().request
    fu, fp = make_user(username="e2e_ft_fin2", role="staff", modules=["cashier", "finance"])
    su, sp = make_user(username="e2e_ft_sup2", role="superadmin")
    vid, ftok = _draft(live_server, fu, fp, "最終關卡 退回作廢 e2e")
    stok = _api(live_server, "POST", "/api/auth/login", body={"username": su, "password": sp})["token"]
    page = e2e_browser.new_page()
    _open(page, live_server, fu, fp, vid)
    _click(page, "submit")
    page.close()
    page = e2e_browser.new_page()
    _open(page, live_server, su, sp, vid)
    page.locator(H["sendback"]).first.click()
    _reason(page, "科目要改")
    assert _status(live_server, stok, vid) == "草稿"
    _shot(page, "voucher_final_6_sent_back")
    _click(page, "submit")
    _click(page, "approve")
    _click(page, "approve")
    assert _status(live_server, stok, vid) == "已核准"
    _click(page, "post")
    assert _status(live_server, stok, vid) == "已過帳"
    page.locator(H["void"]).first.click()
    _reason(page, "e2e 作廢")
    v = _get(live_server, stok, vid)
    assert v.get("voided_at") and v.get("void_reason") == "e2e 作廢"                                   # 作廢＝留痕（原單保留狀態，另記時間與原因）
    _shot(page, "voucher_final_7_voided")
    page.close()


@pytest.mark.e2e
def test_any_superadmin_can_approve_the_final_tier_from_the_queue_page(live_server, make_user, e2e_browser):
    """待我簽核頁：最終關卡（系統規定）是『同層任一人』，不是循序——第二位最高管理者也按得到核准（曾只有名單第一位有按鈕）。"""
    _CTX["req"] = e2e_browser.new_page().request
    fu, fp = make_user(username="e2e_ft_fin3", role="staff", modules=["cashier", "finance"])
    s1, p1 = make_user(username="e2e_ft_supA", role="superadmin")
    s2, p2 = make_user(username="e2e_ft_supB", role="superadmin")
    from helpers import _set_setting
    _set_setting("voucher_approval_flow", {"includeSubmitterManagerTier": False, "tiers": [{"order": 0, "approvers": [{"username": fu, "displayName": fu}]}]})
    vid, ftok = _draft(live_server, fu, fp, "最終關卡 佇列 e2e")
    page = e2e_browser.new_page()
    _open(page, live_server, fu, fp, vid)
    _click(page, "submit")
    _click(page, "approve")                                             # 第一層：設定的簽核人（財務）
    assert _get(live_server, ftok, vid)["approval"]["tiers"][1]["system"] is True if "approval" in _get(live_server, ftok, vid) else True
    page.close()
    order = _api(live_server, "POST", "/api/auth/login", body={"username": s2, "password": p2})["token"]
    page = e2e_browser.new_page()
    page.on("dialog", lambda d: d.accept())                             # 核准前有確認對話框
    inject_login(page, live_server, s2, p2)                             # 名單靠後的那位最高管理者
    page.goto("%s/pages/approval-queue.html" % live_server)
    no = _get(live_server, ftok, vid)["voucher_no"]
    page.locator("[data-testid=aq-item-%s]" % no).first.click()
    page.wait_for_selector("[data-testid=aq-approve]", state="visible", timeout=20000)
    _shot(page, "voucher_final_8_queue_second_superadmin")
    page.locator("[data-testid=aq-approve]").first.click()
    for _ in range(100):
        if _status(live_server, order, vid) == "已核准":
            break
        page.wait_for_timeout(200)
    assert _status(live_server, order, vid) == "已核准"
    page.close()
    c = db.get_db()
    try:
        c.execute("DELETE FROM system_settings WHERE key='voucher_approval_flow'")
        c.commit()
    finally:
        c.close()
