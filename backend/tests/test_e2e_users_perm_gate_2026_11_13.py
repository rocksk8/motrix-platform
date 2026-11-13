"""瀏覽器端對端：使用者管理編輯視窗，個人勾選動到高敏感權限鍵時要填原因（安全票 fix/user-perm-sensitive-gate）。

- 勾（或取消）高敏感鍵 ⇒ 原因欄出現、缺原因存檔被擋、資料庫沒有任何變更；填原因 ⇒ 存檔成功、`permission_changes` 有一列；
- 勾一般鍵 ⇒ 沒有原因欄、存檔照舊、不寫 `permission_changes`。
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


def _open_edit(page, live_server, uid):
    page.goto(f"{live_server}/pages/users.html")
    page.wait_for_function(f"() => {DATA}.users && {DATA}.users.length > 0", timeout=20000)
    page.evaluate(f"() => {DATA}.openEdit({DATA}.users.find(u => u.id === {uid}))")
    page.wait_for_function(f"() => {DATA}.permGate.hi.length > 0 && {DATA}.duty.loaded === true", timeout=20000)      # 高敏感清單與職責角色資料都讀完


@pytest.mark.e2e
def test_high_sensitive_toggle_requires_a_reason_and_is_recorded(live_server, make_user, e2e_browser):
    sa = make_user(username="pg_sa", role="superadmin")
    make_user(username="pg_eng", role="engineer", modules=["dashboard", "equipment"], legacy_finance_flag=False)
    uid = _q("SELECT id FROM users WHERE username='pg_eng'")[0]["id"]
    page = e2e_browser.new_page()
    inject_login(page, live_server, *sa)
    _open_edit(page, live_server, uid)

    # 勾一般鍵：不出現原因欄
    page.evaluate(f"() => {DATA}.toggleModule('quotation')")
    assert page.evaluate(f"() => {DATA}.permGateTouched()") == []
    page.locator('[data-testid="perm-gate"]').wait_for(state="hidden", timeout=5000)
    page.evaluate(f"() => {DATA}.toggleModule('quotation')")            # 還原

    # 勾高敏感鍵 ⇒ 原因欄出現；缺原因存檔被擋（前端先擋；資料庫不動）
    page.evaluate(f"() => {DATA}.toggleModule('settings')")
    page.locator('[data-testid="perm-gate"]').wait_for(state="visible", timeout=5000)
    assert page.evaluate(f"() => {DATA}.permGateTouched()") == ["settings"]
    page.evaluate(f"() => {DATA}.saveUser()")
    page.wait_for_function(f"() => /原因/.test({DATA}.formError)", timeout=10000)
    assert json.loads(_q("SELECT modules FROM users WHERE id=?", (uid,))[0]["modules"]) == ["dashboard", "equipment"]
    assert _q("SELECT COUNT(*) AS n FROM permission_changes WHERE target_id=?", (uid,))[0]["n"] == 0

    # 填原因 ⇒ 存檔成功、permission_changes 一列（kind=user_modules、含原因）
    page.fill('[data-testid="perm-gate-reason"]', "接手系統設定維護")
    page.evaluate(f"() => {DATA}.saveUser()")
    page.wait_for_function(f"() => {DATA}.showModal === false", timeout=20000)
    assert "settings" in json.loads(_q("SELECT modules FROM users WHERE id=?", (uid,))[0]["modules"])
    ch = _q("SELECT kind, reason, high_sensitivity, audit_id FROM permission_changes WHERE target_id=?", (uid,))
    assert len(ch) == 1 and (ch[0]["kind"], ch[0]["reason"], ch[0]["high_sensitivity"]) == ("user_modules", "接手系統設定維護", 1) and ch[0]["audit_id"]
