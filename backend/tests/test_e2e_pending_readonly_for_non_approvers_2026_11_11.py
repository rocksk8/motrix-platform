# -*- coding: utf-8 -*-
"""待審核／簽核中的報價單：非簽核人整張唯讀＋橫幅（2026-11-11，T79 維運票 N7，使用者確認）。

正式機 PUT 報價單 403 共 14 次，全是最高管理者：表單只對「當層簽核人」上鎖，其他人開著待審核／簽核中的單欄位照樣可編輯，
存檔必 403、60 秒自動存檔靜默失敗（以為存了）。現在非簽核人（最高管理者、申請人、其他人）也鎖唯讀，
上方橫幅「此單目前待審核／簽核中，僅簽核人可編輯」＋出路（申請人收回草稿／請簽核人退回）；簽核人本人行為不變（不顯示橫幅，有自己的工具列）。
"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._requires import requires_module  # noqa: E402
from tests.test_e2e_review_edit_lock_2026_11_11 import NO, _is_locked, _seed, _set_mode  # noqa: E402

pytestmark = requires_module("case", "本檔的題打 M01（案件）的報價單頁")

BANNER = '[data-testid="qf-pending-lock-banner"]'


def _open(page, live_server):
    page.goto(f"{live_server}/pages/quotation-form.html?id={NO}")
    page.wait_for_selector(".qty-input", state="attached", timeout=15000)
    page.wait_for_function("() => !!document.querySelector('.form-left')", timeout=10000)


def _clicks_without_effect(page):
    """鍵盤也打不進去，且沒有會失敗的存檔鈕。"""
    before = page.input_value(".qty-input")
    page.evaluate("() => document.querySelector('.qty-input').focus()")
    page.keyboard.type("77")
    assert page.input_value(".qty-input") == before
    assert not page.get_by_role("button", name="儲存草稿").is_visible()


@pytest.mark.e2e
@pytest.mark.parametrize("status_tiers", [0, 1], ids=["待審核", "簽核中"])
def test_superadmin_who_is_not_the_approver_sees_readonly_form_and_banner(live_server, make_user, e2e_browser, status_tiers):
    sa, sp = make_user(username=f"pend_sa{status_tiers}", role="superadmin", modules=["quotation"])
    _set_mode(2)
    _seed(["pend_ap1", "pend_ap2"], signed=status_tiers)          # 簽核人是別人
    page = e2e_browser.new_page()
    inject_login(page, live_server, sa, sp)
    _open(page, live_server)
    page.wait_for_selector(BANNER, state="visible", timeout=10000)
    txt = page.inner_text(BANNER)
    assert "僅簽核人可編輯" in txt and ("待簽核" in txt or "簽核中" in txt), txt
    page.wait_for_function("() => document.querySelector('.qty-input').readOnly", timeout=5000)
    assert _is_locked(page) and page.get_attribute(".form-left", "data-approver-locked") == "1"
    _clicks_without_effect(page)


@pytest.mark.e2e
def test_applicant_sees_banner_readonly_and_the_recall_button(live_server, make_user, e2e_browser):
    ap, pw = make_user(username="sales_x", role="admin", modules=["quotation"])   # 與 _seed 的 requestedBy 同名＝申請人
    _set_mode(2)
    _seed(["pend_ap_other"])
    page = e2e_browser.new_page()
    inject_login(page, live_server, ap, pw)
    _open(page, live_server)
    page.wait_for_selector(BANNER, state="visible", timeout=10000)
    page.wait_for_function("() => document.querySelector('.qty-input').readOnly", timeout=5000)
    assert _is_locked(page)
    assert page.get_by_role("button", name="收回草稿").is_visible(), "橫幅說的出路（收回草稿）要真的在"
    _clicks_without_effect(page)


@pytest.mark.e2e
def test_current_approver_gets_no_banner_and_keeps_the_approver_toolbar(live_server, make_user, e2e_browser):
    """對照（牙齒）：簽核人本人行為不變——沒有橫幅、有簽核按鈕；欄位照舊預設鎖住（V3.39）。"""
    u, p = make_user(username="pend_me", role="admin", modules=["quotation"])
    _set_mode(2)
    _seed([u])
    page = e2e_browser.new_page()
    inject_login(page, live_server, u, p)
    _open(page, live_server)
    page.wait_for_selector('[data-testid="qf-approve-open-preview"]', state="visible", timeout=15000)
    assert not page.is_visible(BANNER), "簽核人本人不該看到『僅簽核人可編輯』"
    assert page.get_attribute(".form-left", "data-approver-locked") == "1"
