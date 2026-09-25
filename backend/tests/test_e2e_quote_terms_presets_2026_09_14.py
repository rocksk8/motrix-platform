"""瀏覽器層級：報價單的條款組方塊真的會切換內容（2026-09-14）。

後端那半由 test_quote_terms_presets_2026_09_14.py 守著；這裡守的是**使用者實際
會做的那個動作**——點方塊，五段文字整組換掉。這一段完全在前端
（`quotation-form.html::applyTermsPreset()`），沒有 e2e 就等於沒有驗過。

需要 `playwright`（見 `test_e2e_playwright_2026_09_07.py` 檔頭說明）。
"""
import json
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")

import uvicorn
from tests._e2e_login import inject_login  # noqa: E402
from tests._ports import free_safe_port



def _rendered(page):
    """PERF #6：等 Alpine 把這次狀態變化畫完（nextTick）＋瀏覽器實際畫出兩個影格。
    ⚠️ 只適用於沒有 CSS transition 的元素（有 transition 的要等轉場落定）。"""
    page.evaluate("() => new Promise(r => (window.Alpine ? Alpine.nextTick : (f => f()))(() => requestAnimationFrame(() => requestAnimationFrame(r))))")



def _wait_init_settled(page):
    page.wait_for_function("() => Alpine.$data(document.querySelector('[x-data]'))._initSettled === true",
                           timeout=15000)


def _delay_requests(page, url_part, ms=2000):
    """頁面裡對 url_part 的 fetch 先延後 ms 再送出——做出「這一支回應最晚到」的時序（負載下的真實情況）。"""
    page.add_init_script("""(() => { const part = %s, ms = %d, f = window.fetch.bind(window);
      window.fetch = async (u, o) => { if (String(u).includes(part)) await new Promise(r => setTimeout(r, ms)); return f(u, o) } })()"""
                         % (json.dumps(url_part), ms))


def _login(page, base_url, username, password):
    return inject_login(page, base_url, username, password)


