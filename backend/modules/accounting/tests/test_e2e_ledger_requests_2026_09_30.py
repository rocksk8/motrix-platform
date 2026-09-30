# -*- coding: utf-8 -*-
"""瀏覽器端對端（含截圖）：總帳申請（會計規定 C 類）。財務人員在『期間與結帳』頁按結帳 ⇒ 送出申請（期間不變）；
撤回；最高管理者在『待我簽核』核准 ⇒ 自動執行（期間已結帳、申請已核准）；退回（填原因）⇒ 申請已退回、期間不變。
每顆按鈕都驗動作終點狀態（資料庫與畫面），不驗某一趟請求。截圖：D:\開發測試檔\shots\<分支>\（測試先存到暫存夾，事後複製）。"""
import os
import subprocess
import tempfile

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

import db  # noqa: E402
from modules.accounting.ledger import periods as P  # noqa: E402


def _shot(page, name):
    try:
        br = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, timeout=10,
                            cwd=os.path.dirname(__file__)).stdout.strip() or "unknown"
        d = os.path.join(os.environ.get("MOTRIX_SHOTS_DIR") or os.path.join(tempfile.gettempdir(), "w4-shots"), br.replace("/", "_"))
        os.makedirs(d, exist_ok=True)
        page.screenshot(path=os.path.join(d, name + ".png"), full_page=True)
    except Exception:  # noqa: BLE001
        pass


def _q(sql, *a):
    c = db.get_db()
    try:
        return c.execute(sql, a).fetchone()
    finally:
        c.close()


def _mk_year(year):
    c = db.get_db()
    try:
        P.create_year(c, year, "t")
        c.commit()
    finally:
        c.close()


def _request_close(page, live_server, pid_year, period_no):
    """財務人員在期間頁按『結帳』→ 對話框『確定』。"""
    page.locator("[data-testid=lp-close]").nth(period_no - 1).click()
    page.wait_for_selector("[data-testid=lp-dialog]", state="visible")
    page.locator("[data-testid=lp-submit]").click()
    page.wait_for_function("() => { const e = document.querySelector('[data-testid=lp-notice]'); return e && e.innerText.includes('已送出申請') }", timeout=15000)


@pytest.mark.e2e
def test_finance_requests_withdraws_then_superadmin_approves_and_it_executes(live_server, make_user, e2e_browser):
    fu, fp = make_user(username="e2e_rq_fin", role="staff", modules=["finance", "cashier"])
    su, sp = make_user(username="e2e_rq_sup", role="superadmin")
    _mk_year(2131)
    pid = _q("SELECT id FROM gl_periods WHERE year=2131 AND period_no=1")[0]
    page = e2e_browser.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    inject_login(page, live_server, fu, fp)
    page.goto("%s/pages/ledger-periods.html" % live_server)
    page.wait_for_selector("[data-testid=lp-close]", state="visible", timeout=20000)
    _request_close(page, live_server, 2131, 1)
    req = _q("SELECT id, request_no, status FROM gl_action_requests WHERE requested_by=? ORDER BY id DESC", fu)
    assert req["status"] == "待審核" and _q("SELECT status FROM gl_periods WHERE id=?", pid)[0] == "open"      # 終點：申請成立、期間沒動
    page.wait_for_selector("[data-testid=lp-req-%s]" % req["request_no"], state="visible")
    assert "待核准" in page.locator("[data-testid=lp-req-status-%s]" % req["request_no"]).inner_text()
    _shot(page, "requests_1_finance_pending")

    page.locator("[data-testid=lp-req-withdraw-%s]" % req["request_no"]).click()                              # 撤回
    page.wait_for_function("(no) => { const e = document.querySelector('[data-testid=\"lp-req-status-' + no + '\"]'); return e && e.innerText.includes('已撤回') }", arg=req["request_no"])
    assert _q("SELECT status FROM gl_action_requests WHERE id=?", req["id"])[0] == "已撤回"
    _shot(page, "requests_2_withdrawn")

    _request_close(page, live_server, 2131, 1)                                                                # 撤回後重新申請
    req = _q("SELECT id, request_no, status FROM gl_action_requests WHERE requested_by=? AND status='待審核'", fu)
    assert req
    page.close()

    page = e2e_browser.new_page()
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.on("dialog", lambda d: d.accept())                                                                   # 核准前的確認對話框
    inject_login(page, live_server, su, sp)
    page.goto("%s/pages/approval-queue.html" % live_server)
    page.locator("[data-testid=aq-item-%s]" % req["request_no"]).first.click()
    page.wait_for_selector("[data-testid=aq-approve]", state="visible")
    _shot(page, "requests_3_superadmin_queue")
    page.locator("[data-testid=aq-approve]").first.click()
    page.wait_for_function("() => true")
    for _ in range(100):                                                                                       # 終點：資料庫狀態（自動執行）
        if _q("SELECT status FROM gl_action_requests WHERE id=?", req["id"])[0] == "已核准":
            break
        page.wait_for_timeout(200)
    assert _q("SELECT status FROM gl_action_requests WHERE id=?", req["id"])[0] == "已核准"
    assert _q("SELECT status FROM gl_periods WHERE id=?", pid)[0] == "closed"                                  # 核准 ⇒ 期間真的結帳了
    assert _q("SELECT closed_by FROM gl_periods WHERE id=?", pid)[0] == fu                                     # 帳上結帳人是申請人
    _shot(page, "requests_4_approved_executed")
    assert not errs, errs[:3]
    page.close()


