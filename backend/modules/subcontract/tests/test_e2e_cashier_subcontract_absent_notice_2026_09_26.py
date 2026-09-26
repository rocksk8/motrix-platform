"""需要外包工班（M04）的題：刪掉 modules/subcontract 時隨模組消失（PLAYBOOK §B-11，稽核 D M04-M1）。

（2026-09-26 自 tests/test_e2e_cashier_subcontract_absent_notice_2026_09_26.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
瀏覽器端對端：外包工班（IP-14）不在時，出納頁要說出原因（2026-09-26 外包工班搬遷）。

後端：待付款回 404＋原因、執行歷史帶 contractorNotice。畫面原本只處理 403，其他錯誤安靜地當成「沒有待匯款」
⇒ 使用者看到「目前沒有待匯款的申請」，而實際是整個功能不在。
正對照：外包工班在 ⇒ 沒有這兩句說明。觀測點打在後端給的那一句（常數），不打在頁面寫死的文字。
"""
import pytest

pytest.importorskip("playwright.sync_api")

from core import registry  # noqa: E402

#: 2026-09-26 M05 搬遷：下列題同時需要應收應付（出納／收款資料）
_NEEDS_ARAP = pytest.mark.skipif(not __import__("core.source_tree", fromlist=["x"]).module_installed("modules/arap/"),
                                 reason="需要應收應付（M05）：模組不在這個安裝包（PLAYBOOK §B-11）")

DATA = "Alpine.$data(document.querySelector('[x-data]'))"


def _open_cashier(live_server, make_user, new_page, login_as, name):
    user = make_user(username=name, role="superadmin")
    page = new_page()
    login_as(page, tuple(user)[:2])
    page.goto(f"{live_server}/pages/cashier.html")
    page.wait_for_function(f"() => {DATA} && {DATA}.cashierLoaded === true", timeout=20000)
    return page


@_NEEDS_ARAP
@pytest.mark.e2e
def test_no_notice_when_subcontract_is_present(live_server, make_user, new_page, login_as):
    page = _open_cashier(live_server, make_user, new_page, login_as, "e2e_ip14_present")
    assert page.evaluate(f"() => {DATA}.payableNotice") == ""
    assert page.evaluate(f"() => {DATA}.cashierHistoryContractorNotice") == ""
