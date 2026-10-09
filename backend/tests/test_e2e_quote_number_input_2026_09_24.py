"""瀏覽器端對端：報價單數字欄位的輸入解析（2026-09-24）。

- 數量／成本／單價／運費／折讓原本是 type=number：貼上「12,000」時瀏覽器給空值，
  x-model.number 就把它變成 0。現在接受千分位與全形數字；解析不了就標紅、不更新、不存檔
- 毛利率清空：原本 parseFloat('')/100 = NaN ⇒ 單價與金額 NaN（加總時當 0），
  checkApproval() 的 NaN < 0.30 為 false ⇒ 跳過「需審核」。現在清空不更新，失焦還原

裁示 H1～H3（hichan-0a 代裁，待使用者確認）。
"""
from tests._requires import requires_module  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
import threading

import pytest

pytest.importorskip("playwright.sync_api")

import uvicorn
from tests._e2e_login import inject_login  # noqa: E402
from tests._ports import free_safe_port
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')

QUOTE_NO = "MQ-202609-071"
PRICE = "tbody input.cell-input.num:not(.internal):not(.qty-input)"
COST = "tbody input.cell-input.num.internal[placeholder='0']"
MARGIN = "tbody input[max='99.99']"
DATA = "Alpine.$data(document.querySelector('[x-data]'))"




def _login(page, base_url, username, password):
    return inject_login(page, base_url, username, password)


def _seed():
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, "
            "pretax, data_json, created_at, updated_at, deal_tag, quote_date) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (QUOTE_NO, "草稿", "解析客戶", "解析專案", 1575, 1500,
             json.dumps({"quoteNo": QUOTE_NO, "customerName": "解析客戶",
                         "projectName": "解析專案", "status": "草稿",
                         "items": [{"id": 1, "description": "品項 A", "qty": 1, "cost": 1000,
                                    "margin": 0.35, "unitPrice": 1650, "amount": 1650}],
                         "tot": {"total": 1575, "pretax": 1500,
                                 "directMarginPct": 0, "netMarginPct": 0}},
                        ensure_ascii=False),
             "2026-09-01T00:00:00", "2026-09-01T00:00:00", "", "2026-09-01"),
        )
        conn.commit()
    finally:
        conn.close()


def _watch_writes(page):
    """記錄頁面送出的存檔請求（PUT／PATCH／POST /api/quotations…）。⚠️ 負向斷言（「標紅時不可以存檔」）要看「請求有沒有送出」，
    不能只看資料庫：`time.sleep` 睡著時 sync Playwright 不處理事件，請求若卡在瀏覽器裡，資料庫當然沒變 ⇒ 假綠（e2e 睡覺等待稽核 2026-10-02）。"""
    writes = []
    page.on("request", lambda r: writes.append((r.method, r.url)) if r.method in ("PUT", "PATCH", "POST") and "/api/quotations" in r.url else None)
    return writes


def _wait_dialog(page, dialogs, ms=5000):
    """等對話框訊息出現（用 Playwright 的等待，才會處理事件）；回傳訊息清單。"""
    waited = 0
    while not dialogs and waited < ms:
        page.wait_for_timeout(100)
        waited += 100
    return dialogs


def _saved_item():
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (QUOTE_NO,)).fetchone()
    finally:
        conn.close()
    return json.loads(row["data_json"])["items"][0]


def _open(page, base):
    page.goto(f"{base}/pages/quotation-form.html?id={QUOTE_NO}")
    page.wait_for_function("() => document.body.innerText.includes('解析客戶')", timeout=20000)
    page.evaluate(f"{DATA}.showCostCols = true")
    page.locator(MARGIN).wait_for(state="visible")