def _seed_presets(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    headers = {"Authorization": f"Bearer {r.json()['token']}"}
    body = {
        "presets": [
            {"key": "", "name": "標準工程",
             "paymentTerms": "工程組的付款條件", "deliveryTerms": "工程組的交貨條件",
             "acceptanceTerms": "工程組的驗收標準", "warrantyTerms": "工程組的保固條件",
             "afterSales": "工程組的售後服務"},
            {"key": "", "name": "純購料",
             "paymentTerms": "購料組的付款條件", "deliveryTerms": "購料組的交貨條件",
             "acceptanceTerms": "購料組的驗收標準", "warrantyTerms": "購料組的保固條件",
             "afterSales": "購料組的售後服務"},
        ],
        "defaultKey": "",
    }
    res = client.put("/api/settings/quote-terms-presets", json=body, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


@pytest.mark.e2e
def test_default_preset_is_applied_to_a_new_quotation(live_server, client, make_user, e2e_browser):
    """新增報價單時自動帶入被設為預設（★）的那一組。"""
    u, p = make_user(username="tp_sa1", role="superadmin")
    _seed_presets(client, u, p)

    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/quotation-form.html")
    page.wait_for_selector('button:has-text("純購料")', timeout=15000)
    # PERF #6：原本固定等 0.4 秒 ⇒ 等 init 把預設條款組套用完（新增模式：isNewRecord 設好之後同一段同步套用）
    # 📌 更正留著（2026-09-25，-n 4 五輪中一輪紅）：第一版等 `_termsDefaultsLoaded`——那是 init **前段**預設條款載完，
    #    套用預設組在 init 後段（還要先 await 取號）⇒ 負載下讀到空字串。等的點選錯了，不是產品競態。
    # 📌 再更正（2026-09-25，建包 ce9bc4b5 紅）：第二版加上 `isNewRecord`——它在 data() 的初始值就是 true，
    #    等於沒加；延後 next-quote-no 2 秒即穩定重現。而且查下去**真的有產品競態**：取號回來前使用者點的
    #    條款組會被預設組無聲蓋回去（見 test_a_preset_picked_before_init_finishes_is_not_overwritten）。
    #    ⇒ 頁面暴露 `_initSettled`（init 整段跑完），等這個終點，不猜哪一支請求最後回來。
    _wait_init_settled(page)
    _rendered(page)
    val = page.eval_on_selector(
        'textarea[x-model="q.paymentTerms"]', "el => el.value")
    assert val == "工程組的付款條件", val


@pytest.mark.e2e
def test_clicking_a_block_swaps_all_five_fields(live_server, client, make_user, e2e_browser):
    """點「純購料」→ 付款條件／交貨條件／驗收標準／保固條件／售後服務整組換掉。

    這是使用者裁示裡「可由報價人手動點選方塊做切換」那一句的實際驗證。
    """
    u, p = make_user(username="tp_sa2", role="superadmin")
    _seed_presets(client, u, p)

    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/quotation-form.html")
    page.wait_for_selector('button:has-text("純購料")', timeout=15000)
    # PERF #6：原本固定等 0.4 秒 ⇒ 等 init 把預設條款組套用完（新增模式：isNewRecord 設好之後同一段同步套用）
    # 📌 更正留著（2026-09-25，-n 4 五輪中一輪紅）：第一版等 `_termsDefaultsLoaded`——那是 init **前段**預設條款載完，
    #    套用預設組在 init 後段（還要先 await 取號）⇒ 負載下讀到空字串。等的點選錯了，不是產品競態。
    # 📌 再更正（2026-09-25，建包 ce9bc4b5 紅）：第二版加上 `isNewRecord`——它在 data() 的初始值就是 true，
    #    等於沒加；延後 next-quote-no 2 秒即穩定重現。而且查下去**真的有產品競態**：取號回來前使用者點的
    #    條款組會被預設組無聲蓋回去（見 test_a_preset_picked_before_init_finishes_is_not_overwritten）。
    #    ⇒ 頁面暴露 `_initSettled`（init 整段跑完），等這個終點，不猜哪一支請求最後回來。
    _wait_init_settled(page)
    _rendered(page)

    page.click('button:has-text("純購料")')
    _rendered(page)   # PERF #6：原本固定等 300ms（套用範本是同步的）

    for model, expect in (
        ("q.paymentTerms",    "購料組的付款條件"),
        ("q.deliveryTerms",   "購料組的交貨條件"),
        ("q.acceptanceTerms", "購料組的驗收標準"),
        ("q.warrantyTerms",   "購料組的保固條件"),
        ("q.afterSales",      "購料組的售後服務"),
    ):
        val = page.eval_on_selector(
            f'textarea[x-model="{model}"]', "el => el.value")
        assert val == expect, f"{model} 沒有跟著換：{val!r}"


@pytest.mark.e2e
def test_switching_preset_does_not_raise_a_false_approval_warning(live_server, client, make_user, e2e_browser):
    """切到非預設的那一組**不該**被判定成「報價條件已修改」。

    原本的 `checkApproval()` 一律拿 DEFAULT_TERMS 比對——有了條款組之後，
    切到「純購料」會整組被當成改過而觸發簽核提示，等於這個功能一用就報警。
    """
    u, p = make_user(username="tp_sa3", role="superadmin")
    _seed_presets(client, u, p)

    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/quotation-form.html")
    page.wait_for_selector('button:has-text("純購料")', timeout=15000)
    # PERF #6：原本固定等 0.4 秒 ⇒ 等 init 把預設條款組套用完（新增模式：isNewRecord 設好之後同一段同步套用）
    # 📌 更正留著（2026-09-25，-n 4 五輪中一輪紅）：第一版等 `_termsDefaultsLoaded`——那是 init **前段**預設條款載完，
    #    套用預設組在 init 後段（還要先 await 取號）⇒ 負載下讀到空字串。等的點選錯了，不是產品競態。
    # 📌 再更正（2026-09-25，建包 ce9bc4b5 紅）：第二版加上 `isNewRecord`——它在 data() 的初始值就是 true，
    #    等於沒加；延後 next-quote-no 2 秒即穩定重現。而且查下去**真的有產品競態**：取號回來前使用者點的
    #    條款組會被預設組無聲蓋回去（見 test_a_preset_picked_before_init_finishes_is_not_overwritten）。
    #    ⇒ 頁面暴露 `_initSettled`（init 整段跑完），等這個終點，不猜哪一支請求最後回來。
    _wait_init_settled(page)
    _rendered(page)
    page.click('button:has-text("純購料")')
    _rendered(page)   # PERF #6：原本固定等 300ms（套用範本是同步的）

    reasons = page.evaluate(
        "() => (Alpine.$data(document.querySelector('[x-data]')).approvalReasons || [])")
    hits = [r for r in reasons if "報價條件" in r]
    assert not hits, f"切換條款組被誤判成條件被改過：{hits}"


# ── 載入期間使用者先動了條款：新單的預設組不可以事後蓋掉（2026-09-25）────────────────────────────
# ☠️ 條款組方塊與五個文字框在 init 取完條款組之後就畫出來了，而新單套用預設組原本排在 `await 取號` 之後。
#    取號要查 quotations 全表的 MAX(序號)，負載下是最慢的一支 ⇒ 這段空窗裡使用者點的方塊／打的字，
#    會在取號回來時被預設組**無聲蓋回去**（畫面閃一下就變回預設，沒有任何提示）。

@pytest.mark.e2e
@pytest.mark.parametrize("slow", ["next-quote-no", "quote-terms-presets", "NONE"])
def test_default_preset_lands_whichever_request_is_slowest(live_server, client, make_user, e2e_browser, slow):
    """哪一支請求最晚回來，新單最後都是預設那一組（等的是 init 的終點，不是某一支請求）。"""
    u, p = make_user(username="tp_slow", role="superadmin")
    _seed_presets(client, u, p)
    page = e2e_browser.new_page()
    _delay_requests(page, slow)
    _login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/quotation-form.html")
    _wait_init_settled(page)
    _rendered(page)
    assert page.eval_on_selector('textarea[x-model="q.paymentTerms"]', "el => el.value") == "工程組的付款條件"


@pytest.mark.e2e
def test_a_preset_picked_before_init_finishes_is_not_overwritten(live_server, client, make_user, e2e_browser):
    u, p = make_user(username="tp_early", role="superadmin")
    _seed_presets(client, u, p)
    page = e2e_browser.new_page()
    _delay_requests(page, "next-quote-no")
    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    _login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/quotation-form.html")
    page.click('button:has-text("純購料")')
    assert not dialogs, "載入中點方塊，欄位根本沒動過，不可以問「會覆蓋你已經改過的內容」：%s" % dialogs
    assert not page.evaluate("() => Alpine.$data(document.querySelector('[x-data]'))._initSettled"), \
        "前提：點下去的時候 init 還沒跑完（取號被延後）"
    _wait_init_settled(page)
    _rendered(page)
    assert page.eval_on_selector('textarea[x-model="q.paymentTerms"]', "el => el.value") == "購料組的付款條件"
    assert page.evaluate("() => Alpine.$data(document.querySelector('[x-data]')).q.termsPresetKey") != \
        page.evaluate("() => Alpine.$data(document.querySelector('[x-data]')).termsDefaultKey")


@pytest.mark.e2e
def test_terms_typed_before_presets_arrive_are_not_overwritten(live_server, client, make_user, e2e_browser):
    u, p = make_user(username="tp_typed", role="superadmin")
    _seed_presets(client, u, p)
    page = e2e_browser.new_page()
    _delay_requests(page, "quote-terms-presets")
    _login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/quotation-form.html")
    page.fill('textarea[x-model="q.paymentTerms"]', "我自己寫的付款條件")
    assert not page.evaluate("() => Alpine.$data(document.querySelector('[x-data]'))._initSettled"), \
        "前提：打字的時候條款組還沒載入"
    _wait_init_settled(page)
    _rendered(page)
    assert page.eval_on_selector('textarea[x-model="q.paymentTerms"]', "el => el.value") == "我自己寫的付款條件"
