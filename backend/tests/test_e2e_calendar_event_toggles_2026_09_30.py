"""瀏覽器端對端：Google 行事曆設定頁的「事件種類」（2026-09-30 使用者裁示「行事曆推送可選」；2026-11-13 S3b 起開關搬到信件矩陣）。

- 最高管理者開頁 ⇒ 19 種事件逐一列出「目前狀態」（唯讀：沒有勾選框、沒有儲存鈕）；預設＝既有 9 種開、其餘 10 種關
- 頁面上有連到 mail-settings.html 的連結（事件開關改在信件矩陣的「行事曆」欄）
- 在信件矩陣的草稿儲存把「案件更新」打開、「開票申請憑據已核准」那一列的行事曆關掉 ⇒ 設定落地、各記一筆行事曆稽核；
  行事曆設定頁重新整理後顯示新狀態（同一份資料）
觀測點打在 DOM 的狀態屬性與資料庫落地值，不打 Alpine 模型。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect  # noqa: E402

EXISTING = {"invoice_voucher", "payment_request", "shipping_note", "quotation_won", "stage_due", "stage_done",
            "important_comment", "dev_case_converted", "dev_case_stale"}
NEW = {"case_update", "dev_case_update", "contractor_payout", "expense_payout", "receipt_logged", "receivable_due", "payable_due",
       "warranty_expiry", "range_task_due", "project_end"}


def _q(sql, args=()):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


def _states(page):
    page.locator("[data-gc-event-state]").first.wait_for(timeout=20000)
    return page.evaluate("() => Object.fromEntries([...document.querySelectorAll('[data-gc-event-state]')]"
                         ".map(i => [i.getAttribute('data-gc-event-state'), i.getAttribute('data-on') === '1']))")


@pytest.mark.e2e
def test_event_types_are_read_only_here_and_change_from_the_mail_matrix(live_server, make_user, new_page, login_as):
    sa = make_user(username="gce2e_sa", role="superadmin")
    page = new_page(viewport={"width": 1500, "height": 1800})
    login_as(page, sa)
    page.goto(f"{live_server}/pages/google-calendar-settings.html")
    page.wait_for_function("() => document.querySelectorAll('[data-gc-event-state]').length === 19", timeout=20000)
    got = _states(page)
    assert {c for c, v in got.items() if v} == EXISTING
    assert {c for c, v in got.items() if not v} == NEW
    assert page.locator("[data-gc-event-input]").count() == 0 and page.locator("#gc-events-save").count() == 0
    assert page.locator('[data-testid="gc-events-link"]').get_attribute("href") == "mail-settings.html"

    # 信件矩陣：行事曆欄兩格各切一次 → 儲存
    page.goto(f"{live_server}/pages/mail-settings.html")
    page.locator('[data-testid="mx-row-cal:case_update"]').wait_for(timeout=20000)
    page.locator('[data-testid="mx-row-cal:case_update"] [data-mx="chip"][data-col="cal"]').click()
    page.locator('[data-testid="mx-row-invoice_voucher_approved"] [data-mx="chip"][data-col="cal"]').click()
    page.locator("[data-testid=mx-draft-save]").click()
    page.locator(".mx-dlg button").filter(has_text="儲存").last.click()
    expect(page.locator("[data-testid=mx-draftbar]")).to_have_count(0)

    cfg = json.loads(_q("SELECT value_json FROM system_settings WHERE key='google_calendar'")[0]["value_json"])
    assert cfg["events"]["case_update"] is True and cfg["events"]["invoice_voucher"] is False
    audits = _q("SELECT username, detail FROM audit_log WHERE action='settings.google_calendar.event_toggle'")
    assert sorted(json.loads(a["detail"])["event"] for a in audits) == ["case_update", "invoice_voucher"]
    assert {a["username"] for a in audits} == {"gce2e_sa"}

    page.goto(f"{live_server}/pages/google-calendar-settings.html")
    page.wait_for_function("() => document.querySelectorAll('[data-gc-event-state]').length === 19", timeout=20000)
    page.wait_for_function("() => document.querySelector('[data-gc-event-state=\"case_update\"]').getAttribute('data-on') === '1'", timeout=15000)
    got = _states(page)
    assert got["case_update"] is True and got["invoice_voucher"] is False and got["payment_request"] is True
