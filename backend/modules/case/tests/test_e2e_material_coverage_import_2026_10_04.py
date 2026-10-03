# -*- coding: utf-8 -*-
"""34-M1 UI（E4）：「從採購單帶入」依報價品項分組——一個品項一列，數量／金額是該品項全部已核准採購單行的合計（後端涵蓋快照給，畫面不運算）。
品項 a 有兩張已核准採購單（3 台＋2 台）→ 一組「5 台／小計 5000／2 行」→ 帶入成一列、單價欄唯讀 → 數量往下調到 4 ⇒ 小計仍 5000（單價換算）→
選供應商、存檔、送審通過（涵蓋檢查過關）→ 再開面板：品項 a 被標「已有材料申請…→ 請用變更申請」且不能勾。headless；等終點。"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.e2e

from tests._requires import requires_module  # noqa: E402
from tests._e2e_login import inject_login  # noqa: E402
from tests._material_po import approved_po  # noqa: E402

pytestmark = [pytest.mark.e2e, requires_module("case", "本檔讀寫 M01（案件）的資料與頁面")]

NO = "MQ-COV-E2E-1"
PANEL = "#fin-material-orders"
Q = {"items": [{"id": "a", "description": "交換器", "qty": 10, "unit": "台", "unitPrice": 2000, "amount": 20000, "cost": 1000},
               {"id": "b", "description": "線材", "qty": 100, "unit": "米", "unitPrice": 10, "amount": 1000, "cost": 5}]}


def _orders():
    import db
    c = db.get_db()
    try:
        d = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        return (d.get("caseRecord") or {}).get("materialOrders") or []
    finally:
        c.close()


def _status(iid):
    import db
    c = db.get_db()
    try:
        r = c.execute("SELECT status FROM case_material_approvals WHERE quote_no=? AND item_id=?", (NO, iid)).fetchone()
        return r["status"] if r else None
    finally:
        c.close()


def test_coverage_group_import_edit_quantity_submit_then_blocked(live_server, make_user, new_context):
    import db
    adm, ap = make_user(username="cov_adm", role="superadmin")
    c = db.get_db()
    try:
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, quote_date)"
                  " VALUES (?,?,?,?,?,?,?,?,?,?,?)", (NO, "已送出", "客", "案", 21000, 21000, json.dumps(dict(Q, dealTag="已成案")),
                                                       "2026-10-04T00:00:00", "2026-10-04T00:00:00", "已成案", "2026-10-04"))
        c.execute("INSERT INTO suppliers (id, name, code, created_at, updated_at) VALUES (1, '甲供應商', 'S-001', '2026-10-04', '2026-10-04')")
        c.commit()
    finally:
        c.close()
    pg = new_context(viewport={"width": 1400, "height": 1200}).new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    sess = inject_login(pg, live_server, adm, ap)
    H = {"Authorization": "Bearer " + sess["token"]}
    approved_po(pg.context, live_server, H, NO, "交換器甲", 3, 1000, adm, item_id="a")
    approved_po(pg.context, live_server, H, NO, "交換器乙", 2, 1000, adm, item_id="a")
    approved_po(pg.context, live_server, H, NO, "線材", 10, 5, adm, unit="米", item_id="b")
    pg.goto(f"{live_server}/pages/case-management.html?q={NO}")
    pg.wait_for_selector('.cm-tab:has-text("財務")', timeout=20000)
    pg.click('.cm-tab:has-text("財務")')
    pg.wait_for_selector(PANEL, timeout=20000)
    pg.wait_for_function("() => document.querySelector('[data-testid=ml-tab-approved]') && !document.querySelector('#fin-material-orders').innerText.includes('載入中')", timeout=20000)

    pg.click('[data-testid="ml-open-po"]')
    pg.locator('[data-testid^="ml-p-"]').first.wait_for(state="visible", timeout=15000)
    groups = pg.locator('[data-testid^="ml-p-"]')
    assert groups.count() == 2                                                                      # 品項 a 一組、品項 b 一組（不是三行）
    ga = pg.locator('[data-testid^="ml-p-"]', has_text="交換器")
    txt = ga.inner_text()
    assert "5 台" in txt and "小計 5000" in txt and "（2 行）" in txt, txt
    ga.locator("input").check()
    pg.click('[data-testid="ml-import"]')
    card = pg.locator('[data-testid^="mo-card-"]').last
    card.locator('input[placeholder="數量"]').wait_for(state="visible", timeout=8000)
    assert card.locator('input[placeholder="數量"]').input_value() == "5"
    assert card.locator('input[placeholder="單價"]').is_disabled()                                   # 金額唯讀（涵蓋行金額合計）
    card.locator('input[placeholder="數量"]').fill("4")                                              # 數量可往下調
    pg.wait_for_function("() => document.querySelector('#fin-material-orders').innerText.includes('5,000')", timeout=5000)   # 小計仍 5000
    pg.wait_for_function("() => document.querySelectorAll('#fin-material-orders [data-testid=mo-supplier] option').length >= 2", timeout=15000)
    card.locator('[data-testid="mo-supplier"]').select_option(label="S-001 甲供應商")
    card.locator('[data-testid="mo-submit"]').click()                                                # 一鍵＝先存再送審（涵蓋檢查在送審）
    for _ in range(100):
        o = [x for x in _orders() if x.get("quoteItemId") == "a"]
        if o and _status(o[0]["itemId"]) in ("待審核", "簽核中", "已核准"):
            break
        pg.wait_for_timeout(200)
    o = [x for x in _orders() if x.get("quoteItemId") == "a"]
    assert o and _status(o[0]["itemId"]) in ("待審核", "簽核中", "已核准"), (o, pg.locator(PANEL).inner_text()[:400])
    assert o[0]["quantity"] == 4 and abs(o[0]["totalPrice"] - 5000) < 0.01

    pg.wait_for_function("() => !document.querySelector('[data-testid=ml-panel]') || getComputedStyle(document.querySelector('[data-testid=ml-panel]')).display === 'none'", timeout=5000)   # 帶入後面板已關
    pg.click('[data-testid="ml-open-po"]')                                                          # 再開一次
    blk = pg.locator('[data-testid="ml-block-item:a"]')
    blk.wait_for(state="visible", timeout=15000)
    assert "變更申請" in blk.inner_text()
    assert pg.locator('[data-testid^="ml-p-"]', has_text="交換器").locator("input").is_disabled()
    assert not errors, errors
