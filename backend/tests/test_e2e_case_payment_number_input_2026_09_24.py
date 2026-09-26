"""瀏覽器端對端：案件款項明細的金額輸入接受千分位與全形數字（N14 擴大範圍，2026-09-24）。

過去含稅／未稅是 type=number＋`+$event.target.value`：貼上「12,000」時瀏覽器給空字串 ⇒ 變成 0 並自動存檔。
實收金額／手續費是 x-model.number：同樣貼不進千分位。改成文字框，規則與報價單 parseNumInput() 相同；
無法辨識 ⇒ 標紅、數值不更新、不存檔。觀測點打在資料庫落地值。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
import time

import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_e2e_case_concurrent_edit_2026_09_24 import (  # noqa: F401  (live_server 是 fixture)
    DATA_JS, _login,
)
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')

NO = "MQ-PAYNUM-001"


def _seed():
    import db
    cr = {"payment": {"items": [
        {"id": 1, "type": "訂金款", "pct": 30, "amount": 30000, "received": True, "receivedAt": "2026-09-01",
         "actualAmount": 30000, "feeAmount": 0, "note": "", "invoiceNo": ""},
        {"id": 2, "type": "交貨款", "pct": 30, "amount": 30000, "received": False, "note": "", "invoiceNo": ""},
        # 最後一期會被自動平衡成「總額 − 其他期」，所以輸入測試打在中間那一期
        {"id": 3, "type": "尾款", "pct": 40, "amount": 40000, "received": False, "note": "", "invoiceNo": ""}]},
        "materials": []}
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (NO, "已送出", "客", "案", 100000, 95238,
             json.dumps({"dealTag": "已成案", "caseRecord": cr}, ensure_ascii=False), now, now, "已成案"))
        conn.commit()
    finally:
        conn.close()


def _items():
    import db
    conn = db.get_db()
    try:
        d = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()[0])
    finally:
        conn.close()
    return {i["id"]: i for i in d["caseRecord"]["payment"]["items"]}


def _save(page):
    return page.evaluate(f"async () => {{ const c = {DATA_JS}; await c.saveCaseRecord(); return c.saveMsg }}")


@pytest.mark.e2e
def test_payment_amounts_accept_separators_and_block_bad_values(live_server, make_user, e2e_browser):
    u = make_user(username="pn_admin", role="admin")
    _seed()
    browser = e2e_browser
    page = browser.new_context().new_page()
    page.on("dialog", lambda d: d.accept())
    _login(page, live_server, *u)
    page.goto(f"{live_server}/pages/case-management.html?q={NO}&tab=fin")
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}'", timeout=20000)
    page.evaluate(f"() => {{ {DATA_JS}.activeTab = 'fin' }}")
    WT2 = 'input[data-num="wt-2"]'
    ACT1 = 'input[data-num="act-1"]'
    FEE1 = 'input[data-num="fee-1"]'
    page.locator(WT2).wait_for(state="visible", timeout=10000)

    page.fill(WT2, "30,500")
    page.locator(WT2).blur()
    page.fill(ACT1, "２９，９８５")
    page.fill(FEE1, "15")
    assert "已儲存" in _save(page)
    it = _items()
    assert it[2]["amount"] == 30500, "含稅貼上千分位不可以變成 0"
    assert it[3]["amount"] == 39500, "尾款跟著平衡"
    assert it[1]["actualAmount"] == 29985 and it[1]["feeAmount"] == 15

    page.fill(FEE1, "1o")
    assert "num-bad" in (page.get_attribute(FEE1, "class") or "")
    msg = _save(page)
    assert "無法辨識" in msg, msg
    time.sleep(0.3)
    assert _items()[1]["feeAmount"] == 15, "標紅時不可以存檔"

    page.fill(FEE1, "20")
    assert "num-bad" not in (page.get_attribute(FEE1, "class") or "")
    assert "已儲存" in _save(page)
    assert _items()[1]["feeAmount"] == 20
