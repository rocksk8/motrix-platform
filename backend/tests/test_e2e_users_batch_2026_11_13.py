"""瀏覽器端對端：使用者管理頁「批次調整權限」面板（設定矩陣 S3a；static/users-batch.js）。

- 授予：高敏感／影響較大／財務三鍵的核取方塊反灰（清單來自 /api/modules/catalog）；一般鍵可批次授予 → 預覽 → 套用 → 資料庫落地 → 復原這一批；
- 取消高敏感鍵：沒填原因被擋（伺服器訊息顯示在確認視窗）、資料庫不動；填原因 ⇒ 成功並有 permission_changes；
- 名稱含 `<img onerror>`／`<script>` 的同仁在面板與確認視窗中被跳脫（不執行、當文字顯示）。
觀測點打在資料庫落地值與元件狀態。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

DATA = "Alpine.$data(document.querySelector('[x-data]'))"
EVIL = "<img src=x onerror=window.__pwn=1><script>window.__pwn2=1</script>"


def _q(sql, args=()):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


def _mods(uid):
    return json.loads(_q("SELECT modules FROM users WHERE id=?", (uid,))[0]["modules"])


def _open_panel(page, live_server):
    page.goto(f"{live_server}/pages/users.html")
    page.wait_for_function(f"() => {DATA}.users && {DATA}.users.length > 0 && {DATA}.batchLists.high.length > 0", timeout=20000)
    page.locator('[data-testid="batch-open"]').click()
    page.locator('[data-testid="batch-preview"]').wait_for(state="visible", timeout=5000)


def _two_people(make_user):
    make_user(username="bt_a", role="sales", modules=["dashboard", "settings"], legacy_finance_flag=False)
    make_user(username="bt_b", role="engineer", modules=["dashboard"], legacy_finance_flag=False)
    return _q("SELECT id FROM users WHERE username='bt_a'")[0]["id"], _q("SELECT id FROM users WHERE username='bt_b'")[0]["id"]


@pytest.mark.e2e
def test_grant_ordinary_key_then_undo_and_gated_keys_are_disabled(live_server, make_user, e2e_browser):
    sa = make_user(username="bt_sa", role="superadmin")
    a, b = _two_people(make_user)
    page = e2e_browser.new_page()
    inject_login(page, live_server, *sa)
    _open_panel(page, live_server)
    for k in ("settings", "quotation", "cashier"):                                       # 高敏感／批次拒絕清單／財務三鍵：授予時反灰
        assert page.locator(f'[data-testid="batch-key-{k}"]').is_disabled(), k
    assert page.locator('[data-testid="batch-key-customer"]').is_enabled()
    page.locator(f'[data-testid="batch-user-{a}"]').check()
    page.locator(f'[data-testid="batch-user-{b}"]').check()
    page.locator('[data-testid="batch-key-customer"]').check()
    page.locator('[data-testid="batch-preview"]').click()
    page.locator('[data-testid="batch-plan"]').wait_for(state="visible", timeout=10000)
    assert _mods(a) == ["dashboard", "settings"], "預覽不寫入"
    page.locator('[data-testid="batch-apply"]').click()
    page.wait_for_function(f"() => {DATA}.batch.result !== null", timeout=10000)
    assert _mods(a) == ["dashboard", "settings", "customer"] and _mods(b) == ["dashboard", "customer"]
    page.locator('[data-testid="batch-undo"]').click()
    page.wait_for_function(f"() => {DATA}.batch.result === null && /已復原 2 位/.test({DATA}.batch.undoMsg)", timeout=10000)
    assert _mods(a) == ["dashboard", "settings"] and _mods(b) == ["dashboard"]


@pytest.mark.e2e
def test_revoke_high_sensitive_key_needs_a_reason(live_server, make_user, e2e_browser):
    sa = make_user(username="bt_sa2", role="superadmin")
    a, _b = _two_people(make_user)
    page = e2e_browser.new_page()
    inject_login(page, live_server, *sa)
    _open_panel(page, live_server)
    page.locator(f'[data-testid="batch-user-{a}"]').check()
    page.locator('input[name="batch-action"][value="revoke"]').check()
    page.locator('[data-testid="batch-key-settings"]').wait_for(state="visible", timeout=5000)
    page.wait_for_function("() => !document.querySelector('[data-testid=\"batch-key-settings\"]').disabled", timeout=5000)   # 切到「取消」後才可勾（等 Alpine 重繪）
    assert page.locator('[data-testid="batch-key-settings"]').is_enabled(), "取消高敏感鍵可以批次"
    page.locator('[data-testid="batch-key-settings"]').check()
    page.locator('[data-testid="batch-preview"]').click()
    page.locator('[data-testid="batch-reason"]').wait_for(state="visible", timeout=10000)          # 需要原因 ⇒ 原因欄出現
    page.locator('[data-testid="batch-apply"]').click()
    page.locator('[data-testid="batch-plan-error"]').wait_for(state="visible", timeout=10000)
    assert "原因" in page.locator('[data-testid="batch-plan-error"]').inner_text()
    assert "settings" in _mods(a) and _q("SELECT COUNT(*) AS n FROM permission_changes WHERE target_id=?", (a,))[0]["n"] == 0
    page.fill('[data-testid="batch-reason"]', "人員轉調收回系統設定")
    page.locator('[data-testid="batch-apply"]').click()
    page.wait_for_function(f"() => {DATA}.batch.result !== null", timeout=10000)
    assert "settings" not in _mods(a)
    ch = _q("SELECT reason, high_sensitivity FROM permission_changes WHERE target_id=?", (a,))
    assert [(c["reason"], c["high_sensitivity"]) for c in ch] == [("人員轉調收回系統設定", 1)]


@pytest.mark.e2e
def test_names_with_markup_are_escaped_in_panel_and_confirm_dialog(live_server, make_user, e2e_browser):
    sa = make_user(username="bt_sa3", role="superadmin")
    make_user(username="bt_x", role="sales", modules=["dashboard"], legacy_finance_flag=False)
    uid = _q("SELECT id FROM users WHERE username='bt_x'")[0]["id"]
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE users SET display_name=? WHERE id=?", (EVIL, uid))
        conn.commit()
    finally:
        conn.close()
    page = e2e_browser.new_page()
    inject_login(page, live_server, *sa)
    _open_panel(page, live_server)
    page.locator(f'[data-testid="batch-user-{uid}"]').check()
    page.locator('[data-testid="batch-key-customer"]').check()
    page.locator('[data-testid="batch-preview"]').click()
    page.locator('[data-testid="batch-plan"]').wait_for(state="visible", timeout=10000)
    assert EVIL in page.locator('[data-testid="batch-plan"]').inner_text(), "名稱當純文字顯示"
    assert page.evaluate("() => window.__pwn === undefined && window.__pwn2 === undefined"), "標籤不可被執行"
    assert page.locator('#batch-perm-panel img').count() == 0 and page.locator('[data-testid="batch-plan"] img').count() == 0


@pytest.mark.e2e
def test_panel_layout_survives_dynamic_style_and_selection_rules(live_server, make_user, e2e_browser):
    """審查 h5 M1／S1／S3：`:style` 用字串會整個蓋掉靜態 style（版面消失），以計算後樣式守住；
    「全部取消」連被搜尋隱藏的人也清掉；套用成功後選取清空、取消確認視窗會清掉錯誤。"""
    sa = make_user(username="bt_sa4", role="superadmin")
    a, b = _two_people(make_user)
    page = e2e_browser.new_page()
    inject_login(page, live_server, *sa)
    _open_panel(page, live_server)
    disp = lambda sel: page.locator(sel).evaluate("el => getComputedStyle(el).display")      # noqa: E731
    assert disp('[data-testid="batch-open"]') == "flex", "面板標題列的 flex 版面不可被 :style 蓋掉"
    assert page.locator('[data-testid="batch-open"]').evaluate("el => getComputedStyle(el).cursor") == "pointer"
    assert page.locator('[data-testid="batch-key-customer"]').locator("xpath=..").evaluate("el => getComputedStyle(el).display") == "flex"
    assert page.locator('[data-testid="batch-key-customer"]').locator("xpath=..").evaluate("el => parseFloat(getComputedStyle(el).paddingLeft)") > 0
    assert page.locator('[data-testid="batch-open"]').get_attribute("role") == "button"

    page.locator(f'[data-testid="batch-user-{a}"]').check()
    page.fill('input[placeholder="搜尋帳號／顯示名稱"]', "查無此人zzzz")
    page.wait_for_function(f"() => /被搜尋隱藏/.test({DATA}.batchSelectedText())", timeout=5000)      # 等 Alpine 重算再讀畫面
    assert "被搜尋隱藏" in page.locator('[data-testid="batch-selected-count"]').inner_text()
    page.get_by_role("button", name="全部取消").click()
    assert page.evaluate(f"() => {DATA}.batchSelectedIds().length") == 0, "全部取消要清掉所有已選（含被隱藏的）"
    page.fill('input[placeholder="搜尋帳號／顯示名稱"]', "")

    page.locator(f'[data-testid="batch-user-{a}"]').check()
    page.locator('[data-testid="batch-key-customer"]').check()
    page.locator('[data-testid="batch-preview"]').click()
    page.locator('[data-testid="batch-plan"]').wait_for(state="visible", timeout=10000)
    page.evaluate(f"() => {{ {DATA}.batch.error = '假的錯誤' }}")
    page.locator('[data-testid="batch-plan-cancel"]').click()
    assert page.evaluate(f"() => {DATA}.batch.error") == "", "取消確認視窗要清掉錯誤"
    page.locator('[data-testid="batch-preview"]').click()
    page.locator('[data-testid="batch-plan"]').wait_for(state="visible", timeout=10000)
    page.locator('[data-testid="batch-apply"]').click()
    page.wait_for_function(f"() => {DATA}.batch.result !== null", timeout=10000)
    assert page.evaluate(f"() => {DATA}.batchSelectedIds().length") == 0, "套用成功後選取要清空"


@pytest.mark.e2e
def test_confirm_dialog_names_the_role_and_the_effective_permission_changes(live_server, make_user, e2e_browser):
    """審查 h5 S2（h4 豁免條件 2）：確認視窗要點名角色，並列出『實際生效多了／少了』哪些權限。"""
    sa = make_user(username="bt_sa5", role="superadmin")
    a, _b = _two_people(make_user)
    page = e2e_browser.new_page()
    inject_login(page, live_server, *sa)
    _open_panel(page, live_server)
    rid = page.evaluate(f"""async () => {{
        const r = await fetch('/api/duty-roles', {{ method: 'POST', headers: {DATA}._headers(),
            body: JSON.stringify({{ key: 'bt_role', name: '外勤小組角色', description: '', permissions: ['customer', 'map'], reason: '建立角色作業' }}) }})
        return (await r.json()).id }}""")
    assert rid
    page.evaluate(f"() => {DATA}.batchLoadRoles()")
    page.wait_for_function(f"() => {DATA}.batch.roles.some(r => r.id === {rid})", timeout=10000)
    page.locator(f'[data-testid="batch-user-{a}"]').check()
    page.locator('input[name="batch-action"][value="bind"]').check()
    page.select_option('[data-testid="batch-role"]', str(rid))
    page.locator('[data-testid="batch-preview"]').click()
    page.locator('[data-testid="batch-plan"]').wait_for(state="visible", timeout=10000)
    assert "外勤小組角色" in page.locator('[data-testid="batch-plan-bind"]').inner_text(), "要寫出角色名稱，不只是「1 個」"
    eff = page.locator('[data-testid="batch-plan-eff-add"]').inner_text()
    assert "實際生效" in eff and "多了" in eff, eff
