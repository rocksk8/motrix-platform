"""瀏覽器端對端：案件頁 CU6（標明即時儲存／按儲存、即時儲存成功閃 ✓）與 CU7（label 綁欄位、必填 *、
勾已收款當下提示填日期）——2026-09-24 使用者表單。

觀測點：
- 區塊標題旁的標記由 `data-save-mode` 決定（不打在寫死的文字上）
- ✓ 只在**伺服器回成功之後**才出現（flashSaved 掛在成功分支）
- label 的 for 指得到真的輸入框（點 label ⇒ 焦點落到那一格）
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_e2e_case_concurrent_edit_2026_09_24 import (  # noqa: F401  (live_server 是 fixture)
    DATA_JS, NOTE_INPUT, _login,
)
from tests.test_case_money_mask_2026_09_24 import NO, _seed
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


def _open(browser, base, user, tab=""):
    page = browser.new_context(viewport={"width": 1400, "height": 1000}).new_page()
    page.on("dialog", lambda d: d.accept())
    _login(page, base, *user)
    page.goto(f"{base}/pages/case-management.html?q={NO}" + (f"&tab={tab}" if tab else ""))
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}'", timeout=20000)
    return page


def _mode_after(page, title):
    """標題旁的儲存方式標記：標題元素本身或其後的兄弟裡第一個 [data-save-mode]。"""
    return page.evaluate("""(t) => {
      const el = [...document.querySelectorAll('.cm-section-title')].find(e => e.textContent.trim().startsWith(t));
      if (!el) return 'NO-TITLE';
      const inside = el.querySelector('[data-save-mode]');
      if (inside) return inside.dataset.saveMode;
      let n = el.nextElementSibling;
      while (n && !n.matches('[data-save-mode]')) n = n.nextElementSibling;
      return n ? n.dataset.saveMode : 'NONE';
    }""", title)


@pytest.mark.e2e
def test_section_titles_say_how_they_save(live_server, make_user, e2e_browser):
    u = make_user(username="cu6_sa", role="superadmin")
    _seed(assigned=[u[0]])
    browser = e2e_browser
    page = _open(browser, live_server, u)
    page.locator(".cm-section-title:has-text('人員角色')").wait_for(timeout=15000)
    got = {t: _mode_after(page, t) for t in (
        "人員角色", "專案期間", "收款管理", "承攬商派發管理", "額外支出", "叫料（材料訂購）", "出貨單管理", "完工單管理")}
    assert got == {"人員角色": "auto", "專案期間": "auto", "收款管理": "auto", "承攬商派發管理": "manual",
                   "額外支出": "manual", "叫料（材料訂購）": "manual", "出貨單管理": "manual",
                   "完工單管理": "manual"}, got


@pytest.mark.e2e
def test_auto_save_flashes_a_tick_only_after_the_server_says_ok(live_server, make_user, e2e_browser):
    u = make_user(username="cu6_sa2", role="superadmin")
    _seed(assigned=[u[0]])
    browser = e2e_browser
    page = _open(browser, live_server, u, tab="fin")
    page.locator(NOTE_INPUT).first.wait_for(state="visible", timeout=20000)
    tick = page.locator('[data-testid="fin-payment"] [data-testid="flash-case"]')
    # 伺服器拒絕 ⇒ 不可以閃 ✓
    page.route("**/api/quotations/*/case-record*", lambda r: r.fulfill(status=500, body='{"detail":"x"}'))
    page.locator(NOTE_INPUT).nth(1).fill("先失敗")
    page.wait_for_function(f"() => {DATA_JS}.saveStatus === 'error'", timeout=15000)
    assert tick.is_hidden(), "存檔失敗不可以顯示「已存」"
    page.unroute("**/api/quotations/*/case-record*")
    page.locator(NOTE_INPUT).nth(1).fill("再成功")
    tick.wait_for(state="visible", timeout=15000)
    tick.wait_for(state="hidden", timeout=5000)


@pytest.mark.e2e
def test_labels_point_at_real_fields_and_ticking_received_prompts_for_the_date(live_server, make_user, e2e_browser):
    u = make_user(username="cu7_sa", role="superadmin")
    _seed(assigned=[u[0]])
    browser = e2e_browser
    page = _open(browser, live_server, u, tab="fin")
    page.locator(NOTE_INPUT).first.wait_for(state="visible", timeout=20000)
    dangling = page.evaluate("""() => [...document.querySelectorAll('[data-testid="fin-payment"] label[for]')]
        .filter(l => !document.getElementById(l.htmlFor)).map(l => l.htmlFor)""")
    assert dangling == [], dangling
    n = page.evaluate("""() => document.querySelectorAll('[data-testid="fin-payment"] label.fi-label[for]').length""")
    assert n >= 10, "款項明細的欄位標籤要綁到欄位（正對照：至少兩期 × 5 格）"
    page.locator('[data-testid="fin-payment"] label[for$="-note"]').nth(1).click()
    assert page.evaluate("() => document.activeElement.placeholder") == "收款備註..."

    # 第二期原本未收款：勾下去的當下 ⇒ 游標到收款日期、框紅、出現必填 *
    page.locator('[data-testid="pay-received-1"]').check()
    date = page.locator('[data-testid="pay-received-at-1"]')
    page.wait_for_function("() => document.activeElement && document.activeElement.dataset.testid === 'pay-received-at-1'",
                           timeout=5000)
    assert "fi--need" in (date.get_attribute("class") or "")
    assert date.get_attribute("aria-required") == "true"
    date.fill("2026-09-20")
    page.wait_for_function("() => !document.querySelector('[data-testid=\"pay-received-at-1\"]').classList.contains('fi--need')",
                           timeout=5000)
    # 第一期本來就有日期：勾選狀態不會觸發提示
    assert "fi--need" not in (page.locator('[data-testid="pay-received-at-0"]').get_attribute("class") or "")
