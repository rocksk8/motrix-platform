"""瀏覽器層級端對端測試：案件管理「財務」分頁的叫料（材料訂購）清單。

**為什麼非得用真實瀏覽器**：`routers/material_orders.py` 的兩支端點在
2026-09-10 就上線、也被 `test_material_orders_2026_09_10.py` 測到 7 題全綠，
但整整一天沒有任何前端呼叫得到它們——全 repo grep `material-orders` 只命中
後端與測試自己。純 API 測試對這種「後端好好的、只是沒有入口」的缺陷完全無感，
只有真的載入頁面、點進財務分頁、看得到那張卡片才驗得出來。前端於
2026-09-11 補上（`case-management.html` 的 `#fin-material-orders` 區塊 ＋
`case-management.js` 的 `loadMaterialOrders()`／`moSave()`），這支測試釘住它。

涵蓋一條完整來回：新增項目 → 小計自動算 → 儲存 → **重新載入頁面**後資料還在，
並直接回頭查 `data_json` 確認真的落到 `caseRecord.materialOrders`。

需要 `playwright`（見 `test_e2e_playwright_2026_09_07.py` 檔頭說明），
沒裝的環境整個檔案 skip。
"""
import json
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

import uvicorn
from tests._ports import free_safe_port

MO_PANEL = "#fin-material-orders"
ITEM_NAME_PH = "項目名稱（如：交換器）"


@pytest.fixture()
def live_server(client):
    """比照 test_e2e_playwright_2026_09_07.py 的同名 fixture：`client` 已把
    db/uploads 導向隔離暫存路徑，這裡再開一個真實 loopback 監聽給瀏覽器打。"""
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
    page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=10000)


def _seed_case(conn, quote_no):
    """建一張已成案報價單。案件管理左側清單只撈 deal_tag 已成案/已結案
    （見 case-management.js::loadCases()），deal_tag 給錯的話 `?q=` 根本選不到案。"""
    data_json = json.dumps({"dealTag": "已成案", "caseRecord": {}}, ensure_ascii=False)
    conn.execute(
        "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
        "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (quote_no, "已送出", "叫料測客", "叫料測專", 100000, 95238, data_json,
         "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "2026-01-01"),
    )


def _open_finance_tab(page, base_url, quote_no, expect="empty"):
    """開啟案件並切到財務分頁。`?q=` 是 case-management.js::init() 支援的選案參數。

    `expect` 是「叫料清單載完了」的判斷依據，不能改成等「載入中…」
    消失：`selected` 一被設定分頁列就出現了，而 loadMaterialOrders() 是在
    selectCase() 更後面才發出去——等「載入中」消失會在它根本還沒開始
    載入的那一瞬間就直接通過，是典型的假等待。空狀態文字與項目列
    則是真正的終點：兩者都只在 moLoading 為 false 時才會渲染。
    """
    page.goto(f"{base_url}/pages/case-management.html?q={quote_no}")
    page.wait_for_selector('.cm-tab:has-text("財務")', timeout=20000)
    page.click('.cm-tab:has-text("財務")')
    page.wait_for_selector(MO_PANEL, timeout=20000)
    if expect == "empty":
        # 2026-09-14：只等空狀態文字**出現**還是會假通過。滿載的機器上實測到
        # 這個順序——空狀態閃了一下 → 這裡的等待通過 → 畫面跳回「載入中…」→
        # 呼叫端的斷言讀到的是載入中的面板。改成等「安定下來」的狀態：空狀態
        # 文字在場**而且**載入指示已經消失，兩個條件同時成立才算載完。
        page.wait_for_function(
            """() => {
                 const el = document.querySelector('#fin-material-orders');
                 if (!el) return false;
                 const t = el.innerText || '';
                 return t.includes('尚無叫料項目') && !t.includes('載入中');
               }""",
            timeout=20000)
    else:
        page.wait_for_selector(f'{MO_PANEL} input[placeholder="{ITEM_NAME_PH}"]', timeout=20000)


def _read_material_orders(quote_no):
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
        return json.loads(row["data_json"] or "{}").get("caseRecord", {}).get("materialOrders", [])
    finally:
        conn.close()


