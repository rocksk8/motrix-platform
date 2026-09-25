"""出納的銀行對帳在「營運報表」模組（M08 analytics）不在時的訊息（M08 搬遷，主持裁示 A）。

銀行對帳目前由 M08 的 `/api/reports/bank-reconcile` 提供（M05 搬遷時收回）。M08 不在 ⇒ 路由不存在，POST 可能
落到靜態檔 mount 回 405（或 404）。出納頁要明說「需要營運報表模組」，不可以只跳 "Not Found"。
以 page.route 讓那一支回 404／405 模擬模組不在；正對照：伺服器回一般錯誤時照舊顯示伺服器的說明。
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
    assert msgs and "營運報表" in msgs[-1] and "Not Found" not in msgs[-1], msgs


@pytest.mark.e2e
def test_other_errors_still_show_the_server_detail(live_server, make_user, e2e_browser, tmp_path):
    """正對照：模組在、伺服器回 400 ⇒ 照舊顯示伺服器的說明（不可以一律講成模組不在）。"""
    msgs = _upload_and_get_alert(e2e_browser, live_server, make_user, tmp_path, "cash_bank_400", 400, "CSV 缺少金額欄位")
    assert msgs and "CSV 缺少金額欄位" in msgs[-1] and "營運報表" not in msgs[-1], msgs
