"""瀏覽器端對端：出納「標記已匯款」視窗的個人外包人員 ↔ 勞報單關聯（R12，使用者 2026-09-30 裁示）。

個人外包人員匯款前必須先關聯勞報單、匯款金額須等於勞報單實付：未關聯 → 畫面說出原因、確認鈕停用；挑了勞報單 → 鈕可按；
按下去 → 匯款單標已匯款、勞報單一併記為已付款（觀測點打在資料庫落地值，不打頁面文字）。
"""
from tests._requires import requires_module  # noqa: E402
import time

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

pytestmark = requires_module("subcontract", "本檔的題打 M04（外包工班）的匯款單；M04 不在時沒有對象")

QUOTE_NO = "MQ-E2E-R12-001"


def _db():
    import db
    return db.get_db()


def _seed():
    conn = _db()
    try:
        cid = conn.execute("INSERT INTO contractors(name, id_number) VALUES (?,?)", ("林外包", "C123456789")).lastrowid
        conn.execute("INSERT INTO payslips(slip_no, contractor_id, contractor_name, income_type, gross_amount, tax_withheld, nhi_supplement, "
                     "net_amount, slip_date, status, signed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     ("LB-E2E-R12-1", cid, "林外包", "9A", 10000, 1000, 211, 8789, "2176-06-10", "已簽回", "2176-06-11T00:00:00"))
        did = conn.execute("INSERT INTO contractor_dispatches(quote_no, dispatch_date, status, items_json, personnel_json, total_amount) VALUES (?,?,?,?,?,?)",
                           (QUOTE_NO, "2176-06-01", "completed", "[]",
                            '[{"id": %d, "name": "林外包", "amount": 8789}]' % cid, 0)).lastrowid
        conn.execute("INSERT INTO contractor_payment_vouchers(voucher_no, dispatch_id, quote_no, status, snapshot_json) VALUES (?,?,?,?,?)",
                     ("PV-E2E-R12-1", did, QUOTE_NO, "已核准",
                      '{"vendorName": "", "grandTotal": 8789, "personnelTotal": 8789, "personnel": [{"id": %d, "name": "林外包", "amount": 8789}]}' % cid))
        conn.commit()
        return cid
    finally:
        conn.close()


def _state():
    conn = _db()
    try:
        v = conn.execute("SELECT is_paid FROM contractor_payment_vouchers WHERE voucher_no='PV-E2E-R12-1'").fetchone()[0]
        s = conn.execute("SELECT status FROM payslips WHERE slip_no='LB-E2E-R12-1'").fetchone()[0]
        return v, s
    finally:
        conn.close()


@pytest.mark.e2e
def test_pay_modal_requires_payslip_link_then_marks_both_paid(live_server, make_user, e2e_browser):
    username, password = make_user(username="e2e_r12", role="superadmin")
    cid = _seed()
    page = e2e_browser.new_page()
    inject_login(page, live_server, username, password)
    page.goto(f"{live_server}/pages/cashier.html")
    row = page.locator("tr", has=page.locator("td.mono", has_text="PV-E2E-R12-1"))
    row.locator("button.action-btn.pay").click()

    panel = page.locator('[data-testid="pay-links"]')
    panel.wait_for(state="visible")
    err = page.locator(f'[data-testid="pay-link-error-{cid}"]')
    err.wait_for(state="visible")
    assert "尚未關聯" in err.inner_text()
    confirm = page.locator(r'button[\@click^="confirmPayVoucher"]')         # 頁面另有『銀行帳戶標記已匯款』同名按鈕，用 @click 區分
    page.fill('[data-testid="pay-date"]', "2176-06-20")
    assert confirm.is_disabled(), "未關聯勞報單時不可以按確認"

    page.select_option(f'[data-testid="pay-link-select-{cid}"]', "LB-E2E-R12-1")
    for _ in range(100):                                     # 等關聯寫入後重讀的終點：錯誤訊息消失、按鈕可按
        if not err.is_visible() and confirm.is_enabled():
            break
        time.sleep(0.1)
    assert confirm.is_enabled() and not err.is_visible()
    assert _state() == (0, "已簽回")                          # 只是關聯，還沒匯款

    confirm.click()
    for _ in range(100):
        if _state()[0] == 1:
            break
        page.wait_for_timeout(100)
    assert _state() == (1, "已付款"), "匯款成功時勞報單要一併記為已付款"
