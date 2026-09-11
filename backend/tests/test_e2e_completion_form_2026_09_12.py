"""瀏覽器端對端：完工單獨立填寫頁 `completion-note-form.html`（2026-09-12）。

使用者指定「用報價單的方式去建立，一個頁面做填寫，多增加可切換的頁面」，所以完工單
從案件管理的 Modal 改成獨立頁面＋分頁切換（基本資料／完成項目／說明與驗收／單據用語）。

這一頁全靠 Alpine 綁定，寫錯不會有錯誤訊息、只會安靜地存不進去——本專案已經在同一個
坑摔過好幾次，所以從瀏覽器一路按到底，最後回頭查資料庫確認值真的送到了。
"""
import json
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

import uvicorn

PAGE = "/pages/completion-note-form.html"


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
    page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=10000)


def _seed_case(quote_no="MQ-CNFORM-001"):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "網路測試客戶", "總部網路架構升級", 100000, 95238,
             json.dumps({"dealTag": "已成案"}, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"),
        )
        conn.commit()
    finally:
        conn.close()


def _row(quote_no="MQ-CNFORM-001"):
    import db
    conn = db.get_db()
    try:
        r = conn.execute(
            "SELECT * FROM completion_notes WHERE quote_no=? ORDER BY id DESC LIMIT 1",
            (quote_no,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


@pytest.mark.e2e
def test_init_runs_exactly_once(live_server, make_user):
    """開一次頁面，案件 API 只能被打一次。

    這一頁刻意**沒有** `x-init="init()"`（Alpine 3 自己就會呼叫 init()）。兩者同時
    存在會跑兩遍，第二次載入的回應會把使用者改到一半的欄位蓋回去——2026-09-11 在
    `case-management.js` 與 `company-profile-settings.html` 各踩過一次。
    數請求次數是確定性的，不必等競態重現。
    """
    username, password = make_user(username="e2e_cnf0", role="superadmin")
    _seed_case()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        try:
            _login(page, live_server, username, password)
            hits = []
            page.on("request", lambda r: hits.append(r.url)
                    if "/api/quotations/MQ-CNFORM-001" in r.url else None)
            page.goto(f"{live_server}{PAGE}?q=MQ-CNFORM-001")
            page.wait_for_selector("button:has-text('完成項目')", timeout=45000)
            page.wait_for_timeout(1200)
            assert len(hits) == 1, f"init() 應該只跑一次，實際打了 {len(hits)} 次案件 API"
        finally:
            browser.close()


@pytest.mark.e2e
def test_tabs_switch_and_case_fields_are_prefilled(live_server, make_user):
    """四個分頁切得動，而且新增時客戶／案件名稱要自動帶進來。"""
    username, password = make_user(username="e2e_cnf1", role="superadmin")
    _seed_case()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        try:
            _login(page, live_server, username, password)
            page.goto(f"{live_server}{PAGE}?q=MQ-CNFORM-001")
            page.wait_for_selector("button:has-text('完成項目')", timeout=45000)

            assert page.input_value("input[x-model='form.customer_name']") == "網路測試客戶"
            assert page.input_value("input[x-model='form.project_name']") == "總部網路架構升級"

            for tab, marker in (("完成項目", "button:has-text('＋ 項目')"),
                                ("說明與驗收", "textarea[x-model='form.work_summary']"),
                                ("單據用語", "button:has-text('網路架構／資安')")):
                page.click(f"button.cnf-tab:has-text('{tab}')")
                page.wait_for_selector(marker, state="visible", timeout=10000)
            assert not errors, f"頁面有 JS 錯誤：{errors}"
        finally:
            browser.close()


@pytest.mark.e2e
def test_preset_and_custom_labels_round_trip(live_server, make_user):
    """套用預設用語 → 儲存 → 值真的寫進 data_json.labels。

    這是使用者這一輪的核心需求（完工單太偏向工程），綁錯不會報錯、只會安靜地存不進去。
    """
    username, password = make_user(username="e2e_cnf2", role="superadmin")
    _seed_case()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        try:
            _login(page, live_server, username, password)
            page.goto(f"{live_server}{PAGE}?q=MQ-CNFORM-001")
            page.wait_for_selector("button:has-text('完成項目')", timeout=45000)

            # 先加一個項目（送審門檻之一，也順便驗項目綁定）
            page.click("button.cnf-tab:has-text('完成項目')")
            page.click("button:has-text('＋ 項目')")
            page.fill("input[x-model='it.description']", "核心交換器建置")

            # 套用「網路架構／資安」那組，再手動微調一欄
            page.click("button.cnf-tab:has-text('單據用語')")
            page.click("button:has-text('網路架構／資安')")
            page.fill("input[x-model=\"form.labels[f.key]\"] >> nth=0", "一、客戶與機房環境")

            page.click("button:has-text('儲存')")
            page.wait_for_selector(":text('已儲存')", timeout=45000)
        finally:
            browser.close()

    assert not errors, f"頁面有 JS 錯誤：{errors}"
    row = _row()
    assert row, "完工單沒有被建立"
    labels = (json.loads(row["data_json"] or "{}") or {}).get("labels") or {}
    assert labels.get("itemColumn") == "設備 / 設定項目", f"預設用語沒存進去：{labels}"
    assert labels.get("sectionCustomer") == "一、客戶與機房環境", "手動微調的那一欄沒存進去"
    assert json.loads(row["items_json"])[0]["description"] == "核心交換器建置"


@pytest.mark.e2e
def test_warranty_toggle_controls_whether_it_is_stored(live_server, make_user):
    """保固勾掉＝月數存 0＝完工單上不顯示（比照報價單「留空就不印」）。"""
    username, password = make_user(username="e2e_cnf3", role="superadmin")
    _seed_case("MQ-CNFORM-002")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        try:
            _login(page, live_server, username, password)
            page.goto(f"{live_server}{PAGE}?q=MQ-CNFORM-002")
            page.wait_for_selector("button:has-text('完成項目')", timeout=45000)

            # 預設是勾選的（12 個月），先確認提示文字在
            assert page.is_checked("input[type='checkbox']")
            page.uncheck("input[type='checkbox']")
            page.wait_for_selector(":text('不會出現')", timeout=10000)

            page.click("button.cnf-tab:has-text('完成項目')")
            page.click("button:has-text('＋ 項目')")
            page.fill("input[x-model='it.description']", "零組件供應")
            page.click("button:has-text('儲存')")
            page.wait_for_selector(":text('已儲存')", timeout=45000)
        finally:
            browser.close()

    assert _row("MQ-CNFORM-002")["warranty_months"] == 0
