"""瀏覽器端對端：外包工班（IP-14）不在時，出納頁要說出原因（2026-09-26 外包工班搬遷）。

後端：待付款回 404＋原因、執行歷史帶 contractorNotice。畫面原本只處理 403，其他錯誤安靜地當成「沒有待匯款」
⇒ 使用者看到「目前沒有待匯款的申請」，而實際是整個功能不在。
正對照：外包工班在 ⇒ 沒有這兩句說明。觀測點打在後端給的那一句（常數），不打在頁面寫死的文字。
"""
import pytest

pytest.importorskip("playwright.sync_api")

from core import registry  # noqa: E402

DATA = "Alpine.$data(document.querySelector('[x-data]'))"


def _open_cashier(live_server, make_user, new_page, login_as, name):
    user = make_user(username=name, role="superadmin")
    page = new_page()
    login_as(page, tuple(user)[:2])
    page.goto(f"{live_server}/pages/cashier.html")
    page.wait_for_function(f"() => {DATA} && {DATA}.cashierLoaded === true", timeout=20000)
    return page


@pytest.mark.e2e
def test_payable_tab_says_why_when_subcontract_is_absent(live_server, make_user, new_page, login_as, monkeypatch):
    from routers import cashier as ca
    orig = registry.providers
    monkeypatch.setattr(registry, "providers", lambda c: {} if c == "contractor_voucher.public" else orig(c))
    page = _open_cashier(live_server, make_user, new_page, login_as, "e2e_ip14_absent")
    assert page.evaluate(f"() => {DATA}.payableNotice") == ca.CONTRACTOR_MISSING
    page.evaluate(f"() => {{ {DATA}.cashierSub = 'payable' }}")
    page.wait_for_function(f"() => [...document.querySelectorAll('.alert-bar')].some(e => e.offsetParent && e.textContent.trim() === {repr(ca.CONTRACTOR_MISSING)})", timeout=10000)
    assert page.evaluate(f"() => {DATA}.cashierHistoryContractorNotice") == ca.CONTRACTOR_MISSING


@pytest.mark.e2e
def test_no_notice_when_subcontract_is_present(live_server, make_user, new_page, login_as):
    page = _open_cashier(live_server, make_user, new_page, login_as, "e2e_ip14_present")
    assert page.evaluate(f"() => {DATA}.payableNotice") == ""
    assert page.evaluate(f"() => {DATA}.cashierHistoryContractorNotice") == ""
