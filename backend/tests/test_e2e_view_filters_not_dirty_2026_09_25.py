"""W-8（2026-09-25）：改「看法」不是改「資料」——篩選／期間／圖層這類欄位改值後，不可以觸發離頁警告。

sidebar.js `_maybeSetDirty` 對所有 input／change 事件設 `window.motrixIsDirty = true`，只跳過
type=search／range 與 class 含 search／filter 的欄位。走查（D4-2 reports、D7-1 map）發現：只是換個月份
或關一個圖層，離開頁面就跳「尚未儲存」——那個警告一旦常常誤報，使用者就會習慣按「離開」，
等到真的有未存的資料時它就沒有用了。

做法：篩選欄在靜態 class 加 `filter`（不動 sidebar.js）。每頁兩個方向都驗：
- 篩選欄改值 ⇒ 仍然 not dirty
- 反向控制：同頁一個真的存檔欄位改值 ⇒ dirty（避免「整頁都標成 filter」而變綠）；
  沒有存檔欄位的頁（map）改用臨時插入的一般欄位證明監聽器是活的。
事件用 dispatchEvent 送到欄位本身：sidebar 是在 document capture 階段收，與使用者實際操作走同一條路，
而且不受「該欄位目前被 x-show 藏起來」影響（藏起來的欄位切到那個檢視時一樣會被操作）。
"""
import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402
from tests._map_tiles import block_tiles  # noqa: E402

from tests.test_e2e_material_orders_2026_09_11 import live_server, _login  # noqa: F401,E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))   # 單獨跑這個檔時 tests/ 不在 sys.path
from _mapiso import no_tile_probe  # noqa: E402,F401  （map 頁：後端會探測底圖伺服器）

ROOT = "Alpine.$data(document.querySelector('[x-data]'))"

# 以 x-model 綁定的名稱找欄位（x-model.number 之類的修飾字也要比到）
_FIRE = """([names, setup]) => {
  if (setup) eval(setup)
  const byModel = n => [...document.querySelectorAll('input,select,textarea')].filter(el =>
      [...el.attributes].some(a => a.name.split('.')[0] === 'x-model' && a.value === n))
  const missing = [], dirtied = []
  for (const n of names) {
    const els = byModel(n)
    if (!els.length) { missing.push(n); continue }
    for (const el of els) {
      window.motrixIsDirty = false
      el.dispatchEvent(new Event('input', { bubbles: true }))
      el.dispatchEvent(new Event('change', { bubbles: true }))
      if (window.motrixIsDirty) dirtied.push(n)
    }
  }
  window.motrixIsDirty = false
  return { missing, dirtied }
}"""

_CONTROL = """(saved) => {
  let el
  if (saved) {
    el = [...document.querySelectorAll('input,select,textarea')].find(e =>
        [...e.attributes].some(a => a.name.split('.')[0] === 'x-model' && a.value === saved))
    if (!el) return 'missing ' + saved
  } else {
    el = document.createElement('input'); el.type = 'text'; document.body.appendChild(el)
  }
  window.motrixIsDirty = false
  el.dispatchEvent(new Event('input', { bubbles: true }))
  const r = window.motrixIsDirty
  window.motrixIsDirty = false
  return r
}"""

# (頁面, 篩選欄 x-model 名稱, 反向控制用的存檔欄位（None ＝ 用臨時插入的欄位）, 讓 x-if 裡的欄位渲染出來的 setup)
PAGES = [
    ("reports",
     ["year", "month", "quarter", "departmentId", "receivablesMonth", "receivablesYear", "receivablesQuarter",
      "expensesMonth", "expensesYear", "expensesQuarter", "caseListYear", "custSort", "taxExportYear", "taxExportMonth"],
     "targetForm.annual.revenue",
     None),
    ("map", ["picked", "nearN"], None, None),
    ("cashier", ["cashierHistoryStart", "cashierHistoryEnd", "t100Start", "t100End"], "receiveNote", None),
    ("payslips", ["filterMonth"], None, None),
    ("shipping-export-history", ["filterYear", "filterMonth"], None, None),
    ("audit-log", ["filterAction"], None, None),
    ("contractors", ["showInactive"], "form.name", None),
    ("vendor-contractors", ["showInactive", "taxIdSearch"], "form.name", None),
    ("customers", ["taxIdSearch"], "form.name", None),
    ("suppliers", ["taxIdSearch"], "form.name", None),
    ("payslip-form", ["conSearch"], "q.companyName", None),
    ("approval-history", ["q"], None, None),
]

