# -*- coding: utf-8 -*-
"""瀏覽器層級：最高管理者開著待審核／簽核中的單，要有「解鎖編輯」入口（V3.45，fix/superadmin-approver-edit-entry）。

正式機回報：最高管理者把 reconfirm_mode 設成開啟後，打開待審核的單，畫面沒有任何編輯入口。
原因：「編輯」鈕排除最高管理者（他走解鎖編輯）；但頂端「解鎖編輯」只在已送出才出現；唯讀橫幅只給非簽核人。
⇒ 最高管理者＋當層簽核人＋待審核／簽核中 ＝ 完全沒有入口。

驗：①那個情境有入口（tooltip 說明整條簽核會重跑）、解鎖後欄位真的可編輯、重新鎖定真的鎖回去；
②一般簽核人行為不變（常駐「編輯」鈕、沒有解鎖入口）；③送審人看到的單有「收回草稿」提示。不改後端權限。
"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._requires import requires_module  # noqa: E402
from tests.test_e2e_review_edit_lock_2026_11_11 import NO, QTY, _is_locked, _open_form, _seed, _set_mode  # noqa: E402

pytestmark = requires_module("case", "本檔的題打 M01（案件）的報價單頁")

_UNLOCK_PW = "Unlock-Pw-2026!x"


def _set_unlock_password(username):
    import db
    from helpers.auth import _hash_pw
    c = db.get_db()
    try:
        c.execute("UPDATE users SET unlock_password_hash=? WHERE username=?", (_hash_pw(_UNLOCK_PW), username))
        c.commit()
    finally:
        c.close()


@pytest.mark.e2e
def test_superadmin_who_is_the_current_approver_gets_an_unlock_entry_on_a_pending_quote(live_server, make_user, e2e_browser):
    u, p = make_user(username="sae_sa", role="superadmin", modules=["quotation"])
    _set_unlock_password(u)
    _set_mode(2)
    _seed([u])                                                                 # 他本人就是第一層簽核人
    page = e2e_browser.new_page()
    inject_login(page, live_server, u, p)
    _open_form(page, live_server)
    page.wait_for_function("() => document.querySelector('.qty-input').readOnly", timeout=5000)
    assert _is_locked(page)
    btn = page.locator('[data-testid="qf-unlock-edit"]')
    btn.wait_for(state="visible", timeout=5000)
    assert "已簽的層需重新簽核" in (btn.get_attribute("title") or "") and "送審人維持" in (btn.get_attribute("title") or "")
    assert not page.is_visible('[data-testid="qf-review-edit-start"]'), "最高管理者不走複查編輯（不改後端權限）"
    # 解鎖：輸入個人解鎖密碼 ⇒ 欄位真的可編輯
    btn.click()
    page.locator('[data-testid="qf-unlock-consequence"]').wait_for(state="visible", timeout=5000)     # 點完先等彈窗出現再讀字
    cons = page.inner_text('[data-testid="qf-unlock-consequence"]')
    assert "已簽的層需重新簽核，並通知他們" in cons and "送審人維持" in cons, "彈窗要講清楚後果（PM）：" + cons
    page.fill('input[placeholder="輸入解鎖密碼"]', _UNLOCK_PW)
    page.get_by_role("button", name="確認解鎖").click()
    page.wait_for_selector('[data-testid="qf-unlocked-banner"]', state="visible", timeout=10000)
    page.wait_for_function("() => !document.querySelector('.qty-input').readOnly", timeout=5000)
    assert not _is_locked(page), "解鎖後（即使他同時是當層簽核人）欄位要可編輯"
    assert not page.is_visible('[data-testid="qf-unlock-edit"]')
    # 重新鎖定：真的鎖回去
    page.click('[data-testid="qf-relock"]')
    page.wait_for_function("() => document.querySelector('.qty-input').readOnly", timeout=5000)
    assert _is_locked(page)
    assert page.is_visible('[data-testid="qf-unlock-edit"]')


@pytest.mark.e2e
def test_superadmin_who_is_not_the_approver_also_gets_the_entry_and_the_banner_stays(live_server, make_user, e2e_browser):
    u, p = make_user(username="sae_sa2", role="superadmin", modules=["quotation"])
    other, _pw = make_user(username="sae_ap2", role="admin", modules=["quotation"])
    _set_mode(2)
    _seed([other])
    page = e2e_browser.new_page()
    inject_login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/quotation-form.html?id={NO}")
    page.wait_for_selector('[data-testid="qf-pending-lock-banner"]', state="visible", timeout=15000)
    assert page.is_visible('[data-testid="qf-unlock-edit"]')


@pytest.mark.e2e
def test_ordinary_approver_is_unchanged_edit_button_yes_unlock_entry_no(live_server, make_user, e2e_browser):
    u, p = make_user(username="sae_ap", role="admin", modules=["quotation"])
    _set_mode(2)
    _seed([u])
    page = e2e_browser.new_page()
    inject_login(page, live_server, u, p)
    _open_form(page, live_server)
    page.wait_for_function("() => document.querySelector('.qty-input').readOnly", timeout=5000)
    assert page.is_visible('[data-testid="qf-review-edit-start"]')
    assert page.locator('[data-testid="qf-unlock-edit"]').count() == 0
    assert _is_locked(page) and page.get_attribute('.form-left', 'data-approver-locked') == '1'


@pytest.mark.e2e
def test_requester_sees_the_recall_hint_and_no_unlock_entry(live_server, make_user, e2e_browser):
    u, p = make_user(username="sales_x", role="admin", modules=["quotation"])      # _seed 的送審人（requestedBy）
    other, _pw = make_user(username="sae_ap3", role="admin", modules=["quotation"])
    _set_mode(2)
    _seed([other])
    page = e2e_browser.new_page()
    inject_login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/quotation-form.html?id={NO}")
    page.wait_for_selector('[data-testid="qf-pending-requester-hint"]', state="visible", timeout=15000)
    assert "收回草稿" in page.inner_text('[data-testid="qf-pending-requester-hint"]')
    assert page.locator('[data-testid="qf-unlock-edit"]').count() == 0


def _unlock(page, live_server, u):
    _open_form(page, live_server)
    page.wait_for_function("() => document.querySelector('.qty-input').readOnly", timeout=5000)
    page.click('[data-testid="qf-unlock-edit"]')
    page.fill('input[placeholder="輸入解鎖密碼"]', _UNLOCK_PW)
    page.get_by_role("button", name="確認解鎖").click()
    page.wait_for_selector('[data-testid="qf-unlocked-banner"]', state="visible", timeout=10000)
    page.wait_for_function("() => !document.querySelector('.qty-input').readOnly", timeout=5000)


@pytest.mark.e2e
def test_approve_return_reject_buttons_are_hidden_while_unlocked_and_back_after_relock(live_server, make_user, e2e_browser):
    """h9 M1：解鎖編輯中（畫面可能有沒存的修改）不能按核准／退回／駁回——這些動作吃伺服器上的舊內容。"""
    u, p = make_user(username="sae_m1", role="superadmin", modules=["quotation"])
    _set_unlock_password(u)
    _set_mode(2)
    _seed([u])
    page = e2e_browser.new_page()
    inject_login(page, live_server, u, p)
    _open_form(page, live_server)
    assert page.is_visible('[data-testid="qf-approve-open-preview"]')                        # 解鎖前：核准類按鈕在
    assert page.get_by_role("button", name="退回修改").is_visible() and page.get_by_role("button", name="駁回結案").is_visible()
    _unlock(page, live_server, u)
    assert not page.is_visible('[data-testid="qf-approve-open-preview"]')
    assert not page.get_by_role("button", name="退回修改").is_visible()
    assert not page.get_by_role("button", name="駁回結案").is_visible()
    page.click('[data-testid="qf-relock"]')                                                  # 沒改東西 ⇒ 不彈確認
    page.wait_for_selector('[data-testid="qf-approve-open-preview"]', state="visible", timeout=5000)
    assert page.get_by_role("button", name="退回修改").is_visible()


def _flow_with(make_user, username):
    """解鎖存檔會重建簽核鏈：用「統一簽核流程」指定一位簽核人（不依賴送審人的部門設定）；改內容的最高管理者不在鏈中。"""
    import json
    import db
    make_user(username=username, role="admin", modules=["quotation"])
    c = db.get_db()
    try:
        c.execute("INSERT OR REPLACE INTO system_settings (key, value_json, updated_at) VALUES (?,?,?)",
                  ("unified_approval_flow",
                   json.dumps({"tiers": [{"approvers": [{"username": username, "display_name": username}]}], "includeSubmitterManagerTier": False}, ensure_ascii=False),
                   "2026-11-17T00:00:00"))
        c.commit()
    finally:
        c.close()


def _track_puts(page):
    """記下這個頁面送出的報價單 PUT（存檔次數）；回傳 list。"""
    puts = []
    page.on("request", lambda rq: puts.append(rq.url) if rq.method == "PUT" and "/api/quotations/" in rq.url else None)
    return puts


def _server_qty():
    from tests.test_e2e_review_edit_lock_2026_11_11 import _state
    return _state()[0]["items"][0]["qty"]


@pytest.mark.e2e
def test_relock_with_unsaved_edit_saves_once_then_locks_and_the_value_survives_reload(live_server, make_user, e2e_browser):
    """2026-11-17：有未存的修改按「重新鎖定」⇒ 走「儲存修改」同一條儲存（只送一次 PUT）→ 成功後鎖回去；重新載入後值已存、仍鎖定。"""
    u, p = make_user(username="sae_rl1", role="superadmin", modules=["quotation"])
    _set_unlock_password(u)
    _set_mode(2)
    _seed([u])
    _flow_with(make_user, "sae_rl1_ap")
    page = e2e_browser.new_page()
    inject_login(page, live_server, u, p)
    puts = _track_puts(page)
    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))
    _unlock(page, live_server, u)
    page.fill(QTY, "37")
    page.click('[data-testid="qf-relock"]')
    page.wait_for_function("() => document.querySelector('.qty-input').readOnly", timeout=10000)
    assert not page.is_visible('[data-testid="qf-unlocked-banner"]')
    assert page.is_visible('[data-testid="qf-unlock-edit"]')
    assert _server_qty() == 37, "重新鎖定要把修改存進伺服器"
    page.wait_for_timeout(800)                                                 # 負向斷言：給可能的第二次存檔一個流動的機會
    assert len(puts) == 1, f"只存一次（不重複寫入／通知）：{puts}"
    assert not any("失敗" in m for m in dialogs), dialogs
    assert len([m for m in dialogs if "建立客戶檔案" in m]) == 1 and len(dialogs) == 1, f"存一次只會有一次「建立客戶檔案」詢問（checkAndCreateCustomer 沒被呼叫兩次）：{dialogs}"
    page.reload()
    page.wait_for_selector(QTY, state="attached", timeout=15000)
    page.wait_for_function("() => document.querySelector('.qty-input').readOnly", timeout=10000)
    assert page.input_value(QTY) == "37" and _is_locked(page)


@pytest.mark.e2e
def test_relock_without_changes_just_locks_and_sends_nothing(live_server, make_user, e2e_browser):
    u, p = make_user(username="sae_rl2", role="superadmin", modules=["quotation"])
    _set_unlock_password(u)
    _set_mode(2)
    _seed([u])
    page = e2e_browser.new_page()
    inject_login(page, live_server, u, p)
    puts = _track_puts(page)
    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))
    _unlock(page, live_server, u)
    page.click('[data-testid="qf-relock"]')
    page.wait_for_function("() => document.querySelector('.qty-input').readOnly", timeout=5000)
    page.wait_for_timeout(500)
    assert puts == [] and dialogs == []


@pytest.mark.e2e
def test_relock_when_the_save_fails_stays_unlocked_keeps_the_edit_and_shows_the_reason(live_server, make_user, e2e_browser):
    u, p = make_user(username="sae_rl3", role="superadmin", modules=["quotation"])
    _set_unlock_password(u)
    _set_mode(2)
    _seed([u])
    _flow_with(make_user, "sae_rl3_ap")
    page = e2e_browser.new_page()
    inject_login(page, live_server, u, p)
    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))
    _unlock(page, live_server, u)
    before = _server_qty()
    state = {"fail": True}

    def _handle(route):
        if route.request.method == "PUT" and state["fail"]:
            route.fulfill(status=422, content_type="application/json", body='{"detail":"測試用：儲存被拒絕"}')
        else:
            route.continue_()

    page.route("**/api/quotations/**", _handle)
    page.fill(QTY, "41")
    page.click('[data-testid="qf-relock"]')
    page.wait_for_function("() => true")
    assert _wait_for(lambda: any("儲存失敗" in m for m in dialogs), page), dialogs
    assert any("測試用：儲存被拒絕" in m for m in dialogs), "要顯示失敗原因：" + str(dialogs)
    assert page.is_visible('[data-testid="qf-unlocked-banner"]'), "存檔失敗：維持解鎖"
    assert not page.evaluate("() => document.querySelector('.qty-input').readOnly")
    assert page.input_value(QTY) == "41", "存檔失敗：畫面上的修改要留著"
    assert _server_qty() == before
    # 原因排除後再按一次「重新鎖定」：存進去並鎖回去
    state["fail"] = False
    page.click('[data-testid="qf-relock"]')
    page.wait_for_function("() => document.querySelector('.qty-input').readOnly", timeout=10000)
    assert _server_qty() == 41 and _is_locked(page)


def _wait_for(pred, page, tries=50, ms=200):
    for _ in range(tries):
        if pred():
            return True
        page.wait_for_timeout(ms)
    return pred()


@pytest.mark.e2e
def test_discard_button_asks_first_then_returns_to_the_server_version(live_server, make_user, e2e_browser):
    """「放棄修改」才會丟掉修改：先確認；按取消 ⇒ 維持解鎖、修改還在；確認 ⇒ 回到伺服器版、鎖定、不送 PUT。"""
    u, p = make_user(username="sae_rl4", role="superadmin", modules=["quotation"])
    _set_unlock_password(u)
    _set_mode(2)
    _seed([u])
    page = e2e_browser.new_page()
    inject_login(page, live_server, u, p)
    puts = _track_puts(page)
    _unlock(page, live_server, u)
    before = page.input_value(QTY)
    page.fill(QTY, "37")
    page.once("dialog", lambda d: d.dismiss())
    page.click('[data-testid="qf-discard-unlock-edit"]')
    page.wait_for_timeout(500)
    assert page.is_visible('[data-testid="qf-unlocked-banner"]') and page.input_value(QTY) == "37"
    page.once("dialog", lambda d: d.accept())
    page.click('[data-testid="qf-discard-unlock-edit"]')
    page.wait_for_function("() => document.querySelector('.qty-input').readOnly", timeout=10000)
    assert page.input_value(QTY) == before and _is_locked(page) and not page.is_visible('[data-testid="qf-unlocked-banner"]')
    assert _server_qty() == int(before) and puts == []


@pytest.mark.e2e
def test_no_draft_wording_while_unlocked_and_double_click_relock_saves_once(live_server, make_user, e2e_browser):
    u, p = make_user(username="sae_rl5", role="superadmin", modules=["quotation"])
    _set_unlock_password(u)
    _set_mode(2)
    _seed([u])
    _flow_with(make_user, "sae_rl5_ap")
    page = e2e_browser.new_page()
    inject_login(page, live_server, u, p)
    puts = _track_puts(page)
    page.on("dialog", lambda d: d.accept())
    _unlock(page, live_server, u)
    body = page.inner_text("body")
    assert "儲存草稿" not in body and "草稿已儲存" not in body, "送審中的單解鎖編輯時不該出現「草稿」字樣"
    assert page.get_by_role("button", name="儲存修改").first.is_visible()
    page.fill(QTY, "52")
    page.dblclick('[data-testid="qf-relock"]')
    page.wait_for_function("() => document.querySelector('.qty-input').readOnly", timeout=10000)
    page.wait_for_timeout(800)
    assert len(puts) == 1 and _server_qty() == 52, puts


def test_unlock_banner_has_no_ambiguous_cancel_button_and_relock_goes_through_savedraft():
    from core import source_tree
    html = source_tree.page_file("quotation-form.html").read_text(encoding="utf-8")
    assert "取消解鎖" not in html
    i = html.index("      async cancelUnlock() {")
    body = html[i:html.index("      async discardUnlockEdit()", i)]
    assert "await this.saveDraft()" in body and "apiSave" not in body and "unlocked = false" not in body, "重新鎖定必須走 saveDraft，且不得先把 unlocked 設成 false"


def test_autosave_does_not_run_while_unlocked():
    """h9 L1：解鎖編輯一律手動儲存（自動存檔的 PUT 不帶 _isUnlockEdit，待審核／已送出都會被 403）。"""
    from core import source_tree
    html = source_tree.page_file("quotation-form.html").read_text(encoding="utf-8")
    i = html.index("      autoSave() {")
    assert "if (this.unlocked) return" in html[i:i + 400]