@pytest.mark.e2e
def test_superadmin_sends_back_with_reason_and_nothing_executes(live_server, make_user, e2e_browser):
    fu, fp = make_user(username="e2e_rq_fin2", role="staff", modules=["finance", "cashier"])
    su, sp = make_user(username="e2e_rq_sup2", role="superadmin")
    _mk_year(2132)
    pid = _q("SELECT id FROM gl_periods WHERE year=2132 AND period_no=1")[0]
    page = e2e_browser.new_page()
    inject_login(page, live_server, fu, fp)
    page.goto("%s/pages/ledger-periods.html" % live_server)
    page.wait_for_selector("[data-testid=lp-close]", state="visible", timeout=20000)
    _request_close(page, live_server, 2132, 1)
    req = _q("SELECT id, request_no FROM gl_action_requests WHERE requested_by=? AND status='待審核'", fu)
    page.close()

    page = e2e_browser.new_page()
    page.on("dialog", lambda d: d.accept())                                                                   # 核准前的確認對話框
    inject_login(page, live_server, su, sp)
    page.goto("%s/pages/approval-queue.html" % live_server)
    page.locator("[data-testid=aq-item-%s]" % req["request_no"]).first.click()
    page.wait_for_selector("[data-testid=aq-reject]", state="visible")
    page.locator("[data-testid=aq-reject]").first.click()
    page.locator("[data-testid=aq-reject-note]").fill("本期還有傳票沒過帳")
    _shot(page, "requests_5_reject_dialog")
    page.locator("[data-testid=aq-reject-confirm]").click()
    for _ in range(100):
        if _q("SELECT status FROM gl_action_requests WHERE id=?", req["id"])[0] == "已退回":
            break
        page.wait_for_timeout(200)
    row = _q("SELECT status, decision_note FROM gl_action_requests WHERE id=?", req["id"])
    assert row["status"] == "已退回" and "沒過帳" in row["decision_note"]
    assert _q("SELECT status FROM gl_periods WHERE id=?", pid)[0] == "open"                                    # 退回 ⇒ 什麼都沒執行
    page.close()

    page = e2e_browser.new_page()
    inject_login(page, live_server, fu, fp)
    page.goto("%s/pages/ledger-periods.html" % live_server)
    page.wait_for_selector("[data-testid=lp-req-status-%s]" % req["request_no"], state="visible", timeout=20000)
    assert "已退回" in page.locator("[data-testid=lp-req-status-%s]" % req["request_no"]).inner_text()          # 申請人看得到結果與原因
    assert "沒過帳" in page.locator("[data-testid=lp-req-%s]" % req["request_no"]).inner_text()
    _shot(page, "requests_6_returned_seen_by_requester")
    page.close()