# reports 的期間下拉分別包在 x-if（月／季／年）裡，一次只渲染一組 ⇒ 三種範圍各跑一次
REPORT_SCOPES = ["month", "quarter", "year"]



def _rendered(page):
    """PERF #6：等 Alpine 把這次狀態變化畫完（nextTick）＋瀏覽器實際畫出兩個影格。
    ⚠️ 只適用於沒有 CSS transition 的元素（有 transition 的要等轉場落定）。"""
    page.evaluate("() => new Promise(r => (window.Alpine ? Alpine.nextTick : (f => f()))(() => requestAnimationFrame(() => requestAnimationFrame(r))))")

def _open(page, base, pg):
    page.goto(f"{base}/pages/{pg}.html")
    page.wait_for_function("() => typeof window.motrixIsDirty !== 'undefined' || document.readyState === 'complete'",
                           timeout=20000)
    page.wait_for_function(f"() => window.Alpine && {ROOT}", timeout=20000)
    _rendered(page)   # PERF #6：原本固定等 300ms


@pytest.mark.e2e
@pytest.mark.parametrize("pg,filters,saved,setup", PAGES, ids=[p[0] for p in PAGES])
def test_changing_a_view_filter_does_not_arm_the_leave_warning(live_server, make_user, request, pg, filters, saved, setup):
    if pg == "map":
        request.getfixturevalue("no_tile_probe")
    u = make_user(username="w8_" + pg.replace("-", "_"), role="superadmin")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_context().new_page()
            block_tiles(page)   # map 頁的底圖圖磚不連外（conftest._browser_netguard）
            _login(page, live_server, *u)
            _open(page, live_server, pg)
            seen_missing = set(filters)
            dirtied = set()
            runs = [None] if pg != "reports" else [
                # ⚠ 走頁面自己的切換入口（switchType／按鈕的 scope＋load）。第一版直接寫 periodType：
                #   飛行中的回應全被 loadData 的過期丟棄機制丟掉、沒有人重新載入 ⇒ loading 永遠 true，
                #   看起來像產品競態，其實是探針繞過了入口。
                "(d => { d.switchType('%s'); d.receivablesScope = '%s'; d.loadReceivables();"
                " d.expensesScope = '%s'; d.loadExpenses(); d.caseListGroupByMonth = true })(%s)"
                % (s, s, s, ROOT) for s in REPORT_SCOPES] + [
                # 稅務匯出的年／月下拉在「資金水位」分頁的 x-if="cashPos && !cashPosLoading" 裡
                "%s.showCashPosTab()" % ROOT]
            for s in runs:
                if s:
                    page.evaluate("(s) => eval(s)", s)
                    # 收支／應收那幾組包在 x-if="!loading && data" 裡
                    page.wait_for_function(f"() => !{ROOT}.loading && !!{ROOT}.data"
                                           + (f" && !!{ROOT}.cashPos && !{ROOT}.cashPosLoading" if "CashPos" in s else ""),
                                           timeout=20000)
                    _rendered(page)   # PERF #6：原本固定等 150ms
                r = page.evaluate(_FIRE, [filters, setup])
                seen_missing &= set(r["missing"])
                dirtied |= set(r["dirtied"])
            assert not seen_missing, "頁面上找不到這些篩選欄（名稱改了？）：%s" % sorted(seen_missing)
            assert not dirtied, "改這些篩選欄會觸發離頁警告：%s" % sorted(dirtied)
            assert page.evaluate(_CONTROL, saved) is True, "反向控制：存檔欄位改值應該要觸發離頁警告"
        finally:
            browser.close()
