# -*- coding: utf-8 -*-
"""T65 C2 案件清單個人檢視偏好／頁籤組合 ON 狀態：真瀏覽器＋真的設定 API。
場景：版面旗標＋list_view 開啟 ⇒ 面板出現；選預設頁籤「已結案」＋每次載入 25 件 ⇒ 儲存 ⇒ 重新載入仍套用；還原預設 ⇒ 回「進行中」＋100 件；
預設（T86 起）合併「已成案」頁籤 ⇒ 只有 進行中／已結案／待精算；公司在設定中心明確存 0 ⇒ 四個頁籤都在。
"""
import pytest

from tests._requires import requires_module
from tests.e2e_on_state._common import DATA_JS, inject_login, seed_case, set_flag, token_of

pytestmark = [pytest.mark.e2e, requires_module("case", "案件管理頁")]

TABS_JS = "() => [...document.querySelectorAll('.cm-list__tab')].filter(b => b.offsetParent !== null).map(b => b.textContent.trim().split(/\\s+/)[0])"


def _is_pref_put(r):
    return r.request.method == "PUT" and "/api/list-prefs/case_list.view" in r.url


def _open(page, base, user):
    inject_login(page, base, user[0], user[1])
    page.goto(base + "/pages/case-management.html")
    page.wait_for_function("() => %s.cases !== undefined && %s.loading === false" % (DATA_JS, DATA_JS), timeout=20000)


def test_c2_default_merges_won_tab_and_options_do_nothing_when_off(live_server, make_user, new_context):
    u = make_user(username="on_lc0", role="superadmin")
    ctx = new_context()
    token_of(ctx, live_server, u)
    seed_case("MQ-ONLC-000")
    page = ctx.new_page()
    _open(page, live_server, u)
    page.wait_for_function("(js) => eval(js)().length === 3", arg=TABS_JS, timeout=20000)
    assert page.evaluate(TABS_JS) == ["進行中", "已結案", "待精算"]
    assert page.evaluate("() => %s.casePageSize" % DATA_JS) == 100
    assert page.get_by_test_id("lv-toggle").count() == 1 and not page.get_by_test_id("lv-toggle").is_visible()


def test_c2_personal_prefs_persist_and_merge_won_tab(live_server, make_user, new_context):
    u = make_user(username="on_lc1", role="superadmin")
    ctx = new_context()
    tk = token_of(ctx, live_server, u)
    seed_case("MQ-ONLC-001")
    set_flag(ctx, live_server, tk, "builder_layout", "case_management", 1)
    for f in ("cases_personal_default_tab", "cases_personal_page_size"):
        set_flag(ctx, live_server, tk, "list_view", f, 1, as_int=True)
    page = ctx.new_page()
    _open(page, live_server, u)
    page.wait_for_function("() => %s.lvOn && %s.lvOn.tab === true && %s.lvOn.size === true" % (DATA_JS, DATA_JS, DATA_JS), timeout=20000)
    page.get_by_test_id("lv-toggle").click()
    page.get_by_test_id("lv-panel").wait_for(state="visible", timeout=5000)
    page.evaluate("() => { const d = %s; d.pv = { ...d.pv, tab: '已結案', size: 25 } }" % DATA_JS)
    with page.expect_response(_is_pref_put, timeout=15000) as put:                             # 等真正的 PUT 回應，不靠固定睡眠（T87：負載下 1 秒不夠）
        page.get_by_test_id("lv-save").click()
    assert put.value.ok, "偏好 PUT 沒成功：%s" % put.value.status
    page.wait_for_function("() => %s.casePageSize === 25" % DATA_JS, timeout=15000)
    page.reload()
    page.wait_for_function("() => %s.listTab === '已結案' && %s.casePageSize === 25" % (DATA_JS, DATA_JS), timeout=20000)
    # 還原預設
    page.get_by_test_id("lv-toggle").click()
    page.get_by_test_id("lv-panel").wait_for(state="visible", timeout=5000)
    with page.expect_response(_is_pref_put, timeout=15000) as put2:
        page.get_by_text("還原預設").click()
    assert put2.value.ok, "還原預設的 PUT 沒成功：%s" % put2.value.status
    page.wait_for_function("() => %s.casePageSize === 100" % DATA_JS, timeout=15000)
    # 預設已合併：只有三個頁籤
    page.wait_for_function("(js) => eval(js)().length === 3", arg=TABS_JS, timeout=20000)
    assert page.evaluate(TABS_JS) == ["進行中", "已結案", "待精算"]
    # 公司明確存 0（想分開顯示）⇒ 四個頁籤都在（已經存過 0 的正式機不會跟著預設變）
    set_flag(ctx, live_server, tk, "list_view", "cases_merge_won_tab", 0, as_int=True)
    page.reload()
    page.wait_for_function("() => %s.lvOn && %s.lvOn.mergeWon === false" % (DATA_JS, DATA_JS), timeout=20000)
    page.wait_for_function("(js) => eval(js)().length === 4", arg=TABS_JS, timeout=20000)
    assert page.evaluate(TABS_JS) == ["進行中", "已成案", "已結案", "待精算"]


