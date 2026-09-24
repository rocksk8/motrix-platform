"""瀏覽器端對端：送審特殊條件前後端判準一致；預設條款來自後端（2026-09-24，N13）。

- 同一份報價資料，前端 checkApproval() 與後端 helpers/quote_terms.compute_approval_reasons()
  算出的原因**逐字相同**（涵蓋毛利率含平手進位、區段標題的項次、有效期、折讓千分位與小數、
  稅率、條款與預設不同、條款與條款組不同）
- 新增報價單的五欄條款由 GET /api/settings/quote-terms-defaults 帶入（前端不再有自己那份）
- 預設條款載入失敗 ⇒ 不判定條款、不擋送審（使用者裁示 R1）
"""
import json
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

import uvicorn
from tests._ports import free_safe_port

DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"


@pytest.fixture()
def live_server(client):
    """比照 test_e2e_copy_to_new_2026_09_10.py 的同名 fixture。"""
    import main
    config = uvicorn.Config(main.app, host="127.0.0.1", port=free_safe_port(), log_level="warning")
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


def _seed_presets():
    import db
    from helpers.quote_terms import DEFAULT_TERMS
    preset = dict(DEFAULT_TERMS, key="p1", name="純購料", afterSales="購料不含售後", deliveryTerms="自取")
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
            ("quote_terms_presets", json.dumps({"presets": [preset], "defaultKey": ""}, ensure_ascii=False),
             "2026-01-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()
    return [preset]


def _cases():
    from helpers.quote_terms import DEFAULT_TERMS
    # 每一組都帶齊判準會讀到的欄位——前端是蓋在既有的 q 上，缺欄位會沿用上一組的值
    t = dict(DEFAULT_TERMS, validDays=30, taxRate=5, showDiscount=False, discount=0, termsPresetKey="")
    items = [{"type": "header", "description": "區段"},
             {"description": "a", "cost": 100, "margin": 0.28125},      # 28.125 ⇒ 平手進位 28.13
             {"description": "b", "cost": 100, "margin": 0.2999},
             {"description": "c", "cost": 0, "margin": 0.1},            # 沒成本 ⇒ 不列
             {"description": "d", "cost": 100, "margin": 0.3}]          # 剛好 30% ⇒ 不列
    return [
        dict(t, items=items, validDays=45, showDiscount=True, discount=12345.5, taxRate=0),
        dict(t, items=[], validDays=30, showDiscount=False, discount=999, taxRate=5),
        dict(t, items=[], validDays=31, deliveryTerms="改過", warrantyTerms="  " + t["warrantyTerms"] + "\n"),
        dict(t, items=[], termsPresetKey="p1"),                                           # 與條款組不同
        dict(t, items=[], termsPresetKey="p1", afterSales="購料不含售後", deliveryTerms="自取"),  # 與條款組相同
        dict(t, items=[], showDiscount=True, discount=1000000),
    ]


@pytest.mark.e2e
def test_frontend_and_backend_reasons_are_identical(live_server, make_user):
    from helpers.quote_terms import DEFAULT_TERMS, compute_approval_reasons
    username, password = make_user(username="e2e_n13a", role="superadmin")
    presets = _seed_presets()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            _login(page, live_server, username, password)
            page.goto(f"{live_server}/pages/quotation-form.html")
            page.wait_for_function(f"() => {DATA_JS}._termsDefaultsLoaded === true "
                                   f"&& {DATA_JS}.termsPresets.length === 1", timeout=20000)
            for i, case in enumerate(_cases()):
                fe = page.evaluate(
                    """(d) => { const c = Alpine.$data(document.querySelector('[x-data]'))
                               c.q = Object.assign({}, c.q, d, { approval: null })
                               c.checkApproval(); return [...c.approvalReasons] }""", case)
                be = compute_approval_reasons(case, presets, DEFAULT_TERMS["paymentTerms"])
                assert fe == be, f"第 {i} 組不一致\n前端 {fe}\n後端 {be}"
                assert i != 0 or len(be) == 5, be   # 量尺：第 0 組要真的量到東西
        finally:
            browser.close()


@pytest.mark.e2e
def test_new_quote_terms_come_from_backend(live_server, make_user):
    from helpers.quote_terms import DEFAULT_TERMS
    username, password = make_user(username="e2e_n13b", role="superadmin")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            _login(page, live_server, username, password)
            page.goto(f"{live_server}/pages/quotation-form.html")
            page.wait_for_function(f"() => {DATA_JS}._termsDefaultsLoaded === true", timeout=20000)
            page.wait_for_function(f"() => !!{DATA_JS}.q.deliveryTerms", timeout=10000)
            got = page.evaluate(f"(() => {{ const q = {DATA_JS}.q; return [q.deliveryTerms, q.acceptanceTerms,"
                                f" q.warrantyTerms, q.afterSales] }})()")
            assert got == [DEFAULT_TERMS[k] for k in ("deliveryTerms", "acceptanceTerms", "warrantyTerms", "afterSales")]
            assert page.evaluate(f"{DATA_JS}.approvalReasons") == [], "新單照預設條款不該觸發「報價條件已修改」"
        finally:
            browser.close()


@pytest.mark.e2e
def test_defaults_load_failure_does_not_judge_terms(live_server, make_user):
    username, password = make_user(username="e2e_n13c", role="superadmin")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            _login(page, live_server, username, password)
            page.route("**/api/settings/quote-terms-defaults", lambda r: r.fulfill(status=503, body="{}"))
            # PERF #6：原本固定等 1.5 秒 ⇒ 等那一趟（被攔成 503 的）預設值請求**整個收完**再讓出一個 task
            # ⚠️ 用 requestfinished 不用 response：response 在收到標頭時就觸發，頁面還要讀 body 才決定旗標，
            #    太早檢查會搶在錯誤寫法「失敗仍設成已載入」之前（假綠）
            with page.expect_event("requestfinished", lambda r: "/api/settings/quote-terms-defaults" in r.url,
                                   timeout=20000):
                page.goto(f"{live_server}/pages/quotation-form.html")
            page.wait_for_function(f"() => {DATA_JS}.session && {DATA_JS}.q", timeout=20000)
            page.evaluate("() => new Promise(r => setTimeout(r, 0))")
            assert page.evaluate(f"{DATA_JS}._termsDefaultsLoaded") is False
            reasons = page.evaluate(
                f"(() => {{ const c = {DATA_JS}; c.q.deliveryTerms = '改過'; c.checkApproval(); return c.approvalReasons }})()")
            assert not any("報價條件" in r for r in reasons), reasons
        finally:
            browser.close()


@pytest.mark.e2e
def test_existing_quote_without_terms_keys_gets_defaults(live_server, make_user):
    """N13 回歸：沒存過條款的舊報價單打開時要帶入預設條款（N13 之前 data() 預設值就是如此）；
    存成空字串的（使用者清掉的）不動。"""
    import db
    from helpers.quote_terms import DEFAULT_TERMS
    username, password = make_user(username="e2e_n13d", role="superadmin")
    conn = db.get_db()
    try:
        for no, extra in (("MQ-202609-091", {}), ("MQ-202609-092", {"deliveryTerms": ""})):
            d = {"quoteNo": no, "customerName": "條款客戶", "projectName": "條款專案", "status": "草稿",
                 "items": [], "tot": {"total": 0, "pretax": 0}}
            d.update(extra)
            conn.execute(
                "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
                " created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (no, "草稿", "條款客戶", "條款專案", 0, 0, json.dumps(d, ensure_ascii=False),
                 "2026-09-01", "2026-09-01", "", "2026-09-01"))
        conn.commit()
    finally:
        conn.close()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            _login(page, live_server, username, password)
            page.goto(f"{live_server}/pages/quotation-form.html?id=MQ-202609-091")
            page.wait_for_function(f"() => {DATA_JS}.q.quoteNo === 'MQ-202609-091' && !!{DATA_JS}.q.deliveryTerms",
                                   timeout=20000)
            assert page.evaluate(f"{DATA_JS}.q.acceptanceTerms") == DEFAULT_TERMS["acceptanceTerms"]
            page.goto(f"{live_server}/pages/quotation-form.html?id=MQ-202609-092")
            page.wait_for_function(f"() => {DATA_JS}.q.quoteNo === 'MQ-202609-092' && !!{DATA_JS}.q.warrantyTerms",
                                   timeout=20000)
            assert page.evaluate(f"{DATA_JS}.q.deliveryTerms") == "", "使用者清掉的條款不可以被補回"
        finally:
            browser.close()
