"""營運報表：期別下拉**顯示的**值，必須等於報表**實際算的**期別。

☠️ 2026-09-25（hichan-8d 查到）：切到「季」時季下拉的 DOM 值是 1、模型值是 3
⇒ 畫面顯示 Q1、報表算的是 Q3；使用者一動任何下拉（觸發 change），報表就被改成 Q1。
⇒ 看的人會把 Q3 的數字當成 Q1 —— 看錯季別的數字，比沒有數字更糟。

成因型態：`x-if` 裡的 `<select x-model>`，選項用 `:value`／`x-for` 產生；
x-model 先把值寫進 select，當下還沒有值相符的 option ⇒ 瀏覽器選第一個；
選項稍後才長出來，select 不會回頭重選。

量法：
- 每個看得到的 `select[x-model]`：DOM 選中的值 ＝ Alpine 模型值（通用掃描，同型的一起抓）；
- 期別列：下拉顯示的年／月／季組出來的期別 ＝ 送出的 `/api/reports/financial?period=`。
"""
import re

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login as _login  # noqa: E402,F401

from tests._e2e_select_model import MISMATCHES_JS as _MISMATCHES_JS  # noqa: E402



def _open(page, base):
    # 等頁面自己的第一個報表請求回來，下面切換時接到的才是切換送出的那一個
    with page.expect_response(lambda r: "/api/reports/financial?" in r.url, timeout=15000):
        page.goto(base + "/pages/reports.html")
    page.wait_for_function("() => window.Alpine && document.querySelector('.period-bar')", timeout=15000)


_PERIOD_RE = {"month": r"period=\d{4}-\d{2}(&|$)", "quarter": r"period=\d{4}-Q\d(&|$)",
              "year": r"period=\d{4}(&|$)"}


def _switch(page, label, kind):
    with page.expect_response(lambda r: "/api/reports/financial?" in r.url
                              and re.search(_PERIOD_RE[kind], r.url), timeout=15000) as resp:
        page.click(f".period-type-btn:text-is('{label}')")
    return resp.value.url


def _shown_period(page):
    """期別列上**看得到的**下拉組出來的期別（使用者眼睛看到的那一個）。"""
    return page.evaluate("""() => {
      const bar = document.querySelector('.period-bar')
      const sel = [...bar.querySelectorAll('select')].filter(s => s.offsetParent !== null)
      const txt = s => s.options[s.selectedIndex] ? s.options[s.selectedIndex].text : ''
      return sel.map(txt)
    }""")


@pytest.mark.e2e
@pytest.mark.parametrize("label,kind", [("月報", "month"), ("季報", "quarter"), ("年報", "year")])
def test_period_selects_show_what_the_report_is_computing(live_server, make_user, label, kind, e2e_browser):
    u, pw = make_user(username="rq_admin", role="superadmin")
    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, u, pw)
    _open(page, live_server)
    url = _switch(page, label, kind)
    period = url.split("period=")[1].split("&")[0]
    shown = _shown_period(page)
    assert page.evaluate(_MISMATCHES_JS) == [], (
        "下拉顯示的值與模型不同（畫面看到的不是報表算的）", shown, period)
    if kind == "quarter":
        year, q = period.split("-Q")
        assert shown[:2] == [year, "Q" + q], ("季報：下拉顯示", shown, "報表算的", period)
    elif kind == "month":
        year, m = period.split("-")
        assert shown[:2] == [year, "%d 月" % int(m)], ("月報：下拉顯示", shown, "報表算的", period)
    else:
        assert shown[:1] == [period + " 年"], ("年報：下拉顯示", shown, "報表算的", period)
    # 一動部門下拉（觸發 loadData）⇒ 期別不可以被下拉的錯值改掉
    with page.expect_response(lambda r: "/api/reports/financial?" in r.url, timeout=15000) as again:
        page.dispatch_event(".period-bar select[x-model='departmentId']", "change")
    assert again.value.url.split("period=")[1].split("&")[0] == period


@pytest.mark.e2e
@pytest.mark.parametrize("label,kind", [("月報", "month"), ("季報", "quarter"), ("年報", "year")])
def test_every_tab_shows_select_values_equal_to_the_model(live_server, make_user, label, kind, e2e_browser):
    """同型掃描：每一個分頁裡看得到的 `select[x-model]`，DOM 選中的值都要等於模型值
    （應收／應付／支出的年、季下拉會跟著頂部期別同步，選項來自非同步載入的年份清單）。"""
    u, pw = make_user(username="rq_admin2", role="superadmin")
    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, u, pw)
    _open(page, live_server)
    _switch(page, label, kind)
    bad = {}
    n = page.locator(".tab").count()
    assert n >= 5, "分頁按鈕找不到（選擇器失效就什麼都沒掃到）"
    for i in range(n):
        tab = page.locator(".tab").nth(i)
        if not tab.is_visible():
            continue
        name = tab.inner_text().strip()
        tab.click()
        page.wait_for_load_state("networkidle")
        got = page.evaluate(_MISMATCHES_JS)
        if got:
            bad[name] = got
    assert bad == {}, bad
