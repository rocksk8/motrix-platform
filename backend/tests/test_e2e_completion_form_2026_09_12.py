"""瀏覽器端對端：完工單獨立填寫頁 `completion-note-form.html`（2026-09-12）。

完工單從案件管理的 Modal 改成獨立頁面（比照報價單清單 → 報價單表單的分工）。
**版面是單一頁面、由上往下逐條填**——初版做成四個可切換分頁，使用者實測後要求拿掉
（「是否能整合成一頁逐條改善下來不要有分頁」），因為填寫時一直在切分頁反而比往下捲慢。

這一頁全靠 Alpine 綁定，寫錯不會有錯誤訊息、只會安靜地存不進去——本專案已經在同一個
坑摔過好幾次，所以從瀏覽器一路按到底，最後回頭查資料庫確認值真的送到了。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")

import uvicorn
from tests._e2e_login import inject_login  # noqa: E402
from tests._ports import free_safe_port
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')

PAGE = "/pages/completion-note-form.html"




def _login(page, base_url, username, password):
    inject_login(page, base_url, username, password)


def _seed_case(quote_no="MQ-CNFORM-001"):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "網路測試客戶", "總部網路架構升級", 100000, 95238,
             json.dumps({"dealTag": "已成案",
                         # 完工單新增時要從這三個欄位帶入地址與聯絡人（使用者指定）
                         "deliveryAddress": "台中市西屯區工業區一路 1 號",
                         "contactName": "林經理",
                         "contactPhone": "04-2461-0000"}, ensure_ascii=False),
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
def test_init_runs_exactly_once(live_server, make_user, e2e_browser):
    """開一次頁面，案件 API 只能被打一次。

    這一頁刻意**沒有** `x-init="init()"`（Alpine 3 自己就會呼叫 init()）。兩者同時
    存在會跑兩遍，第二次載入的回應會把使用者改到一半的欄位蓋回去——2026-09-11 在
    `case-management.js` 與 `company-profile-settings.html` 各踩過一次。
    數請求次數是確定性的，不必等競態重現。
    """
    username, password = make_user(username="e2e_cnf0", role="superadmin")
    _seed_case()
    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, username, password)
    hits = []
    page.on("request", lambda r: hits.append(r.url)
            if "/api/quotations/MQ-CNFORM-001" in r.url else None)
    page.goto(f"{live_server}{PAGE}?q=MQ-CNFORM-001")
    page.wait_for_selector("button:has-text('＋ 項目')", timeout=45000)
    page.wait_for_timeout(1200)
    assert len(hits) == 1, f"init() 應該只跑一次，實際打了 {len(hits)} 次案件 API"


@pytest.mark.e2e
def test_single_page_shows_everything_and_prefills_from_quotation(live_server, make_user, e2e_browser):
    """**沒有分頁**：所有區塊在同一頁同時看得到（使用者要求拿掉分頁）。
    而且新增時客戶、案件名稱、**地址與聯絡人**都要從報價單自動帶進來。

    「一次全部可見」刻意用 `state="visible"` 檢查而不是只看元素存在——分頁那版
    也「存在」，差別在看不看得見。
    """
    username, password = make_user(username="e2e_cnf1", role="superadmin")
    _seed_case()
    browser = e2e_browser
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    _login(page, live_server, username, password)
    page.goto(f"{live_server}{PAGE}?q=MQ-CNFORM-001")
    page.wait_for_selector("button:has-text('＋ 項目')", timeout=45000)

    assert page.input_value("input[x-model='form.customer_name']") == "網路測試客戶"
    assert page.input_value("input[x-model='form.project_name']") == "總部網路架構升級"
    # 地址與聯絡人（使用者指定要從報價單拉）
    assert page.input_value("input[x-model='form.site_address']") == "台中市西屯區工業區一路 1 號"
    assert page.input_value("input[x-model='form.recipient']") == "林經理"
    assert page.input_value("input[x-model='form.contact_phone']") == "04-2461-0000"

    # 四個區塊同時可見，不需要點任何分頁
    for marker in ("button:has-text('＋ 項目')",
                   "textarea[x-model='form.work_summary']",
                   "textarea[x-model='form.pending_items']",
                   "button:has-text('網路架構／資安')"):
        page.wait_for_selector(marker, state="visible", timeout=10000)
    # 分頁按鈕不該再存在
    assert page.locator("button.cnf-tab").count() == 0, "分頁應該已經拿掉了"
    assert not errors, f"頁面有 JS 錯誤：{errors}"


@pytest.mark.e2e
def test_preset_and_custom_labels_round_trip(live_server, make_user, e2e_browser):
    """套用預設用語 → 儲存 → 值真的寫進 data_json.labels。

    這是使用者這一輪的核心需求（完工單太偏向工程），綁錯不會報錯、只會安靜地存不進去。
    """
    username, password = make_user(username="e2e_cnf2", role="superadmin")
    _seed_case()
    browser = e2e_browser
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    _login(page, live_server, username, password)
    page.goto(f"{live_server}{PAGE}?q=MQ-CNFORM-001")
    page.wait_for_selector("button:has-text('＋ 項目')", timeout=45000)

    # 先加一個項目（送審門檻之一，也順便驗項目綁定）
    page.click("button:has-text('＋ 項目')")
    page.fill("input[x-model='it.description']", "核心交換器建置")

    # 套用「網路架構／資安」那組，再手動微調一欄（同一頁，不用切分頁）
    page.click("button:has-text('網路架構／資安')")
    page.fill("input[x-model=\"form.labels[f.key]\"] >> nth=0", "一、客戶與機房環境")

    page.click("button:has-text('儲存')")
    page.wait_for_selector(":text('已儲存')", timeout=45000)

    assert not errors, f"頁面有 JS 錯誤：{errors}"
    row = _row()
    assert row, "完工單沒有被建立"
    labels = (json.loads(row["data_json"] or "{}") or {}).get("labels") or {}
    assert labels.get("itemColumn") == "設備 / 設定項目", f"預設用語沒存進去：{labels}"
    assert labels.get("sectionCustomer") == "一、客戶與機房環境", "手動微調的那一欄沒存進去"
    assert json.loads(row["items_json"])[0]["description"] == "核心交換器建置"


@pytest.mark.e2e
def test_warranty_toggle_controls_whether_it_is_stored(live_server, make_user, e2e_browser):
    """保固勾掉＝月數存 0＝完工單上不顯示（比照報價單「留空就不印」）。"""
    username, password = make_user(username="e2e_cnf3", role="superadmin")
    _seed_case("MQ-CNFORM-002")
    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, username, password)
    page.goto(f"{live_server}{PAGE}?q=MQ-CNFORM-002")
    page.wait_for_selector("button:has-text('＋ 項目')", timeout=45000)

    # 預設是勾選的（12 個月），先確認提示文字在
    assert page.is_checked("input[type='checkbox']")
    page.uncheck("input[type='checkbox']")
    page.wait_for_selector(":text('不會出現')", timeout=10000)

    page.click("button:has-text('＋ 項目')")
    page.fill("input[x-model='it.description']", "零組件供應")
    page.click("button:has-text('儲存')")
    page.wait_for_selector(":text('已儲存')", timeout=45000)

    assert _row("MQ-CNFORM-002")["warranty_months"] == 0
