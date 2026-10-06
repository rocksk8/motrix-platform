# -*- coding: utf-8 -*-
"""第 43 班 e2e：報價品項「已出貨數量」的畫面（使用者裁示選項 B）。
- 案件頁出貨單編輯視窗：「從報價單匯入」的列存檔後資料庫的 items_json 帶 quoteItemId（舊單與手動列沒有）；每列「已累計出貨」＝該報價品項所有出貨單合計，
  沒有對應的列顯示「—」；占用中（待審核）以小字顯示。（出貨單清單本來就不帶品項明細，只有 itemCount，所以欄位放在編輯視窗。）
- 精算頁：報價品項表「已出貨/數量」欄；沒有可歸屬紀錄的品項顯示「—」
觀測點：資料庫落地值與 DOM 文字；等終點，不 sleep。"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.e2e

from tests._e2e_login import inject_login  # noqa: E402
from modules.supply.tests.test_shipping_material_link_2026_10_03 import ITEM, Q, _note, world, L  # noqa: E402,F401
from tests.test_shipped_qty_2026_10_06 import Qi, sq  # noqa: E402,F401

DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"


def _items(no):
    import db
    c = db.get_db()
    try:
        return json.loads(c.execute("SELECT items_json FROM shipping_notes WHERE note_no=?", (no,)).fetchone()["items_json"])
    finally:
        c.close()


def _page(live_server, new_context, url):
    pg = new_context(viewport={"width": 1600, "height": 1200}).new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(pg, live_server, "sl_super", "Test-Pass-123")
    pg.goto(url)
    return pg, errors


def test_import_from_quote_stamps_quote_item_id_and_the_list_shows_cumulative(sq, live_server, new_context):
    client, h = sq
    _note(client, h, [Qi(5)], status="已核准")                                              # q2 已出貨 5
    _note(client, h, [Qi(2)], status="待審核")                                              # q2 占用 2
    _note(client, h, [{"description": "舊單攝影機", "qty": 8, "unit": "台"}], status="已核准")   # 舊單：沒有 quoteItemId ⇒ 不影響任何品項的累計
    mine = _note(client, h, [])
    pg, errors = _page(live_server, new_context, "%s/pages/case-management.html?q=%s&tab=shipping" % (live_server, Q))
    pg.wait_for_function("() => { const d = %s; return !!(d && d.selected && d.selected.quote_no === '%s' && d.shippingNotes && d.shippingNotes.length === 4) }" % (DATA_JS, Q), timeout=25000)
    pg.wait_for_function("() => %s.itemShipped && %s.itemShipped.items && %s.itemShipped.items.q2 && %s.itemShipped.items.q2.attributed" % (DATA_JS, DATA_JS, DATA_JS, DATA_JS), timeout=15000)
    # 新增出貨單 → 從報價單匯入 → 存檔：資料庫帶 quoteItemId
    pg.evaluate("() => %s.openNewShippingNote()" % DATA_JS)
    pg.wait_for_function("() => %s.showShippingModal" % DATA_JS, timeout=8000)
    pg.evaluate("() => { %s.shippingForm.items = []; %s.importItemsFromQuote() }" % (DATA_JS, DATA_JS))
    stamped = pg.evaluate("() => %s.shippingForm.items.map(i => [i.type || '', i.description, i.quoteItemId || ''])" % DATA_JS)
    assert stamped == [["", "電纜", "q1"], ["header", "標題", ""], ["", "攝影機", "q2"], ["", "配件", "q3"], ["", "另一品項", "q4"]], stamped
    # 編輯視窗每列的「已累計出貨」：q2＝所有出貨單合計（已核准 5、占用 2）／報價 8；沒有可歸屬紀錄的品項「—」（不是 0）
    pg.locator('[data-testid="ship-cum-2"]').wait_for(timeout=8000)
    cum = lambda i: pg.locator('[data-testid="ship-cum-%d"]' % i).inner_text().replace("\n", " ").strip()
    assert cum(2) == "5 / 8 占用 2" and cum(0) == "—" and cum(3) == "—" and cum(4) == "—", [cum(i) for i in (0, 2, 3, 4)]
    pg.evaluate("() => { %s.addShippingItem() }" % DATA_JS)                                    # 手動新增的列：沒有 quoteItemId
    assert pg.evaluate("() => %s.shippingForm.items.slice(-1)[0].quoteItemId === undefined" % DATA_JS) is True
    pg.locator("button", has_text="儲存出貨單").click()
    pg.wait_for_function("() => !%s.shippingSaving && !%s.showShippingModal" % (DATA_JS, DATA_JS), timeout=15000)
    import db
    c = db.get_db()
    try:
        new_no = [r["note_no"] for r in c.execute("SELECT note_no FROM shipping_notes WHERE quote_no=? ORDER BY id DESC", (Q,)).fetchall() if r["note_no"] != mine][0]             if False else c.execute("SELECT note_no FROM shipping_notes WHERE quote_no=? ORDER BY id DESC LIMIT 1", (Q,)).fetchone()["note_no"]
    finally:
        c.close()
    saved = _items(new_no)
    assert [i.get("quoteItemId") for i in saved if i.get("type") != "header"] == ["q1", "q2", "q3", "q4", None], saved
    assert not errors, errors


def test_settlement_page_shows_shipped_over_ordered_and_dash_when_unattributed(sq, live_server, new_context):
    client, h = sq
    _note(client, h, [Qi(5)], status="已核准")                                              # q2：5 / 8
    _note(client, h, [Qi(2)], status="待審核")                                              # q2 占用 2
    _note(client, h, [{**L(4), "quoteItemId": "q1", "qty": 4}], status="已核准")             # q1 經材料申請：4 / 10（帶 materialLink 的列）
    pg, errors = _page(live_server, new_context, "%s/pages/settlement.html?no=%s" % (live_server, Q))
    pg.locator('[data-testid="stl-shipped-q2"]').wait_for(timeout=25000)
    pg.wait_for_function("() => document.querySelector('[data-testid=\"stl-shipped-q2\"]').innerText.includes('5 / 8')", timeout=15000)
    txt = lambda q: pg.locator('[data-testid="stl-shipped-%s"]' % q).inner_text().replace("\n", " ").strip()
    assert txt("q2") == "5 / 8 占用 2", txt("q2")
    assert txt("q1") == "4 / 10", txt("q1")
    assert txt("q3") == "—" and txt("q4") == "—", "沒有可歸屬的出貨紀錄 ⇒ 「—」不是 0"
    assert "已出貨/數量" in pg.locator("th", has_text="已出貨/數量").first.inner_text()
    assert not errors, errors
