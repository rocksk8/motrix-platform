# -*- coding: utf-8 -*-
"""瀏覽器端對端（含截圖）：獎金更正單頁（`/pages/bonus-corrections.html`，2026-09-30 使用者核准）。

每顆按鈕都按、驗**動作終點狀態**（資料庫＋畫面），不驗某一趟請求：
載入目前金額 → 加人／移除 → 建立草稿 → 修改草稿 → 送審 → 自簽被擋 → 駁回（要原因）→ 再送審 → 核准（簽核人≠申請人）
→ 傳票（沖轉／重開）→ 出納標記補發 → 已完成；另一張：減少（追回）→ 核准即完成、追回應收傳票與「追回處理方式待確認」標示；作廢草稿。
截圖：暫存夾（BK19 不准寫 repo 外），事後複製到 D:\\開發測試檔\\shots\\wip-w2-bonus-correction\\。"""
import json
import os
import tempfile

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from modules.payroll.tests._bonus_insure import insure_all  # noqa: E402

PAGE = "/pages/bonus-corrections.html"
DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"


def _shot(page, name):
    try:
        d = os.path.join(os.environ.get("MOTRIX_SHOTS_DIR") or os.path.join(tempfile.gettempdir(), "w2-shots"),
                         "wip-w2-bonus-correction")
        os.makedirs(d, exist_ok=True)
        page.screenshot(path=os.path.join(d, name + ".png"), full_page=True)
    except Exception:  # noqa: BLE001
        pass


def _q(sql, *a):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, a)]
    finally:
        c.close()


def _corr(cn):
    return _q("SELECT * FROM bonus_corrections WHERE corr_no=?", cn)[0]


def _setup(live_server, make_user, browser, no):
    """做出一張已發放、應付傳票已過帳的獎金分潤單；回 (users, api_headers 取得函式)。"""
    import db
    u = {}
    for name, role, mods in (("e2c_sa", "superadmin", None), ("e2c_sa2", "superadmin", None),
                             ("e2c_s1", "sales", None), ("e2c_p1", "engineer", None), ("e2c_a1", "engineer", None),
                             ("e2c_cash", "engineer", ["cashier"])):
        u[name] = make_user(username=name, role=role, modules=mods)
    data = {"dealTag": "已結案", "caseRecord": {"roles": {"executor": ""}},
            "settlement": {"status": "finalized", "summary": {"netProfit": 100000}}}
    c = db.get_db()
    try:
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at,"
                  " deal_tag, sales_person, sales_person_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (no, "已送出", "更正客戶", "更正專案", json.dumps(data, ensure_ascii=False), "2026-09-01", "2026-09-01", "已結案", "", None))
        c.commit()
    finally:
        c.close()
    ctx = browser.new_context()
    req = ctx.request

    def hdr(name):
        r = req.post(f"{live_server}/api/auth/login", data={"username": name, "password": u[name][1]})
        return {"Authorization": "Bearer " + r.json()["token"]}
    sa, sa2, cash = hdr("e2c_sa"), hdr("e2c_sa2"), hdr("e2c_cash")
    assert req.post(f"{live_server}/api/bonus/cases/{no}", headers=sa, data={"members": {
        "sales": [{"username": "e2c_s1"}], "project": [{"username": "e2c_p1"}]}}).ok
    assert req.post(f"{live_server}/api/bonus/cases/{no}/submit", headers=sa).ok
    assert req.post(f"{live_server}/api/bonus/cases/{no}/approve", headers=sa2).ok
    insure_all()
    assert req.post(f"{live_server}/api/bonus/cases/{no}/mark-paid", headers=cash, data={}).ok
    vid = _q("SELECT accrual_voucher_id FROM bonus_case_awards WHERE quote_no=?", no)[0]["accrual_voucher_id"]
    c = db.get_db()
    try:
        c.execute("UPDATE vouchers_all SET status='已過帳' WHERE id=?", (vid,))   # 模擬會計已過帳（總帳只沖轉已過帳傳票）
        c.commit()
    finally:
        c.close()
    return u


def _page_as(browser, live_server, cred):
    p = browser.new_context().new_page()
    inject_login(p, live_server, *cred)
    p.goto(live_server + PAGE)
    p.locator('[data-testid="bc-list"], [data-testid="bc-empty"]').first.wait_for(timeout=20000)
    return p


def _msg(page):
    return page.inner_text('[data-testid="bc-msg"]') if page.locator('[data-testid="bc-msg"]').count() else ""