def test_c2_failed_save_does_not_change_the_page_and_says_so(live_server, make_user, new_context):
    """T87：伺服器存不進去時，畫面不能先把每頁筆數改掉（之前會：畫面 25 件、伺服器還是預設，重新整理又跳回去）。"""
    u = make_user(username="on_lc2", role="superadmin")
    ctx = new_context()
    tk = token_of(ctx, live_server, u)
    seed_case("MQ-ONLC-002")
    set_flag(ctx, live_server, tk, "builder_layout", "case_management", 1)
    set_flag(ctx, live_server, tk, "list_view", "cases_personal_page_size", 1, as_int=True)
    page = ctx.new_page()
    _open(page, live_server, u)
    page.wait_for_function("() => %s.lvOn && %s.lvOn.size === true" % (DATA_JS, DATA_JS), timeout=20000)
    page.route("**/api/list-prefs/case_list.view", lambda route: route.fulfill(status=500, body="{}") if route.request.method == "PUT" else route.continue_())
    page.get_by_test_id("lv-toggle").click()
    page.get_by_test_id("lv-panel").wait_for(state="visible", timeout=5000)
    page.evaluate("() => { const d = %s; d.pv = { ...d.pv, size: 25 } }" % DATA_JS)
    with page.expect_response(_is_pref_put, timeout=15000):
        page.get_by_test_id("lv-save").click()
    page.get_by_text("儲存失敗，設定沒有改變").wait_for(state="visible", timeout=10000)
    assert page.evaluate("() => %s.casePageSize" % DATA_JS) == 100, "沒存成功就不能改每頁筆數"
    assert page.evaluate("() => %s.pv.size" % DATA_JS) == 25, "使用者在面板上改的值留著，可以直接再按一次儲存"


def test_c2_panel_is_not_offered_until_saved_prefs_are_loaded(live_server, make_user, new_context):
    """T87 c2 偶發紅燈的根因：旗標讀到就顯示面板、但個人偏好還在讀 ⇒ 使用者（或測試）在這段空窗改的值，會被稍後讀回的偏好整個蓋掉。
    決定式重現：把偏好的 GET 拖慢 2 秒——這段時間面板入口不可見；讀回之後改的值照樣存得進去。"""
    import time
    u = make_user(username="on_lc3", role="superadmin")
    ctx = new_context()
    tk = token_of(ctx, live_server, u)
    seed_case("MQ-ONLC-003")
    set_flag(ctx, live_server, tk, "builder_layout", "case_management", 1)
    set_flag(ctx, live_server, tk, "list_view", "cases_personal_page_size", 1, as_int=True)
    page = ctx.new_page()

    def slow_get(route):
        if route.request.method == "GET":
            time.sleep(2)
        route.continue_()

    page.route("**/api/list-prefs/case_list.view", slow_get)
    _open(page, live_server, u)
    page.wait_for_function("() => %s.lvOn && %s.lvOn.size === true" % (DATA_JS, DATA_JS), timeout=20000)
    assert not page.get_by_test_id("lv-toggle").is_visible(), "偏好還沒讀回來，不該開放面板"
    page.get_by_test_id("lv-toggle").wait_for(state="visible", timeout=15000)
    assert page.evaluate("() => %s.lvReady" % DATA_JS) is True
    page.get_by_test_id("lv-toggle").click()
    page.evaluate("() => { const d = %s; d.pv = { ...d.pv, size: 25 } }" % DATA_JS)
    with page.expect_response(_is_pref_put, timeout=15000) as put:
        page.get_by_test_id("lv-save").click()
    assert put.value.ok
    page.wait_for_function("() => %s.casePageSize === 25" % DATA_JS, timeout=15000)
