"""瀏覽器端對端：設定中心可編輯（S1，2026-10-13）。

- 收緊的設定：改值→預覽顯示『立即生效』→填原因→儲存→落地（定義新版本＋變更明細）
- 放寬的設定：顯示紅色橫幅、需勾『我已了解』才能儲存→列入待生效；第二位最高管理者在『待生效』頁核准
- 還原預設按鈕、畫面不出現內部鍵名、手機寬度不橫向捲動
觀測點打在資料庫落地值與元件狀態，不打在頁面寫死的文字上（文字只驗不出現鍵名）。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402


def _q(sql, args=()):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


def _open(page, live_server, group):
    page.goto(f"{live_server}/pages/settings-center.html")
    page.locator(f'[data-testid="sc-group-{group}"]').wait_for(timeout=20000)
    page.locator(f'[data-testid="sc-group-{group}"]').click()


@pytest.mark.e2e
def test_tightening_saves_immediately(live_server, make_user, e2e_browser):
    sa = make_user(username="sc_e2e_a", role="superadmin")
    page = e2e_browser.new_page()
    inject_login(page, live_server, *sa)
    _open(page, live_server, "uploads")
    box = page.locator('[data-testid="sc-input-max_file_mb"]')
    box.wait_for(timeout=15000)
    box.fill("10")                                            # 20 → 10：收緊
    page.locator('[data-testid="sc-kind-max_file_mb"]').wait_for(timeout=10000)
    assert "立即生效" in page.locator('[data-testid="sc-kind-max_file_mb"]').inner_text()
    assert page.is_disabled('[data-testid="sc-save"]')       # 還沒填原因
    page.fill('[data-testid="sc-reason"]', "測試收緊")
    page.wait_for_function("() => !document.querySelector('[data-testid=\"sc-save\"]').disabled", timeout=10000)
    page.click('[data-testid="sc-save"]')
    page.locator('[data-testid="sc-msg"]').wait_for(timeout=15000)
    assert "已儲存並立即生效" in page.locator('[data-testid="sc-msg"]').inner_text()
    rows = _q("SELECT body_json FROM ui_definitions WHERE kind='setting_group' AND key='uploads' AND status='published' ORDER BY version DESC")
    assert json.loads(rows[0]["body_json"])["values"]["max_file_mb"] == 10
    ch = _q("SELECT field, reason FROM config_changes WHERE domain='setting:uploads'")
    assert [(c["field"], c["reason"]) for c in ch] == [("max_file_mb", "測試收緊")]
    page.locator('[data-testid="sc-nondefault-max_file_mb"]').wait_for(timeout=10000)      # 重新載入後：目前不是系統預設


@pytest.mark.e2e
def test_loosening_needs_ack_then_second_superadmin_approves(live_server, make_user, e2e_browser):
    a = make_user(username="sc_e2e_b", role="superadmin")
    b = make_user(username="sc_e2e_c", role="superadmin")
    page = e2e_browser.new_page()
    inject_login(page, live_server, *a)
    _open(page, live_server, "retention")
    box = page.locator('[data-testid="sc-input-audit_log_keep_days"]')
    box.wait_for(timeout=15000)
    box.fill("400")                                           # 縮短保存期限＝放寬
    banner = page.locator('[data-testid="sc-banner-audit_log_keep_days"]')
    banner.wait_for(timeout=10000)
    assert "sc-banner--red" in (banner.get_attribute("class") or "")
    assert "需另一位最高管理者核准" in page.locator('[data-testid="sc-kind-audit_log_keep_days"]').inner_text()
    page.fill('[data-testid="sc-reason"]', "測試放寬")
    assert page.is_disabled('[data-testid="sc-save"]')       # 紅色橫幅：沒勾『我已了解』不可送出
    page.check('[data-testid="sc-ack"]')
    page.wait_for_function("() => !document.querySelector('[data-testid=\"sc-save\"]').disabled", timeout=10000)
    page.click('[data-testid="sc-save"]')
    page.locator('[data-testid="sc-msg"]').wait_for(timeout=15000)
    assert "待生效" in page.locator('[data-testid="sc-msg"]').inner_text()
    pend = _q("SELECT id, approvals_required FROM config_changes WHERE domain='setting:retention' AND field='audit_log_keep_days'")
    assert len(pend) == 1 and pend[0]["approvals_required"] == 1
    assert not _q("SELECT 1 FROM ui_definitions WHERE kind='setting_group' AND key='retention'")            # 放寬沒有直接生效

    page2 = e2e_browser.new_page()                            # 第二位最高管理者
    inject_login(page2, live_server, *b)
    page2.goto(f"{live_server}/pages/settings-center.html")
    page2.locator('[data-testid="sc-tab-pending"]').wait_for(timeout=20000)
    page2.click('[data-testid="sc-tab-pending"]')
    btn = page2.locator('[data-testid="sc-approve-%d"]' % pend[0]["id"])
    btn.wait_for(timeout=15000)
    btn.click()
    page2.locator('[data-testid="sc-msg"]').wait_for(timeout=15000)
    assert "已核准" in page2.locator('[data-testid="sc-msg"]').inner_text()
    ev = _q("SELECT event FROM config_change_events WHERE change_id=? ORDER BY id", (pend[0]["id"],))
    assert [e["event"] for e in ev] == ["pending", "approved"]


@pytest.mark.e2e
def test_reset_button_clears_the_draft_and_no_internal_keys_are_shown(live_server, make_user, e2e_browser):
    sa = make_user(username="sc_e2e_d", role="superadmin")
    page = e2e_browser.new_page()
    inject_login(page, live_server, *sa)
    _open(page, live_server, "uploads")
    box = page.locator('[data-testid="sc-input-max_file_mb"]')
    box.wait_for(timeout=15000)
    box.fill("10")
    page.locator('[data-testid="sc-bar"]').wait_for(timeout=10000)
    page.click('[data-testid="sc-reset-max_file_mb"]')        # 還原預設 ⇒ 草稿消失
    page.wait_for_function("() => !document.querySelector('[data-testid=\"sc-bar\"]').offsetParent", timeout=10000)
    text = page.inner_text("main")
    for key in ("max_file_mb", "audit_log_keep_days", "confirm_period_days", "show_denied", "pending_approval", "immediate"):
        assert key not in text
    # 手機寬度不橫向捲動
    page.set_viewport_size({"width": 390, "height": 800})
    page.wait_for_timeout(300)
    assert page.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")


@pytest.mark.e2e
def test_choice_field_shows_each_options_impact_and_blocks_other_groups_while_dirty(live_server, make_user, e2e_browser):
    sa = make_user(username="sc_e2e_e", role="superadmin")
    page = e2e_browser.new_page()
    inject_login(page, live_server, *sa)
    _open(page, live_server, "system_hub")
    page.locator('[data-testid="sc-choice-show_denied-1"]').wait_for(timeout=15000)
    page.check('[data-testid="sc-choice-show_denied-1"]')     # 選了較寬鬆的選項
    banner = page.locator('[data-testid="sc-banner-show_denied"]')
    banner.wait_for(timeout=10000)
    assert "sc-banner--red" in (banner.get_attribute("class") or "")
    page.click('[data-testid="sc-group-uploads"]')            # 有未儲存的修改 ⇒ 不能切走
    page.locator('[data-testid="sc-err"]').wait_for(timeout=10000)
    assert "尚未儲存" in page.locator('[data-testid="sc-err"]').inner_text()
    page.click('[data-testid="sc-discard"]')
    page.click('[data-testid="sc-group-uploads"]')
    page.locator('[data-testid="sc-input-max_file_mb"]').wait_for(timeout=10000)
