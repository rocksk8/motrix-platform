"""瀏覽器端對端：信件與通知收件設定（CORE-SPEC「使用者裁示」信件與通知的收件人、用語，2026-09-26）。

- 超級管理員在「信件與通知收件設定」把一種信改成指定角色 ⇒ 設定落地
- 使用者管理：一般管理員的退訂清單裡，系統技術類不能勾選（收不到的類型不能把自己加進去）
觀測點打在資料庫落地值與元件狀態，不打在頁面寫死的文字上。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

DATA = "Alpine.$data(document.querySelector('[x-data]'))"


def _q(sql, args=()):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


@pytest.mark.e2e
def test_superadmin_sets_recipients_in_page(live_server, make_user, e2e_browser):
    sa = make_user(username="ms_e2e_sa", role="superadmin")
    page = e2e_browser.new_page()
    inject_login(page, live_server, *sa)
    page.goto(f"{live_server}/pages/mail-settings.html")
    page.locator('[data-testid="ms-mode-settlement_finalized"]').wait_for(timeout=20000)
    page.select_option('[data-testid="ms-mode-settlement_finalized"]', "custom")
    page.locator('[data-testid="ms-role-settlement_finalized-engineer"]').click()
    page.locator('[data-testid="ms-save-settlement_finalized"]').click()
    page.wait_for_function(
        f"() => {DATA}.items.find(t => t.key === 'settlement_finalized').okMsg === '已儲存'", timeout=15000)
    rows = _q("SELECT value_json FROM system_settings WHERE key='mail_recipient_overrides'")
    assert json.loads(rows[0]["value_json"])["settlement_finalized"] == {
        "mode": "custom", "users": [], "roles": ["engineer"]}


@pytest.mark.e2e
def test_admin_cannot_tick_a_system_type(live_server, make_user, e2e_browser):
    sa = make_user(username="ms_e2e_sa2", role="superadmin")
    make_user(username="ms_e2e_adm", role="admin")
    uid = _q("SELECT id FROM users WHERE username='ms_e2e_adm'")[0]["id"]
    page = e2e_browser.new_page()
    inject_login(page, live_server, *sa)
    page.goto(f"{live_server}/pages/users.html")
    page.wait_for_function(f"() => {DATA}.users && {DATA}.users.length > 0", timeout=20000)
    page.evaluate(f"() => {DATA}.openEdit({DATA}.users.find(u => u.id === {uid}))")
    page.wait_for_function(f"() => {DATA}.allNotifyTypes.some(t => t.key === 'backup_stale')", timeout=15000)
    types = page.evaluate(f"() => Object.fromEntries({DATA}.allNotifyTypes.map(t => [t.key, t.receivable]))")
    assert types["backup_stale"] is False and types["settlement_finalized"] is True
    for g in page.evaluate(f"() => {DATA}.notifyGroups.map(g => g.group)"):
        page.evaluate(f"(g) => {{ {DATA}._notifyGroupOpen[g] = true }}", g)
    box = page.locator('[data-testid="notify-type-backup_stale"] input[type=checkbox]')
    box.wait_for(state="visible", timeout=10000)
    assert box.is_disabled() and not box.is_checked()
