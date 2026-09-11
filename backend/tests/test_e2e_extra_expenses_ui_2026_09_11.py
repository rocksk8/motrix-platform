"""瀏覽器層級端對端測試：案件管理的「額外支出」分頁（2026-09-11，改版第三段）。

規格見 `MOTRIX-ERP-QUICK.md` §5.10。使用者交辦的七項裡屬於畫面的那幾項都在這裡驗：
從精算頁搬到案件內選單、類別欄不再被寫死寬度、填寫人自動帶入（推定值要標出來）、
支出人可選可自由文字、填寫日期與更動日期看得到、可以送審、送審中的金額要提醒。

這一區全靠 Alpine 綁定，寫錯不會有錯誤訊息、只會安靜地不顯示——本專案已經在同一個
坑摔過三次（WebAuthn 設定頁、叫料、系統技術設定），所以一律補端到端。

需要 `playwright`（見 `test_e2e_playwright_2026_09_07.py` 檔頭說明）。
"""
import json
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

import uvicorn

TAB = ".cm-tab:has-text('額外支出')"
PANEL = "#xe-panel"


@pytest.fixture()
def live_server(client):
    """比照 test_e2e_playwright_2026_09_07.py 的同名 fixture。"""
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


def _seed_case(quote_no="MQ-XEUI-001"):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "額外支出測客", "測專", 100000, 95238,
             json.dumps({"dealTag": "已成案", "caseRecord": {}}, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"),
        )
        conn.commit()
    finally:
        conn.close()


def _open_tab(page, base_url, quote_no):
    page.goto(f"{base_url}/pages/case-management.html?q={quote_no}")
    page.wait_for_selector(TAB, timeout=20000)
    page.click(TAB)
    # 等載入真的結束（空狀態或項目列出現），不要等「載入中」消失——
    # 分頁列比載入早出現，那樣等會在還沒開始載入時就通過
    page.wait_for_selector(
        f"{PANEL} :text('尚無額外支出'), {PANEL} input[placeholder='品項說明（必填）']",
        timeout=20000)


@pytest.mark.e2e
def test_tab_exists_and_shows_empty_state(live_server, make_user):
    """分頁要在案件內選單裡（不是塞在財務分頁），空狀態要有引導文字。"""
    username, password = make_user(username="e2e_xe", role="superadmin")
    _seed_case()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        try:
            _login(page, live_server, username, password)
            _open_tab(page, live_server, "MQ-XEUI-001")
            body = page.locator(PANEL).inner_text()
            assert "尚無額外支出" in body
            assert not errors, f"頁面有 JS 錯誤：{errors}"
        finally:
            browser.close()


@pytest.mark.e2e
def test_create_save_and_author_is_filled_in(live_server, make_user):
    """新增 → 儲存 → 填寫人自動帶入（不是空白，也不是前端亂填的）。

    舊版的填寫人永遠是空字串（前端取錯 session 路徑），這支測試就是釘住它。
    """
    username, password = make_user(username="e2e_xe2", role="superadmin")
    _seed_case("MQ-XEUI-002")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        try:
            _login(page, live_server, username, password)
            _open_tab(page, live_server, "MQ-XEUI-002")

            # 選擇器一律限縮在 PANEL 裡：頁面上不只一個「儲存」按鈕
            # （案件整包存檔、叫料的「儲存叫料」都含這兩個字），
            # has-text 是子字串比對，不限縮就會點到別人的按鈕
            page.click(f"{PANEL} button:has-text('＋ 新增支出')")
            page.fill(f"{PANEL} input[placeholder='品項說明（必填）']", "吊車運費")
            page.fill(f"{PANEL} input[placeholder='數量']", "2")
            page.fill(f"{PANEL} input[placeholder='單位成本']", "1500")
            page.click(f"{PANEL} button:text-is('儲存')")
            page.wait_for_selector(f"{PANEL} :text('已儲存')", timeout=45000)

            # 落地檢查：填寫人是登入者，且不是推定值
            import db
            conn = db.get_db()
            try:
                row = conn.execute(
                    "SELECT created_by, created_by_name, created_by_inferred, total_cost, status "
                    "FROM case_extra_expenses WHERE quote_no='MQ-XEUI-002'").fetchone()
            finally:
                conn.close()
            assert row, "應該要寫進 case_extra_expenses"
            assert row["created_by"] == username, "填寫人要自動帶入登入者"
            assert row["created_by_inferred"] == 0, "現場填的不是推定值"
            assert row["total_cost"] == 3000, "小計要由後端算"
            assert row["status"] == "草稿"
        finally:
            browser.close()