@pytest.mark.e2e
def test_material_orders_panel_round_trip(live_server, make_user):
    """新增一筆叫料 → 小計自動算 → 儲存 → 重新載入後資料仍在，且真的寫進 data_json。

    這支測試在前端補上之前一定紅：那時候 `#fin-material-orders` 這個節點
    根本不存在，`_open_finance_tab()` 會在等它的時候逾時。
    """
    username, password = make_user(username="e2e_mo", role="superadmin")
    quote_no = "MQ-MO-E2E"

    import db
    conn = db.get_db()
    try:
        _seed_case(conn, quote_no)
        conn.commit()
    finally:
        conn.close()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        case_list_calls = []
        mo_calls = []
        # CM6：清單改分頁後，摘要計數與深連結也會打 /api/quotations?；主清單載入才帶 offset=0
        page.on("request", lambda r: case_list_calls.append(r.url)
                if "/api/quotations?" in r.url and "offset=0" in r.url else None)
        page.on("request", lambda r: mo_calls.append(r.url)
                if "/material-orders" in r.url and r.method == "GET" else None)
        api_calls = []
        page.on("request", lambda r: api_calls.append(r.method + " " + r.url)
                if "/api/" in r.url else None)
        try:
            _login(page, live_server, username, password)
            _open_finance_tab(page, live_server, quote_no)

            # 空狀態：沒有項目時要看得到引導文字，不是一片空白
            assert "尚無叫料項目" in page.locator(MO_PANEL).inner_text()

            # 回歸測試：init() 只能跑一次。<body> 寫了 x-init="init()"，而 Alpine 3
            # 本來就會自動呼叫資料物件的 init()，两者相加讓整頁初始化跑兩遍，
            # 第二次 selectCase() 會把使用者剛新增的叫料列默默重置掉（實測會造成
            # 這支測試每六輪假失敗兩次）。用「案件清單 API 被呼叫幾次」釘它，
            # 比等競態重現穩定。修法見 case-management.js::init() 的 _initDone 守門。
            # 同一個理由的另一半：叫料清單也只能載一次。切財務分頁刻意不重載
            # （case-management.html:774），第二次載入回來時會把使用者剛打的那
            # 一列蓋掉。這條也是上面那個假等待真正想抓的東西——面板之所以會
            # 跳回「載入中…」，就是有人又發了第二次。
            assert len(mo_calls) == 1, (
                f"叫料清單應該只載一次，實際發了 {len(mo_calls)} 次：{mo_calls}\n"
                f"案件清單 API {len(case_list_calls)} 次；所有 API 請求：\n"
                + "\n".join(api_calls))
            assert len(case_list_calls) == 1, (
                f"init() 應該只跑一次，但案件清單 API 被呼叫了 {len(case_list_calls)} 次")

            page.click(f'{MO_PANEL} button:has-text("＋ 新增項目")')
            try:
                page.fill(f'{MO_PANEL} input[placeholder="{ITEM_NAME_PH}"]', "24埠 PoE 交換器")
            except Exception as exc:                      # noqa: BLE001 — 只為了補上下文
                raise AssertionError(
                    "按了「新增項目」卻等不到輸入框。案件清單 API "
                    + str(len(case_list_calls)) + " 次、叫料 API " + str(len(mo_calls))
                    + " 次；面板內容："
                    + page.locator(MO_PANEL).inner_text()) from exc
            page.fill(f'{MO_PANEL} input[placeholder="數量"]', "3")
            page.fill(f'{MO_PANEL} input[placeholder="單位"]', "台")
            page.fill(f'{MO_PANEL} input[placeholder="單價"]', "12500")

            # 小計由前端算（後端會用 abs(小計 - 數量×單價) > 0.01 擋回來，
            # 所以這個數字錯了就等於整支端點不能用）
            page.wait_for_function(
                """(sel) => {
                     const el = document.querySelector(sel);
                     return !!el && el.innerText.includes('NT$ 37,500');
                   }""",
                arg=MO_PANEL, timeout=10000,
            )

            page.click(f'{MO_PANEL} button:has-text("儲存叫料")')
            # 時限放寬到 45 秒：整個 pytest session 期間有背景排程（月報、逾期檢查等）
            # 在寫 db，SQLite 寫鎖被佔住時 db.py 的 connect(timeout=30) 最多會等 30 秒，
            # 存檔這支 PATCH 就會卡滿一輪才回來。單檔跑不會遇到、全套跑才會——
            # 比照 test_e2e_playwright_2026_09_07.py 既有的同款處理。
            page.wait_for_selector(f'{MO_PANEL} :text("已儲存")', timeout=45000)

            # 落地檢查：不只看畫面，直接回頭查 data_json
            saved = _read_material_orders(quote_no)
            assert len(saved) == 1, f"data_json 裡應該有 1 筆叫料，實際 {len(saved)}"
            assert saved[0]["itemName"] == "24埠 PoE 交換器"
            assert saved[0]["quantity"] == 3
            assert saved[0]["unitPrice"] == 12500
            assert saved[0]["totalPrice"] == 37500
            assert saved[0]["paidStatus"] == "pending"
            assert saved[0]["paidAmount"] == 0
            assert saved[0]["paidDate"] is None

            # 重新載入：證明 GET 端點也真的接上了，不是只有畫面上的暫存狀態
            _open_finance_tab(page, live_server, quote_no, expect="rows")
            panel_text = page.locator(MO_PANEL).inner_text()
            # 項目名稱在 input 的 value 裡而不是 innerText，要用 input_value() 讀
            assert page.input_value(f'{MO_PANEL} input[placeholder="{ITEM_NAME_PH}"]') == "24埠 PoE 交換器"
            assert "NT$ 37,500" in panel_text, "重新載入後小計應該還在"
        finally:
            browser.close()


