"""瀏覽器端對端：信件 × 行事曆通知矩陣（MAIL-CAL 階段 1；使用者裁示 2026-10-05；S3b 2026-11-13 起改為共用矩陣元件的草稿制）。

在 mail-settings.html 逐格操作（點格子只進草稿、頂端儲存列「儲存」才寫入），觀測點打在資料庫落地值（system_settings）：
- 業務類信件格關閉 ⇒ mail_recipient_overrides[key].off；重新開啟 ⇒ 設定消失（與升級前位元相同）
- 簽核類信件關閉要先確認（第二段警告）：取消 ⇒ 沒寫入；確認 ⇒ 寫入
- 鎖住的資安類信件格停用；沒有日期的信件沒有行事曆格
- 行事曆格 ⇒ google_calendar.events（與 Google 行事曆設定頁同一份）；副列「同上」；僅行事曆的列沒有信件格
"""
import json
import os

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect  # noqa: E402


def _setting(key):
    import db
    conn = db.get_db()
    try:
        r = conn.execute("SELECT value_json FROM system_settings WHERE key=?", (key,)).fetchone()
        return json.loads(r["value_json"]) if r else {}
    finally:
        conn.close()


def _row(page, key):
    return page.locator('[data-testid="mx-row-%s"]' % key)


def _mail(page, key):
    return _row(page, key).locator(".mx-sw")


def _cal(page, key):
    return _row(page, key).locator('[data-mx="chip"][data-col="cal"]')


def _dlg(page, text):
    return page.locator(".mx-dlg button").filter(has_text=text).last


def _save(page, second=None):
    """頂端儲存列「儲存」→ 確認視窗「儲存」；second＝要再按的第二段（簽核／系統類關閉的警告）。"""
    page.locator("[data-testid=mx-draft-save]").click()
    _dlg(page, "儲存").wait_for(state="visible", timeout=10000)
    _dlg(page, "儲存").click()
    if second:
        _dlg(page, second).wait_for(state="visible", timeout=10000)
        _dlg(page, second).click()
    expect(page.locator("[data-testid=mx-draftbar]")).to_have_count(0)


def _open(live_server, make_user, new_page, login_as, name, key):
    sa = make_user(username=name, role="superadmin")
    page = new_page(viewport={"width": 1500, "height": 1800})
    login_as(page, sa)
    page.goto(f"{live_server}/pages/mail-settings.html")
    _row(page, key).wait_for(timeout=20000)
    return page


@pytest.mark.e2e
def test_matrix_cells_write_back_to_the_existing_stores(live_server, make_user, new_page, login_as):
    page = _open(live_server, make_user, new_page, login_as, "nm_e2e_sa", "settlement_finalized")

    # 業務類：關閉 ⇒ 草稿不寫入、儲存後 off；再開 ⇒ 設定消失
    sw = _mail(page, "settlement_finalized")
    expect(sw).to_have_attribute("aria-checked", "true")
    sw.click()
    expect(sw).to_have_attribute("aria-checked", "false")
    assert "settlement_finalized" not in _setting("mail_recipient_overrides"), "草稿階段不寫入"
    _save(page)
    assert _setting("mail_recipient_overrides")["settlement_finalized"]["off"] is True
    expect(_mail(page, "settlement_finalized")).to_have_attribute("aria-checked", "false")
    _mail(page, "settlement_finalized").click()
    _save(page)
    assert "settlement_finalized" not in _setting("mail_recipient_overrides")

    # 簽核類：第二段警告——先取消（不寫入），再確認（寫入）
    _mail(page, "payment_request_submitted").click()
    page.locator("[data-testid=mx-draft-save]").click()
    _dlg(page, "儲存").click()
    _dlg(page, "仍要關閉").wait_for(state="visible", timeout=10000)
    assert "相關人員不會再收到通知" in page.locator(".mx-dlg").last.inner_text()
    _dlg(page, "取消").click()
    assert "payment_request_submitted" not in _setting("mail_recipient_overrides"), "取消確認後不可寫入"
    _save(page, second="仍要關閉")
    assert _setting("mail_recipient_overrides")["payment_request_submitted"]["off"] is True

    # 停用格：鎖住的資安類信件格；沒有日期的信件沒有行事曆格
    assert _mail(page, "backup_error").is_disabled()
    assert _cal(page, "payment_request_submitted").count() == 0 and _cal(page, "backup_error").count() == 0

    # 行事曆格：主列寫 events；副列「同上」；僅行事曆的列沒有信件格
    page.screenshot(path=os.environ["MATRIX_SHOT"]) if os.environ.get("MATRIX_SHOT") else None
    cal = _cal(page, "case_stage_deadline")
    expect(cal).to_have_attribute("aria-pressed", "true")
    cal.click()
    _save(page)
    assert _setting("google_calendar")["events"]["stage_due"] is False
    assert "同上" in _row(page, "case_stage_deadline_manager").locator('[data-testid="ms-calnote-case_stage_deadline_manager"]').inner_text()
    assert _mail(page, "cal:receipt_logged").count() == 0
    only = _cal(page, "cal:receipt_logged")
    expect(only).to_have_attribute("aria-pressed", "false")
    only.click()
    _save(page)
    assert _setting("google_calendar")["events"]["receipt_logged"] is True


@pytest.mark.e2e
def test_phase2_date_event_cells_default_off_and_write_back_together(live_server, make_user, new_page, login_as):
    """階段 2：三個新日期型事件的行事曆格——預設未勾、可勾、寫回 google_calendar.events；信件格不受影響。"""
    page = _open(live_server, make_user, new_page, login_as, "nm_e2e_p2", "warranty_expiry")
    cells = (("warranty_expiry", "warranty_expiry"), ("range_task_deadline", "range_task_due"), ("case_project_overdue", "project_end"))
    for mail, code in cells:
        cal = _cal(page, mail)
        assert cal.is_enabled() and cal.get_attribute("aria-pressed") == "false", "%s：預設要可勾且未勾" % mail
        assert _mail(page, mail).get_attribute("aria-checked") == "true", "%s：信件格不受影響" % mail
    assert not _setting("google_calendar").get("events"), "沒動任何格子 ⇒ 沒有寫入"
    for mail, code in cells:                                        # 三格一起勾、一次儲存
        _cal(page, mail).click()
    expect(page.locator("[data-testid=mx-draft-count]")).to_contain_text("3 項未儲存的修改")
    assert not _setting("google_calendar").get("events"), "草稿階段不寫入"
    _save(page)
    ev = _setting("google_calendar")["events"]
    assert all(ev[c] is True for _, c in cells)
    _cal(page, "warranty_expiry").click()                           # 再取消：回到關
    _save(page)
    assert _setting("google_calendar")["events"]["warranty_expiry"] is False
    assert "warranty_expiry" not in _setting("mail_recipient_overrides"), "行事曆格不寫信件設定"
