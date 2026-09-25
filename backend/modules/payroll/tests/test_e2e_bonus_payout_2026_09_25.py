"""瀏覽器端對端：獎金分潤送交出納＋U4 投保金額（CORE-SPEC「使用者裁示」獎金分潤，2026-09-25）。

- 出納：出納頁「獎金待發放」→ 標記已發放（打獎金那一支 API）→ 資料庫已發放、離開清單、進執行歷史
- 財務：出納頁看不到獎金子頁籤
- 最高管理者：獎金頁「投保金額與全年累計」存檔 ⇒ 設定落地
觀測點打在資料庫落地值，不打在頁面寫死的文字上。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from modules.payroll.tests._bonus_insure import insure_all  # noqa: E402

NO = "MQ-E2EBP-001"
CASHIER_JS = "Alpine.$data(document.querySelector('[x-data]'))"


def _q(sql, args=()):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


def _seed_payout(client, u):
    import db
    data = {"dealTag": "已結案", "caseRecord": {"roles": {"executor": ""}},
            "settlement": {"status": "finalized", "summary": {"netProfit": 100000}}}
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at,"
            " updated_at, deal_tag, sales_person, sales_person_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (NO, "已送出", "出納客戶", "出納專案", json.dumps(data, ensure_ascii=False),
             "2026-09-01", "2026-09-01", "已結案", "", None))
        conn.commit()
    finally:
        conn.close()

    def tok(user):
        r = client.post("/api/auth/login", json={"username": user[0], "password": user[1]})
        assert r.status_code == 200, r.text
        return {"Authorization": "Bearer " + r.json()["token"]}
    sa, sa2 = tok(u["bp_sa"]), tok(u["bp_sa2"])
    r = client.post(f"/api/bonus/cases/{NO}", headers=sa,
                    json={"members": {"sales": [{"username": "bp_m1"}], "project": [], "admin": []}})
    assert r.status_code == 200, r.text
    assert client.post(f"/api/bonus/cases/{NO}/submit", headers=sa).status_code == 200
    r = client.post(f"/api/bonus/cases/{NO}/approve", headers=sa2)
    assert r.json()["status"] == "待發放", r.text


def _users(make_user):
    out = {}
    for u, role, mods in (("bp_sa", "superadmin", None), ("bp_sa2", "superadmin", None),
                          ("bp_m1", "sales", None), ("bp_cash", "engineer", ["cashier"]),
                          ("bp_fin", "engineer", ["finance"])):
        out[u] = make_user(username=u, role=role, modules=mods)
    return out


@pytest.mark.e2e
def test_cashier_marks_bonus_paid_from_cashier_page(client, live_server, make_user, e2e_browser):
    u = _users(make_user)
    _seed_payout(client, u)
    insure_all()
    page = e2e_browser.new_page()
    inject_login(page, live_server, *u["bp_cash"])
    page.goto(f"{live_server}/pages/cashier.html")
    tab = page.locator('[data-testid="cashier-bonus-tab"]')
    tab.wait_for(state="visible", timeout=20000)
    tab.click()
    page.locator(f'[data-testid="cashier-bonus-pay-{NO}"]').click()
    page.locator('[data-testid="cashier-bonus-modal"] table tbody tr').first.wait_for(timeout=15000)
    # 扣繳與補充保費已依撥付日的法規參數試算：顯示版本與參數；沒有拒絕訊息
    page.locator('[data-testid="cashier-bonus-ded-params"]').wait_for(state="visible", timeout=15000)
    assert "法規參數" in page.inner_text('[data-testid="cashier-bonus-ded-params"]')
    assert not page.locator('[data-testid="cashier-bonus-deduction-notice"]').is_visible()
    page.locator('[data-testid="cashier-bonus-confirm"]').click()
    page.wait_for_function(f"() => !{CASHIER_JS}.bonusPay.show && !{CASHIER_JS}.bonusPay.saving", timeout=15000)
    a = _q("SELECT status, paid_by FROM bonus_case_awards WHERE quote_no=?", (NO,))[0]
    assert a == {"status": "已發放", "paid_by": "bp_cash"}
    snap = _q("SELECT changes_json FROM bonus_case_award_edit_log WHERE action='mark_paid' ORDER BY id DESC LIMIT 1")
    assert json.loads(snap[0]["changes_json"])["deductions"]["rules"]["version"]      # 版本快照落地
    page.wait_for_function(
        f"() => {CASHIER_JS}.bonusQueue.items.every(i => i.quoteNo !== '{NO}')"
        f" && {CASHIER_JS}.cashierHistoryBonus.some(b => b.quoteNo === '{NO}')", timeout=15000)


@pytest.mark.e2e
def test_finance_does_not_see_bonus_tab(client, live_server, make_user, e2e_browser):
    u = _users(make_user)
    _seed_payout(client, u)
    page = e2e_browser.new_page()
    inject_login(page, live_server, *u["bp_fin"])
    page.goto(f"{live_server}/pages/cashier.html")
    page.wait_for_function(f"() => {CASHIER_JS}.ready === true", timeout=20000)
    page.wait_for_function(f"() => {CASHIER_JS}.cashierLoaded === true", timeout=20000)
    assert not page.locator('[data-testid="cashier-bonus-tab"]').is_visible()
    assert page.evaluate(f"() => {CASHIER_JS}.bonusQueue.items.length") == 0


@pytest.mark.e2e
def test_superadmin_sets_insured_amount_in_bonus_page(client, live_server, make_user, e2e_browser):
    u = _users(make_user)
    page = e2e_browser.new_page()
    inject_login(page, live_server, *u["bp_sa"])
    page.goto(f"{live_server}/pages/bonus.html")
    page.locator('[data-testid="bn-insurance-open"]').click()
    page.locator('[data-testid="bn-ins-amount-bp_m1"]').wait_for(timeout=15000)
    page.fill('[data-testid="bn-ins-amount-bp_m1"]', "45800")
    page.fill('[data-testid="bn-ins-ext-bp_m1"]', "12000")
    page.locator('[data-testid="bn-ins-save-bp_m1"]').click()
    page.wait_for_function(
        "() => Alpine.$data(document.querySelector('[x-data]')).msg.startsWith('已儲存')", timeout=15000)
    prof = json.loads(_q("SELECT value_json FROM system_settings WHERE key='payroll_insurance_profiles'")[0][
        "value_json"])
    from datetime import date
    assert prof["bp_m1"] == {"insuredAmount": 45800, "ytdExternal": {str(date.today().year): 12000}}
    page.wait_for_function(
        "() => Alpine.$data(document.querySelector('[x-data]')).insurance"
        ".some(i => i.username === 'bp_m1' && i.ytdTotal === 12000)", timeout=15000)
