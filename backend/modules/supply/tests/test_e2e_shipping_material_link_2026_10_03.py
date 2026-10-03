# -*- coding: utf-8 -*-
"""34-S2 畫面 e2e：出貨單「從材料申請帶入」。
列出已到料且有剩餘可出貨量的材料申請（扣掉其他出貨單占用）→ 數量預設剩餘、超量被擋 → 帶入後該列有「連結材料申請」標記、序號按鈕反灰 →
改列上數量時連結數量跟著改 → 存檔後資料庫 items_json 帶 materialLink → 送審前提醒（E6）列出沒連結的剩餘材料申請，仍可送出。
headless；等終點（資料庫／頁面狀態）。"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.e2e

from tests._e2e_login import inject_login  # noqa: E402
from tests._ui_dialogs import answer_confirm  # noqa: E402
from modules.supply.tests.test_shipping_material_link_2026_10_03 import DOC, ITEM, Q, _note, world  # noqa: E402,F401

DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"


def _items(no):
    import db
    c = db.get_db()
    try:
        return json.loads(c.execute("SELECT items_json FROM shipping_notes WHERE note_no=?", (no,)).fetchone()["items_json"])
    finally:
        c.close()


@pytest.fixture()
def ui(world, live_server, new_context):
    client, h = world
    other = _note(client, h, [{"description": "電纜", "materialLink": {"materialItemId": ITEM, "docCode": DOC, "qty": 4}}], status="已核准")   # 別張已出貨 4 ⇒ 剩餘 6
    import db
    cn = db.get_db()
    cn.execute("UPDATE shipping_notes SET data_json=? WHERE note_no=?", (json.dumps({"approval": {"tiers": [], "currentTier": 0, "status": "approved"}}), other))   # 清單頁會讀 approval.tiers
    cn.commit()
    cn.close()
    mine = _note(client, h, [])
    pg = new_context(viewport={"width": 1500, "height": 1200}).new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e) + " | " + str(getattr(e, "stack", ""))[:500]))
    inject_login(pg, live_server, "sl_super", "Test-Pass-123")
    pg.goto("%s/pages/case-management.html?q=%s&tab=shipping" % (live_server, Q))
    pg.wait_for_function("() => { const d = %s; return !!(d && d.selected && d.selected.quote_no === '%s' && d.shippingNotes && d.shippingNotes.length === 2) }" % (DATA_JS, Q), timeout=20000)
    pg.locator("button", has_text="編輯").first.click()
    pg.wait_for_function("() => %s.showShippingModal && %s.editShippingNoteNo" % (DATA_JS, DATA_JS), timeout=8000)
    yield pg, client, h, mine
    assert not errors, errors


def _open_panel(pg):
    pg.click('[data-testid="msh-open"]')
    pg.locator('[data-testid="msh-row-%s"]' % DOC).wait_for(state="visible", timeout=15000)


def test_panel_lists_remaining_and_import_adds_a_linked_row(ui):
    pg, client, h, mine = ui
    _open_panel(pg)
    txt = pg.locator('[data-testid="msh-row-%s"]' % DOC).inner_text()
    assert "已到料 10" in txt and "其他出貨單 4" in txt and "剩餘 6" in txt, txt
    assert pg.locator('[data-testid="msh-qty-%s"]' % DOC).input_value() == "6"            # 預設剩餘
    pg.locator('[data-testid="msh-qty-%s"]' % DOC).fill("5")
    pg.locator('[data-testid="msh-row-%s"] input[type=checkbox]' % DOC).check()
    pg.click('[data-testid="msh-import"]')
    pg.locator('[data-testid="ship-link-tag"]').wait_for(state="visible", timeout=8000)
    assert DOC in pg.locator('[data-testid="ship-link-tag"]').inner_text()
    assert pg.locator('[data-testid="ship-qty-linked"]').input_value() == "5"
    serial_btn = pg.locator('tr:has([data-testid="ship-link-tag"]) button:has-text("選料號")')
    assert serial_btn.is_disabled()                                                         # 與庫存序號同列互斥
    # 改列上數量 ⇒ 連結數量跟著改；存檔後資料庫帶 materialLink
    pg.locator('[data-testid="ship-qty-linked"]').fill("3")
    pg.locator("button", has_text="儲存出貨單").click()
    pg.wait_for_function("() => !%s.shippingSaving && !%s.showShippingModal" % (DATA_JS, DATA_JS), timeout=15000)
    it = _items(mine)
    assert len(it) == 1 and it[0]["materialLink"] == {"materialItemId": ITEM, "docCode": DOC, "qty": 3} and it[0]["qty"] == 3, it


def test_over_remaining_is_refused_in_the_panel_and_nothing_is_added(ui):
    pg, client, h, mine = ui
    _open_panel(pg)
    pg.locator('[data-testid="msh-qty-%s"]' % DOC).fill("7")                                # 剩餘只有 6
    pg.locator('[data-testid="msh-row-%s"] input[type=checkbox]' % DOC).check()
    pg.click('[data-testid="msh-import"]')
    pg.locator('[data-testid="msh-err"]').wait_for(state="visible", timeout=5000)
    assert "不超過剩餘可出貨量 6" in pg.locator('[data-testid="msh-err"]').inner_text()
    assert pg.evaluate("() => %s.shippingForm.items.length" % DATA_JS) == 0


def test_submit_warns_about_unlinked_remaining_but_does_not_block(ui):
    pg, client, h, mine = ui
    pg.evaluate("() => { %s.shippingForm.items.push({ id: 1, description: '一般品項', brand: '', qty: 1, unit: '台', notes: '' }) }" % DATA_JS)
    pg.locator("button", has_text="儲存出貨單").click()
    pg.wait_for_function("() => !%s.shippingSaving && !%s.showShippingModal" % (DATA_JS, DATA_JS), timeout=15000)
    pg.evaluate("(no) => { %s.submitShippingNote({ noteNo: no }) }" % DATA_JS, mine)               # 與清單上「送出」鈕同一個函式
    msg = answer_confirm(pg, ok=True, expect="提醒")                                          # E6：不擋，只提醒
    assert DOC in msg and "剩餘 6" in msg, msg
    import db

    def _st():
        c = db.get_db()
        try:
            return c.execute("SELECT status FROM shipping_notes WHERE note_no=?", (mine,)).fetchone()["status"]
        finally:
            c.close()
    for _ in range(50):                                                                       # 等送審請求完成（等終點，不 sleep）
        if _st() != "草稿":
            break
        pg.wait_for_timeout(200)
    assert _st() in ("待審核", "已核准"), _st()


def test_material_card_shows_applied_arrived_shipped_and_the_note_numbers(world, live_server, new_context):
    """34-S3：案件頁材料申請卡片：已申請／已到料／已出貨（占用中）＋出貨單號；沒到料也沒出貨連動的那一筆不顯示。"""
    client, h = world
    a = _note(client, h, [{"description": "電纜", "materialLink": {"materialItemId": ITEM, "docCode": DOC, "qty": 4}}], status="已核准")
    b = _note(client, h, [{"description": "電纜", "materialLink": {"materialItemId": ITEM, "docCode": DOC, "qty": 2}}], status="待審核")
    import db
    cn = db.get_db()
    for no in (a, b):
        cn.execute("UPDATE shipping_notes SET data_json=? WHERE note_no=?", (json.dumps({"approval": {"tiers": [], "currentTier": 0}}), no))
    cn.commit()
    cn.close()
    pg = new_context(viewport={"width": 1500, "height": 1200}).new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(pg, live_server, "sl_super", "Test-Pass-123")
    pg.goto("%s/pages/case-management.html?q=%s" % (live_server, Q))
    pg.wait_for_selector('.cm-tab:has-text("財務")', timeout=20000)
    pg.click('.cm-tab:has-text("財務")')
    pg.wait_for_selector('[data-testid="mo-card-%s"]' % ITEM, timeout=20000)
    pg.click('[data-testid="ml-tab-all"]')
    t = pg.locator('[data-testid="ml-ship-%s"]' % ITEM)
    t.wait_for(state="visible", timeout=15000)
    assert t.inner_text() == "已申請 10／已到料 10／已出貨 4（占用中 2）", t.inner_text()
    notes = pg.locator('[data-testid="ml-ship-notes-%s"]' % ITEM).inner_text()
    assert a in notes and b in notes, notes
    assert pg.locator('[data-testid="ml-ship-it2"]').is_hidden()
    assert not errors, errors
