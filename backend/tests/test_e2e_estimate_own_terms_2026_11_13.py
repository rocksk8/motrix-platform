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
