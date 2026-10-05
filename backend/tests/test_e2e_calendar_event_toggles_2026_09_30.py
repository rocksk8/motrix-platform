"""瀏覽器端對端：Google 行事曆設定頁的「事件種類」開關（2026-09-30 使用者裁示「行事曆推送可選」）。

- 最高管理者開頁 ⇒ 16 種事件逐一列出、勾選狀態＝預設（既有 9 種開、新 7 種關）
- 勾「案件更新」、關「開票申請憑據已核准」按儲存 ⇒ 設定落地、各記一筆稽核；重新整理後勾選狀態照存的值
觀測點打在 DOM 的 checkbox 狀態與資料庫落地值，不打 Alpine 模型。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

EXISTING = {"invoice_voucher", "payment_request", "shipping_note", "quotation_won", "stage_due", "stage_done",
            "important_comment", "dev_case_converted", "dev_case_stale"}
NEW = {"case_update", "dev_case_update", "contractor_payout", "expense_payout", "receipt_logged", "receivable_due", "payable_due"}


def _q(sql, args=()):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


def _checked(page):
    page.locator("[data-gc-event-input]").first.wait_for(timeout=20000)
    return page.evaluate("() => Object.fromEntries([...document.querySelectorAll('[data-gc-event-input]')]"
                         ".map(i => [i.getAttribute('data-gc-event-input'), i.checked]))")


@pytest.mark.e2e
def test_superadmin_toggles_event_types_and_they_persist(live_server, make_user, e2e_browser):
    sa = make_user(username="gce2e_sa", role="superadmin")
    page = e2e_browser.new_page()
    inject_login(page, live_server, *sa)
    page.goto(f"{live_server}/pages/google-calendar-settings.html")
    page.wait_for_function("() => document.querySelectorAll('[data-gc-event-input]').length === 16", timeout=20000)
    got = _checked(page)
    assert {c for c, v in got.items() if v} == EXISTING
    assert {c for c, v in got.items() if not v} == NEW

    page.locator('[data-gc-event-input="case_update"]').check()
    page.locator('[data-gc-event-input="invoice_voucher"]').uncheck()
    page.locator("#gc-events-save").click()
    page.wait_for_function("() => (document.querySelector('#gc-events-msg').textContent || '').includes('已儲存')",
                           timeout=15000)

    cfg = json.loads(_q("SELECT value_json FROM system_settings WHERE key='google_calendar'")[0]["value_json"])
    assert cfg["events"]["case_update"] is True and cfg["events"]["invoice_voucher"] is False
    audits = _q("SELECT username, detail FROM audit_log WHERE action='settings.google_calendar.event_toggle'")
    assert sorted(json.loads(a["detail"])["event"] for a in audits) == ["case_update", "invoice_voucher"]
    assert {a["username"] for a in audits} == {"gce2e_sa"}

    page.reload()
    page.wait_for_function("() => document.querySelectorAll('[data-gc-event-input]').length === 16", timeout=20000)
    page.wait_for_function("() => document.querySelector('[data-gc-event-input=\"case_update\"]').checked", timeout=15000)
    got = _checked(page)
    assert got["case_update"] is True and got["invoice_voucher"] is False and got["payment_request"] is True
