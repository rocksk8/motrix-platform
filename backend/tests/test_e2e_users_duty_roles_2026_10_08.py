"""瀏覽器端對端：使用者管理編輯視窗的職責角色／個人扣項／生效權限預覽（R2 第 2 步 2a／2b／Q3；docs/platform/R2-STEPS-2-4-DESIGN.md §2.7）。

- 開編輯視窗 → 勾角色 → 預覽（伺服器算）即時變 → 高敏感角色時原因欄必填 → 存檔 → 變更紀錄出現；
- **不烘焙**：綁角色後只存檔，`users.modules` 位元組與開窗前相同；
- Q3：既有使用者 modules 為空 ⇒ 編輯視窗不預填樣板；新增使用者仍預填。
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
    page.wait_for_function(f"() => {DATA}.duty.loaded === true && {DATA}.duty.preview !== null", timeout=20000)      # 角色資料讀完且第一次預覽（伺服器算）回來


@pytest.mark.e2e
def test_bind_role_preview_reason_save_and_no_baking(live_server, make_user, e2e_browser):
    sa = make_user(username="r2e_sa", role="superadmin")
    make_user(username="r2e_eng", role="engineer", modules=["dashboard", "equipment"], legacy_finance_flag=False)
    uid = _q("SELECT id FROM users WHERE username='r2e_eng'")[0]["id"]
    raw_before = _q("SELECT modules FROM users WHERE id=?", (uid,))[0]["modules"]
    page = e2e_browser.new_page()
    inject_login(page, live_server, *sa)
    _open_edit(page, live_server, uid)
    page.locator('[data-testid="duty-section"]').wait_for(state="visible", timeout=10000)

    # 開窗時表單是「原始勾選」，不是生效清單；預覽已有結果
    assert page.evaluate(f"() => {DATA}.form.modules") == ["dashboard", "equipment"]
    assert "procurement" not in page.evaluate(f"() => {DATA}.duty.preview.effective")

    # 勾一個一般角色（採購）⇒ 預覽由伺服器算出來並即時更新；表單的原始勾選不變；沒有差異以外的原因要求
    page.locator('[data-testid="duty-role-procurement"]').click()
    page.wait_for_function(f"() => {DATA}.duty.preview.effective.includes('procurement')", timeout=10000)
    assert page.evaluate(f"() => {DATA}.form.modules") == ["dashboard", "equipment"], "預覽不可寫回原始勾選（不烘焙）"
    assert not page.locator('[data-testid="duty-reason-required"]').is_visible()

    # 再勾一個含高敏感鍵的角色（系統管理：settings）⇒ 原因欄必填；缺原因存檔被擋、資料庫沒有任何綁定
    page.locator('[data-testid="duty-role-sysadmin"]').click()
    page.wait_for_function(f"() => {DATA}.duty.preview.effective.includes('settings')", timeout=10000)
    page.locator('[data-testid="duty-reason-required"]').wait_for(state="visible", timeout=5000)
    page.evaluate(f"() => {DATA}.saveUser()")
    page.wait_for_function(f"() => /原因/.test({DATA}.formError)", timeout=10000)
    assert _q("SELECT COUNT(*) AS n FROM user_duty_roles WHERE user_id=?", (uid,))[0]["n"] == 0

    # 填原因 ⇒ 存檔成功：兩個綁定、變更紀錄（含原因）出現；users.modules 位元組與開窗前相同
    page.fill('[data-testid="duty-reason"]', "接手採購與系統維護")
    page.evaluate(f"() => {DATA}.saveUser()")
    page.wait_for_function(f"() => {DATA}.showModal === false", timeout=20000)
    assert _q("SELECT COUNT(*) AS n FROM user_duty_roles WHERE user_id=?", (uid,))[0]["n"] == 2
    ch = _q("SELECT kind, reason, audit_id FROM permission_changes WHERE target_id=? ORDER BY id", (uid,))
    assert [c["kind"] for c in ch] == ["bind", "bind"] and all(c["audit_id"] for c in ch)
    assert any(c["reason"] == "接手採購與系統維護" for c in ch)
    assert _q("SELECT modules FROM users WHERE id=?", (uid,))[0]["modules"] == raw_before, "只綁角色、沒改勾選 ⇒ users.modules 位元組不變（不烘焙）"


@pytest.mark.e2e
def test_subtract_and_save_without_changes_keeps_raw_modules_bytes(live_server, make_user, e2e_browser):
    sa = make_user(username="r2e_sa2", role="superadmin")
    make_user(username="r2e_eng2", role="engineer", modules=["dashboard"], legacy_finance_flag=False)
    uid = _q("SELECT id FROM users WHERE username='r2e_eng2'")[0]["id"]
    rid = _q("SELECT id FROM duty_roles WHERE key='procurement'")[0]["id"]
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO user_duty_roles (user_id, role_id, granted_by, granted_at, reason) VALUES (?,?,?,?,?)", (uid, rid, 1, "t", ""))
        conn.commit()
    finally:
        conn.close()
    raw_before = _q("SELECT modules FROM users WHERE id=?", (uid,))[0]["modules"]
    page = e2e_browser.new_page()
    inject_login(page, live_server, *sa)
    _open_edit(page, live_server, uid)
    assert "procurement" in page.evaluate(f"() => {DATA}.duty.preview.effective"), "角色給的權限在預覽裡"
    # 什麼都不改就存檔 ⇒ users.modules 位元組不變（角色權限沒有被複製進個人勾選）
    page.evaluate(f"() => {DATA}.saveUser()")
    page.wait_for_function(f"() => {DATA}.showModal === false", timeout=20000)
    assert _q("SELECT modules FROM users WHERE id=?", (uid,))[0]["modules"] == raw_before
    # 再開一次，扣掉角色給的「採購」（一般鍵，不必原因）⇒ 預覽立刻沒有它；存檔後 DB 有扣項、users.modules 仍不變
    _open_edit(page, live_server, uid)
    page.locator('[data-testid="duty-sub-procurement"]').click()
    page.wait_for_function(f"() => !{DATA}.duty.preview.effective.includes('procurement')", timeout=10000)
    page.evaluate(f"() => {DATA}.saveUser()")
    page.wait_for_function(f"() => {DATA}.showModal === false", timeout=20000)
    assert [r["perm_key"] for r in _q("SELECT perm_key FROM user_perm_subtracts WHERE user_id=?", (uid,))] == ["procurement"]
    assert _q("SELECT modules FROM users WHERE id=?", (uid,))[0]["modules"] == raw_before


@pytest.mark.e2e
def test_existing_user_with_empty_modules_is_not_prefilled_but_new_user_is(live_server, make_user, e2e_browser):
    sa = make_user(username="r2e_sa3", role="superadmin")
    make_user(username="r2e_empty", role="engineer", modules=[], legacy_finance_flag=False)
    uid = _q("SELECT id FROM users WHERE username='r2e_empty'")[0]["id"]
    assert json.loads(_q("SELECT modules FROM users WHERE id=?", (uid,))[0]["modules"]) == []
    page = e2e_browser.new_page()
    inject_login(page, live_server, *sa)
    _open_edit(page, live_server, uid)
    assert page.evaluate(f"() => {DATA}.form.modules") == [], "Q3：既有使用者 modules 為空 ⇒ 不預填基礎類別樣板"
    # 只改姓名存檔 ⇒ users.modules 仍是空（不會悄悄發回整套樣板）
    page.evaluate(f"() => {{ {DATA}.form.displayName = '改過的名字' }}")
    page.evaluate(f"() => {DATA}.saveUser()")
    page.wait_for_function(f"() => {DATA}.showModal === false", timeout=20000)
    row = _q("SELECT display_name, modules FROM users WHERE id=?", (uid,))[0]
    assert row["display_name"] == "改過的名字" and json.loads(row["modules"]) == []
    # 新增使用者仍預填樣板
    page.evaluate(f"() => {DATA}.openCreate()")
    assert len(page.evaluate(f"() => {DATA}.form.modules")) > 0
