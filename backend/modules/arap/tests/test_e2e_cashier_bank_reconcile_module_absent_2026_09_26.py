"""出納頁的銀行對帳在「端點不在」或「對方模組不在」時的訊息（2026-09-26 M05 搬遷：銀行對帳自 M08 收回 M05）。

〔沿革〕原檔 tests/test_e2e_cashier_bank_reconcile_without_analytics_2026_09_26.py 驗的是「M08 不在 ⇒ 說需要營運報表」；
銀行對帳收回 M05 之後，端點與出納頁同一個模組 ⇒ 前提改變，改驗：
① 路由不存在（404 "Not Found"／405）⇒ 說「需要應收應付模組」、不顯示 "Not Found"
② 端點回 404 並帶說明（M04 外包工班不在 ⇒ 沒有承攬商匯款申請可比對）⇒ 照伺服器的說明顯示
③ 正對照：一般錯誤（400）照舊顯示伺服器的說明
以 page.route 讓那一支回指定狀態碼。
"""
import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402


def _upload_and_get_alert(e2e_browser, live_server, make_user, tmp_path, name, status, detail):
    u = make_user(username=name, role="superadmin")
    page = e2e_browser.new_context().new_page()
    page.route("**/api/reports/bank-reconcile", lambda route: route.fulfill(
        status=status, body='{"detail":"%s"}' % detail, content_type="application/json"))
    inject_login(page, live_server, u[0], u[1])
    page.goto(f"{live_server}/pages/cashier.html")
    page.wait_for_function("() => { const el = document.querySelector('[x-data]'); return el && Alpine.$data(el) }",
                           timeout=15000)
    page.evaluate("() => { Alpine.$data(document.querySelector('[x-data]')).cashierSub = 'bank' }")
    csv = tmp_path / "bank.csv"
    csv.write_text("日期,金額\n2026-09-01,100\n", encoding="utf-8")
    # 終點＝彈窗本身（bankReconciling 初值就是 false，拿它當終點會在上傳開始前就通過）
    with page.expect_event("dialog", timeout=15000) as ev:
        page.set_input_files("input[type=file][accept='.csv']", str(csv))
    msg = ev.value.message
    ev.value.dismiss()
    return [msg]


@pytest.mark.e2e
@pytest.mark.parametrize("status", [404, 405])
def test_missing_module_says_which_module_is_needed(live_server, make_user, e2e_browser, tmp_path, status):
    msgs = _upload_and_get_alert(e2e_browser, live_server, make_user, tmp_path, "cash_bank_%d" % status, status,
                                 "Not Found" if status == 404 else "Method Not Allowed")
    assert msgs and "應收應付" in msgs[-1] and "Not Found" not in msgs[-1] and "Method Not Allowed" not in msgs[-1], msgs


@pytest.mark.e2e
def test_detail_from_the_endpoint_is_shown_when_m04_is_absent(live_server, make_user, e2e_browser, tmp_path):
    """端點在、但 M04 不在 ⇒ 404 帶 CONTRACTOR_MISSING ⇒ 照這一句顯示（不是講成「需要應收應付模組」）。"""
    from modules.arap.api import cashier
    msgs = _upload_and_get_alert(e2e_browser, live_server, make_user, tmp_path, "cash_bank_m04", 404, cashier.CONTRACTOR_MISSING)
    assert msgs and cashier.CONTRACTOR_MISSING in msgs[-1] and "應收應付」模組" not in msgs[-1], msgs


@pytest.mark.e2e
def test_other_errors_still_show_the_server_detail(live_server, make_user, e2e_browser, tmp_path):
    """正對照：模組在、伺服器回 400 ⇒ 照舊顯示伺服器的說明（不可以一律講成模組不在）。"""
    msgs = _upload_and_get_alert(e2e_browser, live_server, make_user, tmp_path, "cash_bank_400", 400, "CSV 缺少金額欄位")
    assert msgs and "CSV 缺少金額欄位" in msgs[-1] and "應收應付" not in msgs[-1], msgs
