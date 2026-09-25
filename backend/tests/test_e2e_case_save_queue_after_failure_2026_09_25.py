"""存檔排隊：在途的一次失敗之後，使用者之後按的「儲存」不可以被吞掉。

☠️ 2026-09-25（hichan-bf 查 invoice 偶發紅時看到）：存檔一律排隊，在途時再呼叫只標記「再存一次」；
   原本「某一次失敗就停」⇒ 在途的是只填一欄時觸發的自動存檔（伺服器 400「要一起填寫」），
   使用者補完另一欄按「儲存」，這一按被吞掉，畫面只顯示前一次的錯誤，資料沒進資料庫。
🔑 在一次嘗試期間有新的存檔請求 ⇒ 不論那一次成敗，都用**最新狀態**再送一次；沒有新請求才停（不會無限重送）。
觀測點打在資料庫落地值。
"""
import pytest

pytest.importorskip("playwright.sync_api")
from tests.test_e2e_case_concurrent_edit_2026_09_24 import DATA_JS  # noqa: E402
from tests.test_case_money_mask_2026_09_24 import _db_data, _seed  # noqa: E402
from tests.test_e2e_case_invoice_amounts_2026_09_24 import PRETAX, TAX, _open  # noqa: E402


@pytest.mark.e2e
def test_a_save_pressed_while_a_failing_save_is_in_flight_is_not_swallowed(live_server, make_user, e2e_browser):
    u = make_user(username="queue_fail", role="sales")
    _seed(assigned=[u[0]])
    page = _open(e2e_browser, live_server, u)
    held, statuses = [], []

    def hold_first_patch(route):
        if route.request.method == "PATCH" and "/case-record" in route.request.url and not held:
            held.append(route)            # 第一次（只填一欄）先攔住
        else:
            route.continue_()
    page.route("**/api/quotations/**", hold_first_patch)
    page.on("response", lambda r: statuses.append(r.status)
            if r.request.method == "PATCH" and "/case-record" in r.url else None)

    page.locator(PRETAX).nth(1).fill("6000")
    page.evaluate(f"() => {{ const c = {DATA_JS}; clearTimeout(c._autoSaveTimer); window.__first = c.saveCaseRecord() }}")
    for _ in range(100):
        if held:
            break
        page.wait_for_timeout(50)
    assert held, "第一次存檔沒有送出（探針失效）"

    page.locator(TAX).nth(1).fill("300")
    page.evaluate(f"() => {{ const c = {DATA_JS}; clearTimeout(c._autoSaveTimer); window.__manual = c.manualSave() }}")
    held[0].continue_()                   # 讓伺服器真的回 400（只填一欄）
    state = page.evaluate(f"""async () => {{ await window.__manual; const c = {DATA_JS};
        return {{ st: c.saveStatus, msg: c.saveMsg, dirty: c.dirty }} }}""")

    assert statuses and statuses[0] == 400, "前提：第一次（只填一欄）應該被伺服器擋下：%s" % statuses
    items = _db_data()["caseRecord"]["payment"]["items"]
    assert (items[1].get("invoicePretax"), items[1].get("invoiceTax")) == (6000, 300), \
        "在途存檔失敗後，使用者按的「儲存」被吞掉了：%s %s" % (state, statuses)
    assert state["st"] == "saved" and not state["dirty"], state
