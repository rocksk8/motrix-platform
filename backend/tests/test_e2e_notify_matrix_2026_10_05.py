"""瀏覽器端對端：信件 × 行事曆通知矩陣（MAIL-CAL 階段 1；使用者裁示 2026-10-05）。

在 mail-settings.html 逐格操作，觀測點打在資料庫落地值（system_settings）與元件狀態：
- 業務類信件格取消勾選 ⇒ mail_recipient_overrides[key].off；重新勾選 ⇒ 設定消失（與升級前位元相同）
- 簽核類信件格取消勾選要先確認：取消確認 ⇒ 勾選還原、沒寫入；確認 ⇒ 寫入
- 鎖住的資安類信件格停用；沒有日期的行事曆格停用
- 行事曆格 ⇒ google_calendar.events（與 Google 行事曆設定頁同一份）；副列「同上」；僅行事曆的列信件格停用
"""
import json
import os

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

DATA = "Alpine.$data(document.querySelector('[x-data]'))"


def _setting(key):
    import db
    conn = db.get_db()
    try:
        r = conn.execute("SELECT value_json FROM system_settings WHERE key=?", (key,)).fetchone()
        return json.loads(r["value_json"]) if r else {}
    finally:
        conn.close()


def _tid(page, tid):
    return page.locator('[data-testid="%s"]' % tid)


@pytest.mark.e2e
def test_matrix_cells_write_back_to_the_existing_stores(live_server, make_user, e2e_browser):
    sa = make_user(username="nm_e2e_sa", role="superadmin")
    page = e2e_browser.new_page(viewport={"width": 1500, "height": 900})
    inject_login(page, live_server, *sa)
    page.goto(f"{live_server}/pages/mail-settings.html")
    _tid(page, "ms-row-settlement_finalized").wait_for(timeout=20000)

    # 業務類：取消勾選 ⇒ off；再勾選 ⇒ 設定消失
    box = _tid(page, "ms-mail-settlement_finalized")
    assert box.is_checked() and box.is_enabled()
    box.click()
    page.wait_for_function(f"() => {DATA}.items.find(t => t.key === 'settlement_finalized').mailOff === true", timeout=15000)
    assert _setting("mail_recipient_overrides")["settlement_finalized"]["off"] is True and not box.is_checked()
    _tid(page, "ms-off-settlement_finalized").wait_for(state="visible", timeout=5000)
    box.click()
    page.wait_for_function(f"() => {DATA}.items.find(t => t.key === 'settlement_finalized').mailOff === false", timeout=15000)
    assert "settlement_finalized" not in _setting("mail_recipient_overrides") and box.is_checked()

    # 簽核類：確認警告——先取消（不寫入、勾選還原），再確認（寫入）
    box = _tid(page, "ms-mail-payment_request_submitted")
    seen = []
    page.once("dialog", lambda d: (seen.append(d.message), d.dismiss()))
    box.click()
    page.wait_for_timeout(600)
    assert seen and "payment_request_submitted" not in _setting("mail_recipient_overrides") and box.is_checked(), "取消確認後不可寫入、勾選要還原"
    page.once("dialog", lambda d: (seen.append(d.message), d.accept()))
    box.click()
    page.wait_for_function(f"() => {DATA}.items.find(t => t.key === 'payment_request_submitted').mailOff === true", timeout=15000)
    assert _setting("mail_recipient_overrides")["payment_request_submitted"]["off"] is True and "簽核" in seen[-1]

    # 停用格：鎖住的資安類信件格、沒有日期的行事曆格
    locked = _tid(page, "ms-mail-backup_error")
    assert locked.is_disabled() and locked.is_checked()
    assert _tid(page, "ms-cal-payment_request_submitted").is_disabled() and _tid(page, "ms-cal-backup_error").is_disabled()

    # 行事曆格：主列寫 events；副列「同上」；停用的信件格（僅行事曆列）
    page.screenshot(path=os.environ["MATRIX_SHOT"]) if os.environ.get("MATRIX_SHOT") else None
    cal = _tid(page, "ms-cal-case_stage_deadline")
    assert cal.is_checked()
    cal.click()
    page.wait_for_function(f"() => {DATA}.items.find(t => t.key === 'case_stage_deadline_manager').calendar.enabled === false", timeout=15000)
    assert _setting("google_calendar")["events"]["stage_due"] is False
    assert "同上" in _tid(page, "ms-cal-case_stage_deadline_manager").inner_text()
    assert _tid(page, "ms-mail-cal:receipt_logged").evaluate("e => e.tagName") == "SPAN"
    only = _tid(page, "ms-cal-cal:receipt_logged")
    assert not only.is_checked()
    only.click()
    page.wait_for_function(f"() => {DATA}.items.find(t => t.key === 'cal:receipt_logged').calendar.enabled === true", timeout=15000)
    assert _setting("google_calendar")["events"]["receipt_logged"] is True