@pytest.mark.e2e
def test_full_lifecycle_supplement(live_server, make_user, e2e_browser):
    no = "MQ-202609-931"
    u = _setup(live_server, make_user, e2e_browser, no)
    sa = _page_as(e2e_browser, live_server, u["e2c_sa"])
    _shot(sa, "01-list-empty")
    # 載入目前金額
    sa.fill('[data-testid="bc-new-quote"]', no)
    sa.locator('[data-testid="bc-load-current"]').click()
    sa.locator('[data-testid="bc-form"]').wait_for(timeout=15000)
    cur = {r["username"]: r["amount"] for r in _q("SELECT username, amount FROM bonus_case_award_lines WHERE award_id="
                                                   "(SELECT id FROM bonus_case_awards WHERE quote_no=?)", no)}
    assert sa.locator('[data-testid="bc-line-e2c_s1"]').count() == 1 and sa.locator('[data-testid="bc-line-e2c_p1"]').count() == 1
    # 加人 → 移除 → 再加（兩顆按鈕）
    sa.select_option('[data-testid="bc-add-pick"]', "e2c_a1")
    sa.locator('[data-testid="bc-add"]').click()
    sa.locator('[data-testid="bc-line-e2c_a1"]').wait_for(timeout=5000)
    sa.locator('[data-testid="bc-remove-e2c_a1"]').click()
    assert sa.locator('[data-testid="bc-line-e2c_a1"]').count() == 0
    sa.select_option('[data-testid="bc-add-pick"]', "e2c_a1")
    sa.locator('[data-testid="bc-add"]').click()
    sa.fill('[data-testid="bc-new-amt-e2c_a1"]', "2000")
    sa.fill('[data-testid="bc-new-amt-e2c_s1"]', str(cur["e2c_s1"] + 1000))
    # 原因必填
    sa.locator('[data-testid="bc-save"]').click()
    sa.wait_for_function("() => document.body.innerText.includes('原因')", timeout=5000)
    assert _q("SELECT COUNT(*) AS n FROM bonus_corrections")[0]["n"] == 0
    sa.fill('[data-testid="bc-reason"]', "補登行政人員並調整業務金額")
    _shot(sa, "02-form-filled")
    assert "3,000" in sa.inner_text('[data-testid="bc-form-supplement"]').replace("NT$ ", "") or \
        "3000" in sa.inner_text('[data-testid="bc-form-supplement"]').replace(",", "")
    sa.locator('[data-testid="bc-save"]').click()
    cn = no + "-C1"
    sa.locator(f'[data-testid="bc-item-{cn}"]').wait_for(timeout=15000)
    c = _corr(cn)
    assert c["status"] == "草稿" and (c["supplement_total"], c["clawback_total"]) == (3000, 0)
    # 修改草稿
    sa.locator(f'[data-testid="bc-item-{cn}"]').click()
    sa.locator('[data-testid="bc-edit"]').click()
    sa.fill('[data-testid="bc-new-amt-e2c_a1"]', "2500")
    sa.locator('[data-testid="bc-save"]').click()
    sa.wait_for_function("() => true")
    sa.wait_for_timeout(800)
    assert _corr(cn)["supplement_total"] == 3500
    # 送審
    sa.locator(f'[data-testid="bc-item-{cn}"]').click()
    sa.locator('[data-testid="bc-submit"]').click()
    sa.wait_for_timeout(800)
    assert _corr(cn)["status"] == "待審核"
    _shot(sa, "03-pending-review")
    # 自簽被擋：申請人自己核准 ⇒ 狀態不變、沒有傳票
    sa.locator('[data-testid="bc-approve"]').click()
    sa.wait_for_timeout(800)
    assert _corr(cn)["status"] == "待審核" and _q("SELECT COUNT(*) AS n FROM vouchers_all WHERE origin LIKE 'bonus_corr%'")[0]["n"] == 0
    assert sa.inner_text('[data-testid="bc-msg"]').strip() != ""
    _shot(sa, "04-self-approve-blocked")
    # 另一位最高管理者：駁回要原因 → 駁回 → 草稿
    sa2 = _page_as(e2e_browser, live_server, u["e2c_sa2"])
    sa2.locator(f'[data-testid="bc-item-{cn}"]').click()
    sa2.locator('[data-testid="bc-reject"]').click()
    sa2.wait_for_timeout(800)
    assert _corr(cn)["status"] == "待審核"                                   # 沒填原因 ⇒ 不動
    sa2.fill('[data-testid="bc-reject-reason"]', "名單再確認")
    sa2.locator('[data-testid="bc-reject"]').click()
    sa2.wait_for_timeout(800)
    assert _corr(cn)["status"] == "草稿"
    # 再送審 → sa2 核准
    sa.reload()
    sa.locator(f'[data-testid="bc-item-{cn}"]').click()
    sa.locator('[data-testid="bc-submit"]').click()
    sa.wait_for_timeout(800)
    sa2.reload()
    sa2.locator(f'[data-testid="bc-item-{cn}"]').click()
    sa2.locator('[data-testid="bc-approve"]').click()
    sa2.wait_for_timeout(1000)
    c = _corr(cn)
    assert c["status"] == "待補發" and c["reversal_voucher_id"] and c["rebook_voucher_id"] and c["clawback_voucher_id"] == 0
    rev = _q("SELECT kind, status, origin FROM vouchers_all WHERE id=?", c["reversal_voucher_id"])[0]
    assert rev["kind"] == "reversal" and rev["status"] == "草稿"
    sa2.locator('[data-testid="bc-vouchers"]').wait_for(timeout=5000)
    assert sa2.locator('[data-testid="bc-clawback-pending"]').is_hidden()
    _shot(sa2, "05-approved-awaiting-payout")
    # 出納標記補發
    # 出納頁「獎金待發放」：更正單的補發列是連結（不在出納頁直接標記），點了落在更正單頁並開好那一張
    cp = e2e_browser.new_context().new_page()
    inject_login(cp, live_server, *u["e2c_cash"])
    cp.goto(live_server + "/pages/cashier.html")
    cp.locator('[data-testid="cashier-bonus-tab"]').wait_for(state="visible", timeout=20000)
    cp.locator('[data-testid="cashier-bonus-tab"]').click()
    link = cp.locator(f'[data-testid="cashier-bonus-corr-{cn}"]')
    link.wait_for(state="visible", timeout=15000)
    assert cp.locator(f'[data-testid="cashier-bonus-pay-{cn}"]').count() == 0 or cp.locator(f'[data-testid="cashier-bonus-pay-{cn}"]').is_hidden()
    _shot(cp, "05b-cashier-bonus-queue-link")
    link.click()
    cp.wait_for_url("**/bonus-corrections.html*", timeout=15000)
    cp.locator('[data-testid="bc-mark-paid"]').wait_for(timeout=15000)       # ?no= 直接開到該張
    cash = _page_as(e2e_browser, live_server, u["e2c_cash"])
    cash.locator(f'[data-testid="bc-item-{cn}"]').click()
    cash.locator('[data-testid="bc-mark-paid"]').wait_for(timeout=10000)
    _shot(cash, "06-cashier-payout")
    cash.locator('[data-testid="bc-mark-paid"]').click()
    cash.wait_for_timeout(1200)
    c = _corr(cn)
    assert c["status"] == "已完成" and c["paid_by"] and c["supplement_voucher_id"]
    assert cash.locator('[data-testid="bc-mark-paid"]').count() == 0
    _shot(cash, "07-completed")


