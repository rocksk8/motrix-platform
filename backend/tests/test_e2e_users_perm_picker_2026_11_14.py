"""瀏覽器端對端：使用者編輯視窗的「存取模組」改成矩陣選擇器（T86；static/perm-key-picker.js），鍵值與儲存格式不變。

- 全部群組一開窗就攤開（不用逐群展開）；每群有總開關（全選／部分／全無）；篩選與「只看已選／未選」；差異預覽＝相對開啟當下；
- 點擊與總開關改的是 form.modules（儲存前不寫入）；財務三鍵維持「失效」不可勾；全部取消不動失效的鍵；
- 存檔後資料庫裡的鍵值就是勾的那些（鍵值不變）。
觀測點打在元件狀態與資料庫落地值，不打頁面文字。
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


def _open(page, live_server, uid):
    page.goto(f"{live_server}/pages/users.html")
    page.wait_for_function(f"() => {DATA}.users && {DATA}.users.length > 0 && {DATA}.allModules.length > 0 && {DATA}.pkUser", timeout=20000)
    page.evaluate(f"() => {DATA}.openEdit({DATA}.users.find(u => u.id === {uid}))")
    page.locator('[data-testid="pk-user-picker"]').wait_for(state="visible", timeout=10000)


@pytest.mark.e2e
def test_groups_are_all_open_and_group_switch_and_chips_change_only_the_form(live_server, make_user, e2e_browser):
    sa = make_user(username="pk_sa", role="superadmin")
    make_user(username="pk_eng", role="engineer", modules=["dashboard", "equipment"], legacy_finance_flag=False)
    uid = _q("SELECT id FROM users WHERE username='pk_eng'")[0]["id"]
    page = e2e_browser.new_page()
    inject_login(page, live_server, *sa)
    _open(page, live_server, uid)

    groups = page.evaluate(f"() => {DATA}.moduleGroups.map(g => g.group)")
    assert len(groups) >= 3
    heads = page.locator('[data-testid^="pk-user-group-"]')
    assert heads.count() == len(groups) and all(heads.nth(i).is_visible() for i in range(heads.count())), "每一群都直接攤開，不必逐群展開"
    first_chip = page.evaluate(f"() => {DATA}.moduleGroups[0].mods[0].key")
    assert page.locator(f'[data-testid="mod-chip-{first_chip}"]').is_visible()

    # 總開關：第一群全選 → 該群的鍵（能勾的）全在 form.modules；再按一次全部取消
    g0 = page.evaluate(f"() => {DATA}.moduleGroups[0]")
    togglable = [m["key"] for m in g0["mods"] if m["key"] not in ("cashier", "finance", "financial_view")]
    sw = page.locator(f'[data-testid="pk-user-group-{g0["group"]}"] input')
    start_all = set(togglable) <= set(page.evaluate(f"() => {DATA}.form.modules"))   # 這個使用者原本可能已勾滿這一群 ⇒ 第一下是全部取消
    sw.click()
    mods = set(page.evaluate(f"() => {DATA}.form.modules"))
    assert (not (set(togglable) & mods)) if start_all else (set(togglable) <= mods)
    sw.click()
    mods = set(page.evaluate(f"() => {DATA}.form.modules"))
    assert (set(togglable) <= mods) if start_all else (not (set(togglable) & mods))

    # 差異預覽：相對於開窗當下；還沒存，資料庫不動
    page.locator(f'[data-testid="mod-chip-{first_chip}"]').click()
    page.locator('[data-testid="pk-user-diff"]').wait_for(state="visible", timeout=5000)
    was_on = first_chip in ("dashboard", "equipment")          # 原本已勾 ⇒ 這一下是取消；否則是新增
    assert ("取消 1 項" if was_on else "新增 1 項") in page.locator('[data-testid="pk-user-diff"]').inner_text()
    assert json.loads(_q("SELECT modules FROM users WHERE id=?", (uid,))[0]["modules"]) == ["dashboard", "equipment"]


@pytest.mark.e2e
def test_filter_and_only_selected_and_clear_all_keep_inert_finance_keys(live_server, make_user, e2e_browser):
    sa = make_user(username="pk_sa2", role="superadmin")
    make_user(username="pk_eng2", role="engineer", modules=["dashboard", "equipment"], legacy_finance_flag=False)
    uid = _q("SELECT id FROM users WHERE username='pk_eng2'")[0]["id"]
    page = e2e_browser.new_page()
    inject_login(page, live_server, *sa)
    _open(page, live_server, uid)

    total = page.locator('[data-testid^="mod-chip-"]').count()
    page.select_option('[data-testid="pk-user-show"]', "on")
    shown = page.locator('[data-testid^="mod-chip-"]').count()
    assert 0 < shown < total, "只看已選：只列出已勾的"
    page.select_option('[data-testid="pk-user-show"]', "all")
    label = page.evaluate(f"() => {DATA}.allModules.find(m => m.key === 'dashboard').label")
    page.fill('[data-testid="pk-user-q"]', label)
    assert 1 <= page.locator('[data-testid^="mod-chip-"]').count() < total, "篩選名稱會縮小列表"

    # 財務三鍵：不能點、被標成失效；全部取消不動它們
    page.fill('[data-testid="pk-user-q"]', "")
    for k in ("cashier", "finance", "financial_view"):
        if page.locator(f'[data-testid="mod-chip-{k}"]').count():
            assert page.locator(f'[data-testid="mod-chip-{k}"] input').is_disabled()
    before_inert = page.evaluate(f"() => {DATA}.form.modules.filter(k => ['cashier','finance','financial_view'].includes(k))")
    page.locator('[data-testid="pk-user-none"]').click()
    after = page.evaluate(f"() => {DATA}.form.modules")
    assert after == before_inert, "全部取消只清能勾的鍵，失效的財務鍵資料保留"


@pytest.mark.e2e
def test_saved_values_are_the_plain_keys_that_were_ticked(live_server, make_user, e2e_browser):
    sa = make_user(username="pk_sa3", role="superadmin")
    make_user(username="pk_eng3", role="engineer", modules=["dashboard", "equipment"], legacy_finance_flag=False)
    uid = _q("SELECT id FROM users WHERE username='pk_eng3'")[0]["id"]
    page = e2e_browser.new_page()
    inject_login(page, live_server, *sa)
    _open(page, live_server, uid)
    page.locator('[data-testid="mod-chip-quotation"]').click()          # 一般鍵（非高敏感）：不需要原因
    page.evaluate(f"() => {DATA}.saveUser()")
    page.wait_for_function(f"() => !{DATA}.showModal", timeout=20000)
    assert sorted(json.loads(_q("SELECT modules FROM users WHERE id=?", (uid,))[0]["modules"])) == ["dashboard", "equipment", "quotation"]


@pytest.mark.e2e
def test_custom_role_modal_uses_the_same_picker(live_server, make_user, e2e_browser):
    sa = make_user(username="pk_sa4", role="superadmin")
    page = e2e_browser.new_page()
    inject_login(page, live_server, *sa)
    page.goto(f"{live_server}/pages/users.html")
    page.wait_for_function(f"() => {DATA}.allModules && {DATA}.allModules.length > 0 && {DATA}.pkCr", timeout=20000)
    page.evaluate(f"() => {DATA}.openCrCreate()")
    page.locator('[data-testid="pk-cr-picker"]').wait_for(state="visible", timeout=10000)
    key = page.evaluate(f"() => {DATA}.moduleGroups[0].mods[0].key")
    on0 = page.evaluate(f"() => {DATA}.crForm.modules.includes('{key}')")
    page.locator(f'[data-testid="cr-chip-{key}"]').click()
    assert page.evaluate(f"() => {DATA}.crForm.modules.includes('{key}')") is (not on0)
    page.locator('[data-testid="pk-cr-diff"]').wait_for(state="visible", timeout=5000)