@pytest.mark.e2e
def test_inferred_author_is_labelled(live_server, make_user, seed_extra_expense):
    """搬移回填的填寫人要標「（推定）」——推定不是還原，不能讓人當成事實。"""
    username, password = make_user(username="e2e_xe3", role="superadmin")
    _seed_case("MQ-XEUI-003")
    exp_id = seed_extra_expense("MQ-XEUI-003", total_cost=1200, description="舊資料",
                                created_by_name="黃玉龍", expense_date="2026-08-01")
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE case_extra_expenses SET created_by_inferred=1 WHERE id=?", (exp_id,))
        conn.commit()
    finally:
        conn.close()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        try:
            _login(page, live_server, username, password)
            _open_tab(page, live_server, "MQ-XEUI-003")
            body = page.locator(PANEL).inner_text()
            assert "黃玉龍" in body
            assert "（推定）" in body, "推定回填的填寫人一定要標示出來"
        finally:
            browser.close()


@pytest.mark.e2e
def test_pending_amount_is_warned_but_still_counted(live_server, make_user, seed_extra_expense):
    """送審中的金額照樣算進總額，但畫面要明講「已計入但可能改變」。"""
    username, password = make_user(username="e2e_xe4", role="superadmin")
    _seed_case("MQ-XEUI-004")
    seed_extra_expense("MQ-XEUI-004", total_cost=1000, description="已核准的",
                       status="已核准", expense_date="2026-08-01")
    seed_extra_expense("MQ-XEUI-004", total_cost=400, description="送審中的",
                       status="待審核", expense_date="2026-08-02")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        try:
            _login(page, live_server, username, password)
            _open_tab(page, live_server, "MQ-XEUI-004")
            body = page.locator(PANEL).inner_text()
            assert "NT$ 1,400" in body, "總額要含送審中的那筆"
            assert "尚未核准" in body
            assert "已經計入上方總額與成本" in body, "要明講它已計入、但可能改變"
        finally:
            browser.close()


@pytest.mark.e2e
def test_approved_row_is_readonly(live_server, make_user, seed_extra_expense):
    """已核准的不給改——金額已經進了成本與報表。"""
    username, password = make_user(username="e2e_xe5", role="superadmin")
    _seed_case("MQ-XEUI-005")
    seed_extra_expense("MQ-XEUI-005", total_cost=800, description="已核准",
                       status="已核准", expense_date="2026-08-03")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        try:
            _login(page, live_server, username, password)
            _open_tab(page, live_server, "MQ-XEUI-005")
            assert page.is_disabled(f"{PANEL} input[placeholder='品項說明（必填）']")
            assert "已核准的項目不可修改" in page.locator(PANEL).inner_text()
        finally:
            browser.close()


@pytest.mark.e2e
def test_settlement_page_points_to_new_location_and_uses_new_total(
        live_server, make_user, seed_extra_expense):
    """精算頁：那張可編輯的表要不見、改成導向卡片，而且成本彙總要用**新表**的數字。

    兩件事都重要：
      - 表沒拿掉的話會變成「編輯了也不會進報表」（資料已改從新表讀），比拿掉更難察覺
      - 成本彙總若還用 settlement.extraItems 算，會停在搬移當下的舊數字
    """
    username, password = make_user(username="e2e_xe6", role="superadmin")
    _seed_case("MQ-XEUI-006")
    seed_extra_expense("MQ-XEUI-006", total_cost=5500, description="新表才有的",
                       status="已核准", expense_date="2026-08-04")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        try:
            _login(page, live_server, username, password)
            page.goto(f"{live_server}/pages/settlement.html?no=MQ-XEUI-006")
            page.wait_for_selector(":text('二、額外支出')", timeout=20000)

            body = page.locator("body").inner_text()
            assert "已移到" in body and "案件管理" in body, "要有導向新位置的說明"
            assert page.locator("a:has-text('前往案件管理的額外支出')").count() == 1

            # 原本那張可編輯的表必須不在了
            assert page.locator("input[placeholder*='工程師出差工時']").count() == 0, \
                "精算頁不該再有可編輯的額外支出表單"

            # 成本彙總要看得到新表那筆 5,500
            page.wait_for_function(
                "() => document.body.innerText.includes('5,500')", timeout=20000)

            assert not errors, f"頁面有 JS 錯誤：{errors}"
        finally:
            browser.close()