@pytest.mark.e2e
def test_clawback_shows_pending_label_and_draft_can_be_cancelled(live_server, make_user, e2e_browser):
    no = "MQ-202609-932"
    u = _setup(live_server, make_user, e2e_browser, no)
    sa = _page_as(e2e_browser, live_server, u["e2c_sa"])
    sa.fill('[data-testid="bc-new-quote"]', no)
    sa.locator('[data-testid="bc-load-current"]').click()
    sa.locator('[data-testid="bc-form"]').wait_for(timeout=15000)
    sa.fill('[data-testid="bc-new-amt-e2c_s1"]', "1000")
    sa.fill('[data-testid="bc-reason"]', "業務金額多給，追回")
    assert sa.locator('[data-testid="bc-form-clawback"]').is_visible()
    sa.locator('[data-testid="bc-save"]').click()
    cn = no + "-C1"
    sa.locator(f'[data-testid="bc-item-{cn}"]').wait_for(timeout=15000)
    # 作廢草稿
    sa.locator(f'[data-testid="bc-item-{cn}"]').click()
    sa.locator('[data-testid="bc-cancel"]').click()
    sa.wait_for_timeout(800)
    assert _corr(cn)["status"] == "已作廢"
    _shot(sa, "08-draft-cancelled")
    # 重開一張（C2）→ 送審 → sa2 核准（只減少 ⇒ 核准即完成）
    sa.fill('[data-testid="bc-new-quote"]', no)
    sa.locator('[data-testid="bc-load-current"]').click()
    sa.locator('[data-testid="bc-form"]').wait_for(timeout=15000)
    sa.fill('[data-testid="bc-new-amt-e2c_s1"]', "1000")
    sa.fill('[data-testid="bc-reason"]', "業務金額多給，追回")
    sa.locator('[data-testid="bc-save"]').click()
    cn2 = no + "-C2"
    sa.locator(f'[data-testid="bc-item-{cn2}"]').wait_for(timeout=15000)
    sa.locator(f'[data-testid="bc-item-{cn2}"]').click()
    sa.locator('[data-testid="bc-submit"]').click()
    sa.wait_for_timeout(800)
    sa2 = _page_as(e2e_browser, live_server, u["e2c_sa2"])
    sa2.locator(f'[data-testid="bc-item-{cn2}"]').click()
    sa2.locator('[data-testid="bc-approve"]').click()
    sa2.wait_for_timeout(1200)
    c = _corr(cn2)
    assert c["status"] == "已完成" and c["supplement_total"] == 0 and c["clawback_total"] > 0 and c["clawback_voucher_id"]
    cb = _q("SELECT summary, origin FROM vouchers_all WHERE id=?", c["clawback_voucher_id"])[0]
    assert cb["origin"] == "bonus_corr_clawback" and "追回處理方式待確認" in cb["summary"]
    sa2.locator('[data-testid="bc-clawback-pending"]').wait_for(timeout=5000)
    assert "追回處理方式待確認" in sa2.inner_text('[data-testid="bc-clawback-pending"]')
    _shot(sa2, "09-clawback-pending-label")
