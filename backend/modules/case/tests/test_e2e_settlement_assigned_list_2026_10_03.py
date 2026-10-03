# -*- coding: utf-8 -*-
"""35c 精算頁二之一：已對應的材料申請／額外支出要看得出已對應（使用者 2026-10-03 截圖：
「已經被帶入了，但額外支出還有顯示不對應，已採用也未消失」）。

根因（用真瀏覽器重現）：報價品項的 id 是**數字**（`id: 8`）時，二之一下拉的 `:selected="it.id === u.itemId"` 是 number === string ⇒ false，
而且 `:value` 在選項還沒畫出來時就綁了 ⇒ 已對應的列一律顯示「（不對應，計入額外支出）」，但品項列的「額外支出 NT$…」與 API 都證明它已對應。
金額沒有重複計算（見 test_settlement_assigned_numbers_2026_10_03.py）；這是顯示問題。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._requires import requires_module  # noqa: E402
from tests.test_e2e_case_concurrent_edit_2026_09_24 import _login  # noqa: F401

pytestmark = requires_module("case", "本檔的題讀寫 M01（案件）的資料與頁面")

NO = "MQ-E2E-SC-1"


def _order(iid, name, total, **kw):
    d = {"itemId": iid, "itemName": name, "quantity": 2, "unit": "批", "unitPrice": total / 2, "totalPrice": total, "paidStatus": "pending",
         "paidAmount": 0, "paidDate": "", "invoiceDate": "2026-10-02", "notes": "備註-" + iid}
    d.update(kw)
    return d


def seed(item_ids=(7, 8), saved_items=None):
    """兩個報價品項（id 可為數字或字串）；材料申請 X 未對應、N 連到品項 2（link）、M 手動對應到品項 1；
    額外支出 1 手動對應到品項 2、2 未對應。回傳 (品項1 id, 品項2 id)。"""
    import db
    i1, i2 = item_ids
    items = [{"id": i1, "description": "交換器 24埠 PoE", "qty": 10, "unit": "台", "unitPrice": 2000, "amount": 20000, "cost": 1000},
             {"id": i2, "description": "線材 Cat6", "qty": 100, "unit": "米", "unitPrice": 10, "amount": 1000, "cost": 5}]
    data = {"items": items, "dealTag": "已成案",
            "caseRecord": {"materialOrders": [_order("X", "未對應料X", 250), _order("N", "連結料N", 800, quoteItemId=str(i2)), _order("M", "手動對應料M", 300)]},
            "settlement": {"status": "draft", "items": saved_items or [],
                           "offsets": [{"kind": "material", "ref": "M", "itemId": str(i1)}, {"kind": "extra", "ref": "1", "itemId": str(i2)}]}}
    c = db.get_db()
    try:
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, sales_person) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (NO, "已送出", "客", "案", 21000, 21000, json.dumps(data), "2026-10-02T00:00:00", "2026-10-02T00:00:00", "已成案", "sc_sc"))
        for mid in ("X", "N", "M"):
            c.execute("INSERT INTO case_material_approvals (quote_no, item_id, status) VALUES (?,?,?)", (NO, mid, "已核准"))
        for desc, cost, note in (("已被對應的支出", 700, "附註1"), ("還沒對應的支出", 900, "附註2")):
            c.execute("INSERT INTO case_extra_expenses (quote_no, category, description, qty, unit, unit_cost, total_cost, note, expense_date, doc_no, files_json, "
                      "created_by, created_by_name, created_by_inferred, payer_username, payer_name, created_at, updated_at, updated_by_name, status, approval_json) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,'[]',?,?,0,?,?,?,?,?,?,'{}')",
                      (NO, "其他", desc, 1, "式", cost, cost, note, "2026-10-02", "", "sc_sc", "sc_sc", "sc_sc", "sc_sc",
                       "2026-10-02T00:00:00", "2026-10-02T00:00:00", "sc_sc", "已核准"))
        c.commit()
    finally:
        c.close()
    return i1, i2


def open_page(live_server, e2e_browser, sa):
    page = e2e_browser.new_context(viewport={"width": 1400, "height": 1300}).new_page()
    _login(page, live_server, *sa)
    page.goto("%s/pages/settlement.html?no=%s" % (live_server, NO))
    page.locator('[data-testid="stl-unassigned"]').wait_for(state="visible", timeout=20000)
    return page


@pytest.mark.e2e
def test_mapped_rows_show_their_target_item_when_quote_item_ids_are_numbers(live_server, make_user, e2e_browser):
    """品項 id 是數字（真實報價單的樣子）：已對應的列的下拉必須顯示它對應到的品項；未對應的列仍是「不對應」。"""
    sa = make_user(username="sc_sc", role="superadmin")
    seed(item_ids=(7, 8))
    page = open_page(live_server, e2e_browser, sa)
    sel = lambda kind, ref: page.locator('[data-testid="stl-offset-%s-%s"]' % (kind, ref))   # noqa: E731
    assert sel("material", "M").input_value() == "7", "材料申請 M 已對應到品項 7，下拉卻顯示 %r" % sel("material", "M").input_value()
    assert sel("extra", "1").input_value() == "8", "額外支出 #1 已對應到品項 8，下拉卻顯示 %r" % sel("extra", "1").input_value()
    assert sel("material", "X").input_value() == "" and sel("extra", "2").input_value() == ""
