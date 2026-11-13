"""瀏覽器層級：估價單開啟時帶的是「估價單自己的條款」，報價單看到的仍是報價單那組（2026-11-13）。

後端與接線由 test_estimate_own_terms_2026_11_13.py 守著；這裡守使用者實際看到的畫面：
新增估價單（?type=estimate）→ 預設條款組／方塊是估價單那組；新增報價單 → 還是報價單那組。
"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests.test_e2e_quote_terms_presets_2026_09_14 import _rendered, _wait_init_settled  # noqa: E402


def _seed(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    h = {"Authorization": f"Bearer {r.json()['token']}"}

    def preset(name):
        return {"key": "", "name": name, "paymentTerms": name + "的付款條件", "deliveryTerms": name + "的交貨條件",
                "acceptanceTerms": name + "的驗收標準", "warrantyTerms": name + "的保固條件", "afterSales": name + "的售後服務"}
    assert client.put("/api/settings/quote-terms-presets", headers=h,
                      json={"presets": [preset("報價甲組"), preset("報價乙組")], "defaultKey": ""}).status_code == 200
    assert client.put("/api/settings/estimate-terms-presets", headers=h,
                      json={"presets": [preset("估價甲組"), preset("估價乙組")], "defaultKey": ""}).status_code == 200


@pytest.mark.e2e
def test_new_estimate_opens_with_the_estimate_terms(live_server, client, make_user, e2e_browser):
    u, p = make_user(username="eot_sa1", role="superadmin")
    _seed(client, u, p)
    page = e2e_browser.new_page()
    inject_login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/quotation-form.html?type=estimate")
    page.wait_for_selector('button:has-text("估價乙組")', timeout=15000)
    _wait_init_settled(page)
    _rendered(page)
    assert page.eval_on_selector('textarea[x-model="q.paymentTerms"]', "el => el.value") == "估價甲組的付款條件"
    assert page.locator('button:has-text("報價乙組")').count() == 0, "估價單不該看到報價單的條款組"
    page.click('button:has-text("估價乙組")')
    _rendered(page)
    assert page.eval_on_selector('textarea[x-model="q.afterSales"]', "el => el.value") == "估價乙組的售後服務"


@pytest.mark.e2e
def test_new_quotation_still_opens_with_the_quote_terms(live_server, client, make_user, e2e_browser):
    u, p = make_user(username="eot_sa2", role="superadmin")
    _seed(client, u, p)
    page = e2e_browser.new_page()
    inject_login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/quotation-form.html")
    page.wait_for_selector('button:has-text("報價乙組")', timeout=15000)
    _wait_init_settled(page)
    _rendered(page)
    assert page.eval_on_selector('textarea[x-model="q.paymentTerms"]', "el => el.value") == "報價甲組的付款條件"
    assert page.locator('button:has-text("估價乙組")').count() == 0, "報價單不該看到估價單的條款組"


def _data(page):
    return "Alpine.$data(document.querySelector('[x-data]'))"


@pytest.mark.e2e
def test_a_late_estimate_response_does_not_overwrite_the_quote_terms(live_server, client, make_user, e2e_browser):
    """報價單 → 切估價單（估價單條款回應很慢）→ 馬上切回報價單：慢的那支晚到，不可以把估價單條款組蓋到報價單上。"""
    from tests.test_e2e_quote_terms_presets_2026_09_14 import _delay_requests
    u, p = make_user(username="eot_sa3", role="superadmin")
    _seed(client, u, p)
    page = e2e_browser.new_page()
    _delay_requests(page, "estimate-terms-presets", 2500)
    inject_login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/quotation-form.html")
    page.wait_for_selector('button:has-text("報價乙組")', timeout=15000)
    _wait_init_settled(page)
    page.evaluate(f"() => {{ {_data(page)}.setDocType('estimate') }}")      # 不回傳 promise（否則 evaluate 會等它跑完，就沒有「慢」可言）
    page.wait_for_timeout(800)                        # 預設付款條件已回來、估價單條款組的請求還在路上（被拖慢）
    page.evaluate(f"async () => await {_data(page)}.setDocType('quote')")
    page.wait_for_timeout(3000)                       # 慢的回應已經到了
    names = page.evaluate(f"() => {_data(page)}.termsPresets.map(x => x.name)")
    assert names == ["報價甲組", "報價乙組"], names
    assert page.evaluate(f"() => {_data(page)}._termsDocType") == "quote"


@pytest.mark.e2e
def test_failed_estimate_terms_load_does_not_leave_the_quote_groups(live_server, client, make_user, e2e_browser):
    """估價單條款載入失敗（500）：不留著報價單的條款組（否則管理視窗存檔會把報價單的組寫到估價單）。"""
    u, p = make_user(username="eot_sa4", role="superadmin")
    _seed(client, u, p)
    page = e2e_browser.new_page()
    page.route("**/api/settings/estimate-terms-presets", lambda route: route.fulfill(status=500, body="boom"))
    inject_login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/quotation-form.html")
    page.wait_for_selector('button:has-text("報價乙組")', timeout=15000)
    _wait_init_settled(page)
    page.evaluate(f"async () => await {_data(page)}.setDocType('estimate')")
    names = page.evaluate(f"() => {_data(page)}.termsPresets.map(x => x.name)")
    assert names == [], names
    assert page.evaluate(f"() => {_data(page)}._termsLoadFailed") is True
    page.evaluate(f"() => {_data(page)}.openTermsManager()")
    assert page.evaluate(f"() => {_data(page)}.termsManageOpen") is False, "載入失敗不給開管理視窗（會拿空清單覆寫估價單條款組）"
