"""瀏覽器端對端：案件頁存檔要排隊——同一頁兩次存檔同時在途，不可以自己跟自己 409（2026-09-24）。

hichan-0a 查到的產品競態（test_e2e_case_invoice_amounts 在 -n 5 回歸偶發紅）：
```
輸入 ⇒ 1.5 秒自動存檔（在途）⇒ 使用者立刻按「儲存」⇒ 第二次存檔
第二次帶的 base 仍是第一次送出前的 _segBase（第一次還沒回來、基準還沒更新）
⇒ 兩次在伺服器上互相比對 ⇒ 後到的那一次 409「已被他人更新」——而他人就是自己
```
⚠️ 使用者真實情境：打完字等一下再按儲存。另外切換案件、結案、附件等單筆操作前也會先存。

題：攔住第一次存檔的請求，在它回來之前改內容再按「儲存」，然後放行。
- 不可以出現任何 409
- 資料庫是最後打的那一版
觀測點打在回應碼與資料庫落地值。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_e2e_case_concurrent_edit_2026_09_24 import (  # noqa: F401  (live_server 是 fixture)
    DATA_JS, NOTE_INPUT, NO, _cr, _login, _seed,
)
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


@pytest.mark.e2e
def test_a_save_while_another_is_in_flight_does_not_conflict_with_itself(live_server, make_user, e2e_browser):
    u = make_user(username="ser_sa", role="superadmin")
    _seed()
    browser = e2e_browser
    page = browser.new_context(viewport={"width": 1400, "height": 1000}).new_page()
    page.on("dialog", lambda d: d.accept())
    _login(page, live_server, *u)
    page.goto(f"{live_server}/pages/case-management.html?q={NO}&tab=fin")
    page.locator(NOTE_INPUT).first.wait_for(state="visible", timeout=20000)
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}'",
                           timeout=10000)

    statuses = []
    page.on("response", lambda r: statuses.append(r.status)
            if r.url.endswith("/case-record") and r.request.method == "PATCH" else None)
    held = []

    def hold_first(route):
        if not held:
            held.append(route)       # 第一次：攔住，模擬「還在途中」
        else:
            route.continue_()
    page.route("**/case-record", hold_first)

    note = page.locator(NOTE_INPUT).first
    note.fill("第一版")
    page.evaluate(f"() => {{ {DATA_JS}.saveCaseRecord() }}")   # 不 await：讓它掛在途中
    for _ in range(200):
        if held:
            break
        page.wait_for_timeout(50)
    assert held, "第一次存檔沒有送出（前提不成立）"

    note.fill("第二版")
    page.evaluate(f"() => {{ {DATA_JS}.manualSave() }}")       # 使用者按「儲存」
    page.wait_for_timeout(300)                                  # 讓第二次有機會送出（若實作沒排隊）
    held[0].continue_()

    page.wait_for_function(f"() => !{DATA_JS}.saving && !{DATA_JS}.dirty", timeout=20000)
    page.wait_for_timeout(300)
    assert 409 not in statuses, "同一頁的兩次存檔互相 409：%r" % statuses
    assert page.evaluate(f"() => {DATA_JS}.segConflict") is None
    assert _cr()["payment"]["items"][0]["note"] == "第二版", "資料庫要是最後打的那一版"
