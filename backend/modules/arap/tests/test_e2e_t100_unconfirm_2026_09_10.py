"""瀏覽器端對端：T100 匯出的「已確認清單／反確認」畫面入口（2026-09-10 稽核補上）。

背景：後端 `/api/reports/t100-export/confirmed` 與 `/unconfirm` 早就存在，
`unconfirm` 的 docstring 自己寫著是「標記錯誤時的救援手段」，但前端只接了
vouchers / preview / confirm 三支——使用者按下「確認已匯入 T100（排除下次匯出）」
是一次標記整個日期區間的批次操作，按錯之後畫面上沒有任何回復方式。

這支測試釘住的是**入口存在且真的能走完**，不是後端邏輯（後端另有單元測試）：
  確認 → 事件從待確認清單消失、出現在已確認清單
  → 按「反確認」→ 從已確認清單消失、重新回到待確認清單
純後端測試攔不下「端點好好的但畫面沒有按鈕」這個缺口，只有真的開瀏覽器才行。
"""
import json
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")

import uvicorn
from tests._e2e_login import inject_login  # noqa: E402
from tests._ports import free_safe_port




def _login(page, base_url, username, password):
    return inject_login(page, base_url, username, password)


@pytest.mark.e2e
def test_t100_confirm_then_unconfirm_from_ui(live_server, make_user, e2e_browser):
    """確認 → 已確認清單看得到 → 反確認 → 回到待確認清單，全程只用畫面操作。"""
    username, password = make_user(username="e2e_t100", role="superadmin")

    import db
    conn = db.get_db()
    try:
        # 一筆已收款的成案，會被 _collect_t100_events 收成「收款」事件。
        # invoiceNo 是必要條件：T100 收款事件來自 _collect_tax_invoices()，
        # 那支只收「已填發票號碼」的款項（沒開發票就沒有銷項傳票可立）。
        data_json = json.dumps({
            "dealTag": "已成案",
            "caseRecord": {"payment": {"items": [{
                "id": 1, "type": "訂金", "pct": 100, "amount": 210000,
                "received": True, "receivedAt": "2026-06-15T00:00:00",
                "invoiceNo": "AB12345678",
            }]}},
        }, ensure_ascii=False)
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("MQ-T100E2E-001", "已送出", "T100測客", "T100測專", 210000, 200000, data_json,
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "2026-06-01"),
        )
        conn.commit()
    finally:
        conn.close()

    browser = e2e_browser
    page = browser.new_page()
    page.on("dialog", lambda d: d.accept())      # confirm() 一律按確定
    _login(page, live_server, username, password)
    # 🔴 2026-09-23 `FN3`：T100 匯出 UI 從**營運報表的頁籤**
    #    搬成**出納頁的子頁籤**（`cashierSub==='t100'`）。
    # ⚠️ 改的是**去哪裡、點什麼**，斷言一個字都沒動 ——
    #    這一題驗的是「反確認那個入口存不存在、按了有沒有效」，
    #    而那件事沒有跟著搬家改變。
    # 🔑 〈搬家要驗兩邊〉：舊位置沒有了由 `test_cashier_split_*`
    #    那一組守，這裡只負責**新位置仍然能走完整條路**。
    page.goto(f"{live_server}/pages/cashier.html")
    page.wait_for_selector(".ctab", timeout=20000)
    page.click('.ctab:has-text("T100匯出")')

    # 日期區間涵蓋這筆收款
    page.fill('input[x-model="t100Start"]', "2026-06-01")
    page.fill('input[x-model="t100End"]', "2026-06-30")
    page.click('button:has-text("重新整理預覽")')
    page.wait_for_function(
        "() => document.body.innerText.includes('MQ-T100E2E-001')"
        " || document.body.innerText.includes('T100測客')",
        timeout=20000)

    # 這個入口在修補之前根本不存在
    entry = page.locator('button:has-text("展開檢視／反確認")')
    entry.wait_for(state="visible", timeout=20000)

    # 確認已匯入
    page.click('button:has-text("確認已匯入 T100")')
    page.wait_for_function(
        "() => { const b = [...document.querySelectorAll('button')]"
        ".find(e => e.innerText.includes('展開檢視／反確認'));"
        "return !!b; }", timeout=20000)

    # 展開已確認清單，應該看得到剛剛那筆。等「值真的出現」而不是只等元素
    # 存在——按鈕會先於資料列渲染，只等按鈕會讀到空表格（2026-09-10 實測）。
    entry.click()
    page.wait_for_selector('button:has-text("反確認")', timeout=20000)
    page.wait_for_function(
        "() => document.body.innerText.includes('MQ-T100E2E-001')"
        " || document.body.innerText.includes('T100測客')",
        timeout=20000)
    confirmed_txt = page.locator("table.data-table").last.inner_text()
    assert "T100測客" in confirmed_txt or "MQ-T100E2E-001" in confirmed_txt, \
        f"已確認清單看不到剛確認的事件：{confirmed_txt[:300]}"

    # 反確認
    page.click('button:has-text("反確認")')
    page.wait_for_function(
        "() => !document.body.innerText.includes('撤銷中…')", timeout=20000)
    page.wait_for_function(
        "() => document.body.innerText.includes('這個日期區間內沒有已確認的事件')",
        timeout=20000)

    # 反確認之後，後端也真的不再有這筆標記
    conn = db.get_db()
    try:
        left = conn.execute("SELECT COUNT(*) c FROM t100_export_confirmations").fetchone()["c"]
    finally:
        conn.close()
    assert left == 0, f"反確認後資料庫仍留有 {left} 筆已確認標記"
