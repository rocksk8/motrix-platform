# -*- coding: utf-8 -*-
"""T65 C2 案件清單個人檢視偏好／頁籤組合 ON 狀態：真瀏覽器＋真的設定 API。
場景：版面旗標＋list_view 開啟 ⇒ 面板出現；選預設頁籤「已結案」＋每次載入 25 件 ⇒ 儲存 ⇒ 重新載入仍套用；還原預設 ⇒ 回「進行中」＋100 件；
合併「已成案」頁籤 ⇒ 該頁籤消失、其他三個仍在；預設（選項全 0）四個頁籤都在。
"""
import pytest

from tests._requires import requires_module
from tests.e2e_on_state._common import DATA_JS, inject_login, seed_case, set_flag, token_of

pytestmark = [pytest.mark.e2e, requires_module("case", "案件管理頁")]

TABS_JS = "() => [...document.querySelectorAll('.cm-list__tab')].filter(b => b.offsetParent !== null).map(b => b.textContent.trim().split(/\\s+/)[0])"


def _open(page, base, user):
    inject_login(page, base, user[0], user[1])
    page.goto(base + "/pages/case-management.html")
    page.wait_for_function("() => %s.cases !== undefined && %s.loading === false" % (DATA_JS, DATA_JS), timeout=20000)


def test_c2_default_has_four_tabs_and_options_do_nothing_when_off(live_server, make_user, new_context):
    u = make_user(username="on_lc0", role="superadmin")
    ctx = new_context()
    token_of(ctx, live_server, u)
    seed_case("MQ-ONLC-000")
    page = ctx.new_page()
    _open(page, live_server, u)
    assert page.evaluate(TABS_JS) == ["進行中", "已成案", "已結案", "待精算"]
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
    page.get_by_test_id("lv-save").click()
    page.wait_for_function("() => %s.casePageSize === 25" % DATA_JS, timeout=15000)
    page.wait_for_timeout(1000)                                                                # 讓 PUT 完成再重新載入
    page.reload()
    page.wait_for_function("() => %s.listTab === '已結案' && %s.casePageSize === 25" % (DATA_JS, DATA_JS), timeout=20000)
    # 還原預設
    page.get_by_test_id("lv-toggle").click()
    page.get_by_test_id("lv-panel").wait_for(state="visible", timeout=5000)
    page.get_by_text("還原預設").click()
    page.wait_for_function("() => %s.casePageSize === 100" % DATA_JS, timeout=15000)
    # 合併重複的「已成案」頁籤（公司層）：只剩三個；其他頁籤仍在
    set_flag(ctx, live_server, tk, "list_view", "cases_merge_won_tab", 1, as_int=True)
    page.reload()
    page.wait_for_function("() => %s.lvOn && %s.lvOn.mergeWon === true" % (DATA_JS, DATA_JS), timeout=20000)
    page.wait_for_function("(js) => eval(js)().length === 3", arg=TABS_JS, timeout=10000)
    assert page.evaluate(TABS_JS) == ["進行中", "已結案", "待精算"]
