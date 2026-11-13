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
    assert "簽核會重跑" in (btn.get_attribute("title") or "")
    assert not page.is_visible('[data-testid="qf-review-edit-start"]'), "最高管理者不走複查編輯（不改後端權限）"
    # 解鎖：輸入個人解鎖密碼 ⇒ 欄位真的可編輯
    btn.click()
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
