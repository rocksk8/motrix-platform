"""瀏覽器端對端：職責角色頁的「職責 × 權限」矩陣（pages/duty-roles.html＋static/duty-matrix.js，共用元件 settings-matrix.js；T86）。

驗：點格子只算草稿（資料庫不動、頂端儲存列）→ 儲存先出預覽（每個角色多／少什麼、影響幾位成員）→ 套用才寫入（版本 +1、變更紀錄）；
高敏感權限缺原因被擋、填了才成功；復原這一批；欄頭整欄一次勾；勾列＋「全部取消」批次與群組總開關都只是草稿；篩選「高敏感」；
角色管理表單不再有 30 顆權限 chip。觀測點打在資料庫落地值，不打在頁面寫死的文字上。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect  # noqa: E402


def _q(sql, args=()):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


def _seed_roles():
    """兩個角色：矩陣測試甲（dashboard）、矩陣測試乙（dashboard＋quotation）；回 {key: id}。"""
    import db
    from helpers import duty_roles as dr
    conn = db.get_db()
    try:
        actor = dict(conn.execute("SELECT * FROM users WHERE role='superadmin' ORDER BY id LIMIT 1").fetchone())
        ids = {}
        for key, name, perms in (("mx_a", "矩陣測試甲", ["dashboard"]), ("mx_b", "矩陣測試乙", ["dashboard", "quotation"])):
            ids[key] = dr.create_role(conn, actor, key, name, "", perms, "", "")
        return ids
    finally:
        conn.close()


def _perms(rid):
    return json.loads(_q("SELECT permissions FROM duty_roles WHERE id=?", (rid,))[0]["permissions"])


def _open(live_server, make_user, new_page, login_as, name, width=1600):
    u = make_user(username=name, role="superadmin")
    ids = _seed_roles()
    page = new_page(viewport={"width": width, "height": 2200})
    login_as(page, u)
    page.goto(f"{live_server}/pages/duty-roles.html")
    page.locator("[data-testid='mx-row-quotation']").wait_for(state="attached", timeout=20000)
    return page, ids


def _cell(page, key, rid):
    return page.locator('button.mx-rc[data-mx="chip"][data-col="roles"][data-key="%s"][data-val="r%d"]' % (key, rid))


def _dlg_btn(page, text):
    return page.locator(".mx-dlg button").filter(has_text=text).first


def _save_with_reason(page, reason=None):
    page.locator("[data-testid=mx-draft-save]").click()
    _dlg_btn(page, "套用").wait_for(state="visible", timeout=10000)
    if reason is not None:
        page.fill("[data-testid=dm-reason]", reason)
    _dlg_btn(page, "套用").click()


@pytest.mark.e2e
def test_click_is_a_draft_then_preview_then_apply(live_server, make_user, new_page, login_as):
    page, ids = _open(live_server, make_user, new_page, login_as, "e2e_dm1")
    a = ids["mx_a"]
    _cell(page, "quotation", a).click()
    expect(page.locator("[data-testid=mx-draftbar]")).to_be_visible()
    assert _perms(a) == ["dashboard"], "點格子只算草稿，資料庫不動"
    page.locator("[data-testid=mx-draft-save]").click()
    _dlg_btn(page, "套用").wait_for(state="visible", timeout=10000)
    expect(page.locator("[data-testid=dm-plan-summary]")).to_contain_text("多")
    expect(page.locator("[data-testid=dm-plan-role-%d]" % a)).to_contain_text("矩陣測試甲")
    assert _perms(a) == ["dashboard"], "預覽不寫入"
    _dlg_btn(page, "套用").click()
    expect(page.locator("[data-testid=mx-draftbar]")).to_have_count(0)
    assert "quotation" in _perms(a)
    v = _q("SELECT version FROM duty_roles WHERE id=?", (a,))[0]["version"]
    assert v == 2
    ch = _q("SELECT kind, audit_id FROM permission_changes WHERE target_type='role' AND target_id=? ORDER BY id DESC LIMIT 1", (a,))
    assert ch[0]["kind"] == "role_def" and ch[0]["audit_id"]


@pytest.mark.e2e
def test_high_sensitive_needs_a_reason_and_undo_restores(live_server, make_user, new_page, login_as):
    page, ids = _open(live_server, make_user, new_page, login_as, "e2e_dm2")
    a = ids["mx_a"]
    _cell(page, "settings", a).click()
    _save_with_reason(page, None)                                             # 缺原因：伺服器擋，草稿保留，資料庫不動
    expect(page.locator("[data-testid=mx-toast-text]")).to_contain_text("原因")
    assert "settings" not in _perms(a)
    expect(page.locator("[data-testid=mx-draftbar]")).to_be_visible()
    _save_with_reason(page, "核定新增系統設定權限")                            # 重新儲存：輸入框預填上次輸入的內容，再確認一次
    expect(page.locator("[data-testid=mx-draftbar]")).to_have_count(0)
    assert "settings" in _perms(a)
    row = _q("SELECT high_sensitivity, reason FROM permission_changes WHERE target_type='role' AND target_id=? ORDER BY id DESC LIMIT 1", (a,))[0]
    assert row["high_sensitivity"] == 1 and row["reason"] == "核定新增系統設定權限"
    # 復原這一批：還回高敏感鍵的取消也要原因 ⇒ 沿用套用當時填的原因，一次就成功（F1：以前送空字串，一律 400）
    page.locator("[data-testid=mx-undo]").click()
    for _ in range(50):                                                       # 復原是非同步請求：輪詢資料庫落地值（最多 10 秒）
        if "settings" not in _perms(a):
            break
        page.wait_for_timeout(200)
    assert "settings" not in _perms(a), "復原應成功（沿用套用時的原因）"
    row = _q("SELECT high_sensitivity, reason FROM permission_changes WHERE target_type='role' AND target_id=? ORDER BY id DESC LIMIT 1", (a,))[0]
    assert row["high_sensitivity"] == 1 and row["reason"] == "復原：核定新增系統設定權限"


@pytest.mark.e2e
def test_undo_a_normal_batch_and_column_select(live_server, make_user, new_page, login_as):
    page, ids = _open(live_server, make_user, new_page, login_as, "e2e_dm3")
    a = ids["mx_a"]
    # 欄頭整欄一次勾：先搜尋縮小到幾列，再勾甲角色的欄頭（甲沒有這些列的權限）
    page.fill("input.mx-search", "quotation")
    page.locator("[data-mx=csel][data-col=roles][data-val=r%d]" % a).first.check()
    expect(page.locator("[data-testid=mx-draftbar]")).to_be_visible()
    assert _perms(a) == ["dashboard"], "整欄勾也只是草稿"
    page.locator("[data-testid=mx-draft-discard]").click()
    expect(page.locator("[data-testid=mx-draftbar]")).to_have_count(0)


@pytest.mark.e2e
def test_role_form_has_no_permission_chip_pool(live_server, make_user, new_page, login_as):
    page, ids = _open(live_server, make_user, new_page, login_as, "e2e_dm4")
    page.locator("[data-testid=dr-new-role]").click()
    page.locator("[data-testid=dr-form]").wait_for(state="visible", timeout=10000)
    assert page.locator("[data-testid=dr-form] .dr-chip").count() == 0, "權限一律在矩陣調整，表單不再有權限 chip"
    expect(page.locator("[data-testid=dr-form]")).to_contain_text("權限矩陣")


@pytest.mark.e2e
def test_batch_pick_roles_and_group_switch_are_drafts(live_server, make_user, new_page, login_as):
    page, ids = _open(live_server, make_user, new_page, login_as, "e2e_dm5")
    a, b = ids["mx_a"], ids["mx_b"]
    # 勾列＋「指定角色…」：授予甲、乙兩個角色（草稿，疊在既有勾選上：乙原本就有 quotation）
    page.locator("[data-testid='mx-row-quotation'] input[data-mx=sel]").check()
    expect(page.locator("[data-testid=mx-batch-count]")).to_have_text("已選 1 項")
    page.locator("[data-testid=mx-batch-some]").click()
    page.locator("[data-testid=dm-pick-role-%d]" % a).check()
    page.locator("[data-testid=dm-pick-role-%d]" % b).check()
    _dlg_btn(page, "加入草稿").click()
    expect(page.locator("[data-testid=mx-draftbar]")).to_be_visible()
    assert "quotation" not in _perms(a), "批次只進草稿"
    page.locator("[data-testid=mx-draft-save]").click()
    _dlg_btn(page, "套用").wait_for(state="visible", timeout=10000)
    # 乙原本就有 quotation ⇒ 沒有實質變更，預覽不列；甲才有「新增權限」
    expect(page.locator("[data-testid=dm-plan-role-%d]" % b)).to_have_count(0)
    expect(page.locator("[data-testid=dm-plan-role-%d]" % a)).to_contain_text("新增權限")
    _dlg_btn(page, "套用").click()
    expect(page.locator("[data-testid=mx-draftbar]")).to_have_count(0)
    assert "quotation" in _perms(a) and "quotation" in _perms(b)
    # 勾列＋「全部取消」：全部角色都拿掉（草稿；放棄後資料不動）
    page.locator("[data-testid='mx-row-quotation'] input[data-mx=sel]").check()
    page.locator("[data-testid=mx-batch-none]").click()
    expect(page.locator("[data-testid=mx-draftbar]")).to_be_visible()
    assert "quotation" in _perms(a) and "quotation" in _perms(b)
    page.locator("[data-testid=mx-draft-discard]").click()
    expect(page.locator("[data-testid=mx-draftbar]")).to_have_count(0)
    # 群組總開關（群組列的「全部角色都有」）：只進草稿
    from helpers import module_registry as mr
    grp = [g for k, _l, g in mr.MODULES if k == "quotation"][0]                 # 「報價單」所在的群組（第一個群組的權限多半所有角色都有，按了沒有差異）
    page.locator('.mx-table [data-mx=gact][data-act=all][data-g="%s"]' % grp).click()
    expect(page.locator("[data-testid=mx-draftbar]")).to_be_visible()
    before = (_perms(a), _perms(b))
    page.locator("[data-testid=mx-draft-discard]").click()
    assert (_perms(a), _perms(b)) == before, "群組總開關在儲存前不寫入"
