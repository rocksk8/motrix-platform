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
from playwright.sync_api import sync_playwright

import uvicorn


@pytest.fixture()
def live_server(client):
    import main
    config = uvicorn.Config(main.app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    else:
        pytest.fail("uvicorn 測試伺服器在時限內沒有啟動")
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def _login(page, base_url, username, password):
    page.goto(f"{base_url}/pages/login.html")
    page.fill('input[x-model="username"]', username)
    page.fill('input[x-model="password"]', password)
    page.click('button:has-text("登入")')
    page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=15000)


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
def test_default_preset_is_applied_to_a_new_quotation(live_server, client, make_user):
    """新增報價單時自動帶入被設為預設（★）的那一組。"""
    u, p = make_user(username="tp_sa1", role="superadmin")
    _seed_presets(client, u, p)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        try:
            _login(page, live_server, u, p)
            page.goto(f"{live_server}/pages/quotation-form.html")
            page.wait_for_selector('button:has-text("純購料")', timeout=15000)
            page.wait_for_timeout(400)
            val = page.eval_on_selector(
                'textarea[x-model="q.paymentTerms"]', "el => el.value")
            assert val == "工程組的付款條件", val
        finally:
            browser.close()


@pytest.mark.e2e
def test_clicking_a_block_swaps_all_five_fields(live_server, client, make_user):
    """點「純購料」→ 付款條件／交貨條件／驗收標準／保固條件／售後服務整組換掉。

    這是使用者裁示裡「可由報價人手動點選方塊做切換」那一句的實際驗證。
    """
    u, p = make_user(username="tp_sa2", role="superadmin")
    _seed_presets(client, u, p)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        try:
            _login(page, live_server, u, p)
            page.goto(f"{live_server}/pages/quotation-form.html")
            page.wait_for_selector('button:has-text("純購料")', timeout=15000)
            page.wait_for_timeout(400)

            page.click('button:has-text("純購料")')
            page.wait_for_timeout(300)

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
        finally:
            browser.close()


@pytest.mark.e2e
def test_switching_preset_does_not_raise_a_false_approval_warning(live_server, client, make_user):
    """切到非預設的那一組**不該**被判定成「報價條件已修改」。

    原本的 `checkApproval()` 一律拿 DEFAULT_TERMS 比對——有了條款組之後，
    切到「純購料」會整組被當成改過而觸發簽核提示，等於這個功能一用就報警。
    """
    u, p = make_user(username="tp_sa3", role="superadmin")
    _seed_presets(client, u, p)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        try:
            _login(page, live_server, u, p)
            page.goto(f"{live_server}/pages/quotation-form.html")
            page.wait_for_selector('button:has-text("純購料")', timeout=15000)
            page.wait_for_timeout(400)
            page.click('button:has-text("純購料")')
            page.wait_for_timeout(300)

            reasons = page.evaluate(
                "() => (Alpine.$data(document.querySelector('[x-data]')).approvalReasons || [])")
            hits = [r for r in reasons if "報價條件" in r]
            assert not hits, f"切換條款組被誤判成條件被改過：{hits}"
        finally:
            browser.close()
