# -*- coding: utf-8 -*-
"""T57 材料卡片『帶入並連結』＝認列已核准採購單（MATERIAL-LINK-BUG-T57）的瀏覽器端對端（一個檔、一題連續流程）。
已核准採購單（廠商不在供應商主檔）→ 案件頁『材料申請』分頁 → 按『帶入並連結』→ **不按任何其他儲存**、等自動存檔 → 重新整理後：
卡片仍顯示已認列的採購單、已申購已勾；填到貨日勾已到料 → 重新整理仍在；伺服器沒有任何材料申請／審核列。
終點以資料庫與頁面狀態為準。"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._requires import requires_module  # noqa: E402
from tests._e2e_login import inject_login  # noqa: E402

pytestmark = [pytest.mark.e2e, requires_module("case", "本檔的題讀寫 M01（案件）的資料與頁面")]

NO = "MQ-E2E-RC-1"
Q = {"items": [{"id": "a", "description": "NVR1004H-4P", "qty": 10, "unit": "台", "unitPrice": 2000, "amount": 20000, "cost": 1000}]}


def _cr():
    import db
    c = db.get_db()
    try:
        return json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"]).get("caseRecord", {})
    finally:
        c.close()


def _wait_db(page, pred, what, timeout=25):
    import time
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pred():
            return
        page.wait_for_timeout(400)
    raise AssertionError("資料庫沒有達到預期狀態：" + what)


def _open_materials(page, live_server):
    page.goto(f"{live_server}/pages/case-management.html?q={NO}")
    page.wait_for_selector('.cm-tab:has-text("執行管理")', timeout=20000)
    page.click('.cm-tab:has-text("執行管理")')
    page.click('.cm-tab:has-text("材料申請")')
    page.wait_for_selector(".mat-card", timeout=20000)
    page.wait_for_function("() => { const d = Alpine.$data(document.querySelector('[x-data]')); return Array.isArray(d.mlGroups) && d.mlGroups.length > 0 }", timeout=20000)


def test_recognize_persists_after_reload_and_ticks_are_enabled(live_server, make_user, e2e_browser):
    import db
    from helpers import _set_setting
    sa, sp = make_user(username="rc_sa", role="superadmin")
    c = db.get_db()
    try:
        data = dict(Q, dealTag="已成案", caseRecord={"materials": [{"id": "c1", "name": "NVR1004H-4P", "qty": 1, "unit": "台", "ordered": False, "arrived": False, "orderItemId": ""}]})
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, quote_date)"
                  " VALUES (?,?,?,?,?,?,?,?,?,?,?)", (NO, "已送出", "客", "案", 21000, 21000, json.dumps(data, ensure_ascii=False),
                                                       "2026-10-13T00:00:00", "2026-10-13T00:00:00", "已成案", "2026-10-13"))
        c.commit()
    finally:
        c.close()
    _set_setting("unified_approval_flow", {"includeSubmitterManagerTier": False, "tiers": []})            # 採購單：送審即核准

    ctx = e2e_browser.new_context(viewport={"width": 1400, "height": 1100})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    sess = inject_login(page, live_server, sa, sp)
    H = {"Authorization": "Bearer " + sess["token"]}
    from modules.case.tests.test_purchase_item_lines_2026_10_02 import _body, _ln
    r = ctx.request.post(f"{live_server}/api/quotations/{NO}/extra-expenses", headers=H,
                         data=_body("purchase_order", [_ln("a", 3, unitCost=1000), _ln("a", 2, unitCost=1000)], data={"vendor": "不在主檔的廠商"}))
    assert r.status == 201, r.text()
    assert ctx.request.post(f"{live_server}/api/quotations/{NO}/extra-expenses/{r.json()['id']}/submit", headers=H).status == 200

    _open_materials(page, live_server)
    card = page.locator(".mat-card").first
    assert card.locator('[data-testid="mat-po-recognized"]').is_hidden()
    card.locator('[data-testid="mat-order-oneclick"]').click()
    assert "不在主檔的廠商" in card.locator('[data-testid="mat-po-recognized"]').inner_text()
    _wait_db(page, lambda: bool((next(iter(_cr().get("materials", [])), {}) or {}).get("poLink")), "認列已存到伺服器（沒有按任何其他儲存）")
    m = _cr()["materials"][0]
    assert m["ordered"] is True and m["poLink"]["vendor"] == "不在主檔的廠商" and m["orderItemId"] == ""

    page.reload()
    _open_materials(page, live_server)
    card = page.locator(".mat-card").first
    assert "已認列採購單" in card.locator('[data-testid="mat-po-recognized"]').inner_text()
    assert card.locator('[data-testid="mat-order-oneclick"]').is_hidden()
    ordered, arrived = card.locator('[data-testid="mat-ordered"]'), card.locator('[data-testid="mat-arrived"]')
    assert ordered.is_checked() and arrived.is_enabled()                                                       # 已申購已勾、已到料可勾

    card.locator('[data-testid="mat-po-arrived-on"]').fill("2026-10-13")
    arrived.check()
    _wait_db(page, lambda: bool((_cr()["materials"][0].get("poLink") or {}).get("arrivedBy")), "已到料與到貨確認已存")
    pl = _cr()["materials"][0]["poLink"]
    assert pl["arrivedOn"] == "2026-10-13" and pl["arrivedBy"] == "rc_sa"
    c = db.get_db()
    try:
        assert c.execute("SELECT COUNT(*) FROM case_material_approvals WHERE quote_no=?", (NO,)).fetchone()[0] == 0
    finally:
        c.close()
    assert not errors, errors