@pytest.mark.e2e
def test_amount_accepts_thousand_separators_and_fullwidth(live_server, make_user, e2e_browser):
    username, password = make_user(username="e2e_num1", role="superadmin")
    _seed()
    browser = e2e_browser
    page = browser.new_page()
    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))
    _login(page, live_server, username, password)
    _open(page, live_server)

    page.fill(PRICE, "12,000")
    assert page.evaluate(f"{DATA}.q.items[0].unitPrice") == 12000
    assert page.evaluate(f"{DATA}.q.items[0].amount") == 12000

    page.fill(PRICE, "１２，５００")
    assert page.evaluate(f"{DATA}.q.items[0].unitPrice") == 12500

    page.fill(COST, "3,000")
    assert page.evaluate(f"{DATA}.q.items[0].cost") == 3000

    # 解析不了：標紅、數值不動、不存檔
    page.fill(PRICE, "12a")
    assert "num-bad" in (page.get_attribute(PRICE, "class") or "")
    assert page.evaluate(f"{DATA}.q.items[0].unitPrice") == 12500
    writes = _watch_writes(page)
    page.click('button:has-text("儲存草稿")')
    assert any("無法辨識" in m for m in _wait_dialog(page, dialogs)), dialogs
    page.wait_for_timeout(1000)                                                             # 給「若有送出」的請求時間出現（Playwright 等待，會處理事件）
    assert writes == [], "標紅時不可以送出任何存檔請求：%s" % writes                        # 負向斷言看請求，不只看資料庫
    assert _saved_item()["unitPrice"] == 1650, "標紅時不可以存檔"

    # 修正後可以存
    page.fill(PRICE, "12,500")
    assert "num-bad" not in (page.get_attribute(PRICE, "class") or "")
    page.click('button:has-text("儲存草稿")')
    for _ in range(100):
        if _saved_item().get("unitPrice") == 12500:
            break
        page.wait_for_timeout(100)
    assert _saved_item()["unitPrice"] == 12500
    assert writes, "正對照：修正後的存檔請求有被記錄到（否則上面的『沒有請求』沒有意義）"


@pytest.mark.e2e
def test_clearing_margin_keeps_previous_value_and_review(live_server, make_user, e2e_browser):
    username, password = make_user(username="e2e_num2", role="superadmin")
    _seed()
    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, username, password)
    _open(page, live_server)

    page.fill(MARGIN, "20")
    assert page.evaluate(f"{DATA}.q.items[0].margin") == 0.2
    assert page.evaluate(f"{DATA}.needsApproval") is True

    page.fill(MARGIN, "")
    assert page.evaluate(f"{DATA}.q.items[0].margin") == 0.2, "清空不可以變成 NaN／0"
    amount = page.evaluate(f"{DATA}.q.items[0].amount")
    assert isinstance(amount, (int, float)) and amount > 0, amount
    assert page.evaluate(f"{DATA}.needsApproval") is True, "清空期間「需審核」不可以消失"

    page.locator(MARGIN).blur()
    assert page.input_value(MARGIN) == "20", "失焦還原成上一個值"


def _saved_data():
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (QUOTE_NO,)).fetchone()
    finally:
        conn.close()
    return json.loads(row["data_json"])


@pytest.mark.e2e
def test_internal_cost_inputs_accept_separators_and_block_bad_values(live_server, make_user, e2e_browser):
    """N14：金額欄位接受千分位與全形數字；無法辨識時標紅不存。（原本打在『內部成本區五個間接費』；第 48 班使用者裁示五項拿掉，
    改打同一套 `setNumField`／`numShown` 的運費與折讓欄位。）"""
    username, password = make_user(username="e2e_num3", role="superadmin")
    _seed()
    browser = e2e_browser
    page = browser.new_page()
    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))
    _login(page, live_server, username, password)
    _open(page, live_server)
    assert page.locator('input[data-num="indirectLogistics"]').count() == 0, "五項間接成本輸入已拿掉"
    FREIGHT = 'xpath=//label[normalize-space()="運費"]/following::input[1]'
    page.locator(FREIGHT).wait_for(state="visible")
    page.evaluate(f"{DATA}.q.showDiscount = true")
    DISC = 'xpath=//label[contains(normalize-space(), "折讓")]/following::input[1]'
    page.fill(FREIGHT, "12,000")
    assert page.evaluate(f"{DATA}.q.freight") == 12000
    page.fill(DISC, "３，５００")
    assert page.evaluate(f"{DATA}.q.discount") == 3500

    page.fill(DISC, "35oo")
    assert "num-bad" in (page.get_attribute(DISC, "class") or "")
    assert page.evaluate(f"{DATA}.q.discount") == 3500
    writes = _watch_writes(page)
    page.click('button:has-text("儲存草稿")')
    assert any("無法辨識" in m for m in _wait_dialog(page, dialogs)), dialogs
    page.wait_for_timeout(1000)
    assert writes == [], "標紅時不可以送出任何存檔請求：%s" % writes
    assert _saved_data().get("freight") != 12000, "標紅時不可以存檔"

    page.fill(DISC, "3,500")
    page.click('button:has-text("儲存草稿")')
    for _ in range(100):
        if _saved_data().get("freight") == 12000:
            break
        page.wait_for_timeout(100)
    d = _saved_data()
    assert d["freight"] == 12000 and d["discount"] == 3500
    assert writes, "正對照：修正後的存檔請求有被記錄到"
