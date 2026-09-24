"""瀏覽器端對端：獎金分潤頁的傳票草稿（SPEC-BONUS §11.8）。

- 出納：待發放時選付款銀行 → 標記已發放 ⇒ 支出傳票草稿的貸方＝選的科目；畫面寫出傳票號、列出已產生的傳票
- 最高管理者：傳票科目設定——不存在的代號存不進去、畫面說得出原因；存成功後生效
- 退回：已送審的傳票不動，畫面把後端的提示寫出來
觀測點打在資料庫落地值與後端回應驅動的畫面。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_e2e_bonus_case_page_2026_09_24 import (  # noqa: F401
    _login, _users, _award, NO, DATA_JS)


def _db():
    import db
    return db.get_db()


def _to_payout(page, base, u):
    def api_login(name):
        r = page.request.post(f"{base}/api/auth/login", data={"username": name, "password": u[name][1]})
        return {"Authorization": "Bearer " + r.json()["token"]}
    sa, sa2 = api_login("pg_sa"), api_login("pg_sa2")
    assert page.request.post(f"{base}/api/bonus/cases/{NO}", headers=sa,
                             data={"members": {"sales": [{"username": "pg_sales"}],
                                               "project": [{"username": "pg_exec"}],
                                               "admin": [{"username": "pg_admin"}]}}).ok
    assert page.request.post(f"{base}/api/bonus/cases/{NO}/submit", headers=sa).ok
    assert page.request.post(f"{base}/api/bonus/cases/{NO}/approve", headers=sa2).ok


def _bank_config():
    conn = _db()
    try:
        conn.execute("INSERT OR IGNORE INTO account_items (code, level, name, parent_code, source, is_active)"
                     " VALUES ('11138', 4, '頁面測試銀行', '111', 'custom', 1)")
        conn.execute(
            "INSERT INTO system_settings (key, value_json, updated_at) VALUES ('t100_export_config', ?, 't')"
            " ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
            (json.dumps({"bankAccounts": [{"name": "頁面測試銀行", "acctCode": "11138"}]}),))
        conn.commit()
    finally:
        conn.close()


@pytest.mark.e2e
def test_cashier_picks_the_bank_and_sees_the_voucher(live_server, make_user, e2e_browser):
    u = _users(make_user)
    _bank_config()
    browser = e2e_browser
    page = browser.new_context().new_page()
    _to_payout(page, live_server, u)
    _login(page, live_server, *u["pg_cash"])   # 非 admin 的出納
    page.goto(f"{live_server}/pages/bonus.html?q={NO}")
    sel = page.locator('[data-testid="bn-pay-bank"]')
    sel.wait_for(timeout=20000)
    sel.select_option("11138")
    page.locator('[data-testid="bn-mark-paid"]').click()
    page.wait_for_function(f"() => ({DATA_JS}.msg || '').startsWith('已標記發放')", timeout=15000)
    a, _ = _award()
    conn = _db()
    try:
        v = conn.execute("SELECT voucher_no FROM vouchers_all WHERE id=?", (a["payment_voucher_id"],)).fetchone()
        credit = conn.execute("SELECT account_code FROM voucher_lines WHERE voucher_id=? AND line_no=2",
                              (a["payment_voucher_id"],)).fetchone()[0]
    finally:
        conn.close()
    assert credit == "11138", "支出傳票草稿的貸方要是出納選的銀行"
    assert v["voucher_no"] in page.evaluate(f"() => {DATA_JS}.msg")
    card = page.locator('[data-testid="bn-vouchers"]')
    card.wait_for(timeout=10000)
    assert v["voucher_no"] in card.inner_text()


@pytest.mark.e2e
def test_superadmin_voucher_account_settings_refuse_bad_codes(live_server, make_user, e2e_browser):
    u = _users(make_user)
    browser = e2e_browser
    page = browser.new_context().new_page()
    _login(page, live_server, *u["pg_sa"])
    page.goto(f"{live_server}/pages/bonus.html")
    page.locator('button:has-text("預設比例設定")').click()
    box = page.locator('[data-testid="bn-acct-payable"]')
    box.wait_for(timeout=20000)
    assert box.input_value() == "2191"
    box.fill("99999")
    page.locator('[data-testid="bn-acct-save"]').click()
    page.wait_for_function(f"() => ({DATA_JS}.msg || '').includes('99999')", timeout=10000)
    conn = _db()
    try:
        row = conn.execute("SELECT value_json FROM system_settings"
                           " WHERE key='bonus_case_voucher_payable_code'").fetchone()
    finally:
        conn.close()
    assert row is None, "不存在的科目不可以存進去"


@pytest.mark.e2e
def test_return_shows_the_notice_when_the_voucher_was_already_submitted(live_server, make_user, e2e_browser):
    u = _users(make_user)
    browser = e2e_browser
    page = browser.new_context().new_page()
    _to_payout(page, live_server, u)
    a, _ = _award()
    conn = _db()
    try:
        conn.execute("UPDATE vouchers_all SET status='待審核' WHERE id=?", (a["accrual_voucher_id"],))
        no = conn.execute("SELECT voucher_no FROM vouchers_all WHERE id=?", (a["accrual_voucher_id"],)).fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    _login(page, live_server, *u["pg_sa"])
    page.goto(f"{live_server}/pages/bonus.html?q={NO}")
    reason = page.locator('[data-testid="bn-return-reason"]')
    reason.wait_for(timeout=20000)
    reason.fill("比例要調")
    page.locator('[data-testid="bn-return"]').click()
    page.wait_for_function(f"() => ({DATA_JS}.msg || '').startsWith('已退回草稿')", timeout=15000)
    msg = page.inner_text('[data-testid="bn-msg"]')
    assert no in msg and "不會自動作廢" in msg
