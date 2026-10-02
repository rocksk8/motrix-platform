# -*- coding: utf-8 -*-
"""32-S4d 預審（c7）：材料申請連結的前端狀態（case-management-mlink.js）在**切換案件**時是否洩漏。
斷言是「應該怎樣」：切到另一張案件後，匯入面板、清單、頁籤、訊息都回到初始；紅燈＝發現（見 audit 回報）。
不隨產品出貨。"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._requires import requires_module  # noqa: E402
from tests._e2e_login import inject_login  # noqa: E402

pytestmark = requires_module("case", "本檔讀寫 M01（案件）的資料與頁面")

A, B = "MQ-LEAK-A", "MQ-LEAK-B"
APP = "window.Alpine.$data(document.querySelector('[x-data]'))"


def _seed():
    import db
    c = db.get_db()
    try:
        for no, desc, qty in ((A, "A案的交換器", 10), (B, "B案的另一個品項", 3)):                        # 兩案的報價品項 id 相同（'a'）、內容不同
            data = {"items": [{"id": "a", "description": desc, "qty": qty, "unit": "台", "unitPrice": 2000, "amount": qty * 2000, "cost": 1000}],
                    "dealTag": "已成案", "caseRecord": {"materialOrders": [
                        {"itemId": "K-" + no[-1], "itemName": "既有申請", "quantity": 1, "unit": "台", "unitPrice": 100, "totalPrice": 100, "paidStatus": "pending",
                         "paidAmount": 0, "paidDate": "", "notes": "", "invoiceDate": "", "supplierId": 1, "quoteItemId": "a"}]}}
            c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, quote_date)"
                      " VALUES (?,?,?,?,?,?,?,?,?,?,?)", (no, "已送出", "客" + no[-1], "案" + no[-1], 1, 1, json.dumps(data, ensure_ascii=False),
                                                           "2026-10-02T00:00:00", "2026-10-02T00:00:00", "已成案", "2026-10-02"))
            c.execute("INSERT INTO case_material_approvals (quote_no, item_id, status) VALUES (?,?,'待審核')", (no, "K-" + no[-1]))
        c.execute("INSERT INTO suppliers (id, name, code, created_at, updated_at) VALUES (1, '甲', 'S-1', '2026-10-02', '2026-10-02')")
        c.commit()
    finally:
        c.close()


def _open(live_server, make_user, new_context):
    u, p = make_user(username="leak_sa", role="superadmin")
    _seed()
    page = new_context(viewport={"width": 1400, "height": 1000}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, u, p)
    page.goto("%s/pages/case-management.html?q=%s" % (live_server, A))
    page.wait_for_selector('.cm-tab:has-text("財務")', timeout=20000)
    page.click('.cm-tab:has-text("財務")')
    page.wait_for_function("() => document.querySelector('[data-testid=ml-tab-approved]')", timeout=20000)
    page.errors = errors
    return page


def _switch_to_b(page):
    page.evaluate("async () => { await %s.selectCase('%s') }" % (APP, B))
    page.wait_for_function("() => %s.selected && %s.selected.quote_no === '%s'" % (APP, APP, B), timeout=20000)
    page.click('.cm-tab:has-text("財務")')                                      # 切案後回到預設分頁；再開財務分頁才會載入材料申請
    page.wait_for_function("() => !%s.moLoading && %s.materialOrders.length > 0" % (APP, APP), timeout=20000)


A_LINE = "{ poDocCode: 'PO-A', poLine: 1, summary: 'A案的採購單明細', qty: 5, unit: '台', unitCost: 100, status: '已核准', quoteItemId: 'a' }"


@pytest.mark.e2e
def test_open_import_panel_and_lists_do_not_survive_a_case_switch(live_server, make_user, new_context):
    """33-M1：匯入面板只剩採購單明細（沒有報價品項入口）；A 案的面板、明細清單、勾選切案後都要回到初始。"""
    page = _open(live_server, make_user, new_context)
    page.click('[data-testid="ml-open-po"]')
    page.wait_for_function("() => !%s.mlLoadingList" % APP, timeout=15000)
    page.evaluate("() => { %s.mlPoLines = [%s]; %s.mlPick['p:PO-A#1'] = true }" % (APP, A_LINE, APP))
    assert page.evaluate("() => %s.mlPoChoices().length" % APP) == 1
    _switch_to_b(page)
    st = page.evaluate("() => ({ panel: %s.mlPanel, lines: %s.mlPoLines.map(i => i.summary), pick: %s.mlPick, msg: %s.mlMsg, choices: %s.mlPoChoices().map(i => i.summary) })" % ((APP,) * 5))
    print("after switch to B:", st)
    assert st["panel"] == "" and st["lines"] == [] and st["choices"] == [] and st["pick"] == {}, "切到 B 後，A 案的匯入面板與採購單明細清單不該還在（可帶入 A 案的明細到 B 案）：%s" % st


@pytest.mark.e2e
def test_import_after_switch_must_not_link_a_foreign_po_line(live_server, make_user, new_context):
    page = _open(live_server, make_user, new_context)
    page.click('[data-testid="ml-open-po"]')
    page.wait_for_function("() => !%s.mlLoadingList" % APP, timeout=15000)
    page.evaluate("() => { %s.mlPoLines = [%s] }" % (APP, A_LINE))
    _switch_to_b(page)
    page.evaluate("() => { %s.mlPick['p:PO-A#1'] = true; %s.mlImport() }" % (APP, APP))
    rows = page.evaluate("() => %s.materialOrders.filter(m => m._saved === false).map(m => [m.itemName, m.poDocCode, m.quantity])" % APP)
    print("imported into B:", rows)
    assert rows == [], "A 案的採購單明細被帶進 B 案：%s" % rows


@pytest.mark.e2e
def test_tab_and_message_reset_on_switch(live_server, make_user, new_context):
    page = _open(live_server, make_user, new_context)
    page.evaluate("() => { %s.mlTab = 'review'; %s.mlMsg = '已帶入 2 筆（草稿）：A 案的訊息' }" % (APP, APP))
    _switch_to_b(page)
    st = page.evaluate("() => ({ tab: %s.mlTab, msg: %s.mlMsg })" % (APP, APP))
    print("tab/msg after switch:", st)
    assert st == {"tab": "approved", "msg": ""}, st


@pytest.mark.e2e
def test_late_response_of_the_previous_case_does_not_land(live_server, make_user, new_context):
    """mlOpen 的回應要比對「還在不在同一張案件」：A 案的 material-po-lines 回應晚於切換抵達 ⇒ 不可寫進 mlPoLines。"""
    page = _open(live_server, make_user, new_context)
    held = []
    page.route("**/%s/material-po-lines" % A, lambda route: held.append(route))
    page.evaluate("() => { %s.mlOpen('po') }" % APP)                                 # 不 await：請求被扣住
    page.wait_for_function("() => true")
    _switch_to_b(page)
    assert held, "前提：A 案的清單請求被扣住"
    held[0].continue_()
    page.wait_for_timeout(1500)
    st = page.evaluate("() => ({ lines: %s.mlPoLines.map(i => i.summary), loading: %s.mlLoadingList })" % (APP, APP))
    print("late response:", st)
    assert st["lines"] == [], "A 案晚到的回應不該寫進 B 案的畫面：%s" % st