@pytest.mark.e2e
def test_material_orders_paid_status_rules_enforced_in_ui(live_server, make_user):
    """付款狀態的三條規則在畫面上就要成立，不能讓使用者撞到後端原始 400。

    後端規則（`routers/material_orders.py` 第 5 步）：
      pending → 已付金額必須 0、日期必須空
      paid    → 已付金額 = 小計
      partial/paid → 日期必填
    """
    username, password = make_user(username="e2e_mo2", role="superadmin")
    quote_no = "MQ-MO-E2E2"

    import db
    conn = db.get_db()
    try:
        _seed_case(conn, quote_no)
        conn.commit()
    finally:
        conn.close()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        # 失敗時看得到原因：全套跑的時候這支偶發逾時，而 Playwright 的 TimeoutError
        # 只會說「等了 45 秒」，不會說當下畫面在什麼狀態、API 是不是回了 400／500。
        bad = []
        page.on("response", lambda r: bad.append(f"{r.status} {r.url}") if r.status >= 400 else None)
        page.on("pageerror", lambda e: bad.append("PAGEERROR: " + str(e)))
        try:
            _login(page, live_server, username, password)
            _open_finance_tab(page, live_server, quote_no)

            page.click(f'{MO_PANEL} button:has-text("＋ 新增項目")')
            page.fill(f'{MO_PANEL} input[placeholder="{ITEM_NAME_PH}"]', "光纖模組")
            page.fill(f'{MO_PANEL} input[placeholder="數量"]', "2")
            page.fill(f'{MO_PANEL} input[placeholder="單價"]', "4000")

            # 待付狀態：金額與日期都應該是關掉的
            assert page.is_disabled(f'{MO_PANEL} input[placeholder="已付金額"]')
            assert page.is_disabled(f'{MO_PANEL} input[type="date"]')

            # 切成已付清：金額自動帶小計、日期自動帶今天
            page.select_option(f"{MO_PANEL} select", "paid")
            assert page.input_value(f'{MO_PANEL} input[placeholder="已付金額"]') == "8000"
            assert page.input_value(f'{MO_PANEL} input[type="date"]') != ""

            page.click(f'{MO_PANEL} button:has-text("儲存叫料")')
            # 時限放寬到 45 秒：整個 pytest session 期間有背景排程（月報、逾期檢查等）
            # 在寫 db，SQLite 寫鎖被佔住時 db.py 的 connect(timeout=30) 最多會等 30 秒，
            # 存檔這支 PATCH 就會卡滿一輪才回來。單檔跑不會遇到、全套跑才會——
            # 比照 test_e2e_playwright_2026_09_07.py 既有的同款處理。
            try:
                page.wait_for_selector(f'{MO_PANEL} :text("已儲存")', timeout=45000)
            except Exception as exc:                      # noqa: BLE001 — 只為了補上下文
                raise AssertionError(
                    "等不到「已儲存」。面板當下內容：\n"
                    + page.locator(MO_PANEL).inner_text()
                    + "\n失敗的請求／頁面錯誤：" + repr(bad)) from exc

            saved = _read_material_orders(quote_no)
            assert saved[0]["paidStatus"] == "paid"
            assert saved[0]["paidAmount"] == 8000
            assert saved[0]["paidDate"], "已付清必須有日期，否則後端回 400"
        finally:
            browser.close()
