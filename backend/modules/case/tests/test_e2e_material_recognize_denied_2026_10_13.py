# -*- coding: utf-8 -*-
"""T57 認列被拒要立刻看得到（MS1d）：非最高管理者按『帶入並連結』⇒ 數秒內（不重新整理）出現白話提示、卡片維持未連結、已申購沒勾；
資料庫沒有 poLink、有一筆 recognize_denied 稽核。對照：最高管理者同樣操作仍成立。終點以資料庫與頁面狀態為準。"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._requires import requires_module  # noqa: E402
from tests._e2e_login import inject_login  # noqa: E402

pytestmark = [pytest.mark.e2e, requires_module("case", "本檔的題讀寫 M01（案件）的資料與頁面")]

NO = "MQ-E2E-RD-1"
Q = {"items": [{"id": "a", "description": "NVR1004H-4P", "qty": 10, "unit": "台", "unitPrice": 2000, "amount": 20000, "cost": 1000}]}


def _cr():
    import db
    c = db.get_db()
    try:
        return json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"]).get("caseRecord", {})
    finally:
        c.close()


def test_denied_recognition_is_visible_at_once_without_reload(live_server, make_user, e2e_browser):
    import db
    from helpers import _set_setting
    sa, sp = make_user(username="rd_sa", role="superadmin")
    adm, ap = make_user(username="rd_adm", role="admin")
    c = db.get_db()
    try:
        data = dict(Q, dealTag="已成案", caseRecord={"materials": [{"id": "c1", "name": "NVR1004H-4P", "qty": 1, "unit": "台", "ordered": False, "arrived": False, "orderItemId": ""}]})
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, quote_date)"
                  " VALUES (?,?,?,?,?,?,?,?,?,?,?)", (NO, "已送出", "客", "案", 21000, 21000, json.dumps(data, ensure_ascii=False),
                                                       "2026-10-13T00:00:00", "2026-10-13T00:00:00", "已成案", "2026-10-13"))
        c.commit()
    finally:
        c.close()
    _set_setting("unified_approval_flow", {"includeSubmitterManagerTier": False, "tiers": []})

    ctx = e2e_browser.new_context(viewport={"width": 1400, "height": 1100})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    sess = inject_login(page, live_server, sa, sp)
    H = {"Authorization": "Bearer " + sess["token"]}
    from modules.case.tests.test_purchase_item_lines_2026_10_02 import _body, _ln
    r = ctx.request.post(f"{live_server}/api/quotations/{NO}/extra-expenses", headers=H, data=_body("purchase_order", [_ln("a", 3, unitCost=1000)], data={"vendor": "某廠商"}))
    assert r.status == 201, r.text()
    assert ctx.request.post(f"{live_server}/api/quotations/{NO}/extra-expenses/{r.json()['id']}/submit", headers=H).status == 200

    ctx2 = e2e_browser.new_context(viewport={"width": 1400, "height": 1100})        # 非最高管理者（管理員）的瀏覽器
    pg = ctx2.new_page()
    pg.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(pg, live_server, adm, ap)
    pg.goto(f"{live_server}/pages/case-management.html?q={NO}")
    pg.wait_for_selector('.cm-tab:has-text("執行管理")', timeout=20000)
    pg.click('.cm-tab:has-text("執行管理")')
    pg.locator('.cm-tab:has-text("材料申請")').dispatch_event('click')
    pg.wait_for_selector(".mat-card", timeout=20000)
    pg.wait_for_function("() => { const d = Alpine.$data(document.querySelector('[x-data]')); return Array.isArray(d.mlGroups) && d.mlGroups.length > 0 }", timeout=20000)
    card = pg.locator(".mat-card").first
    card.locator('[data-testid="mat-order-oneclick"]').dispatch_event('click')               # 編輯中提示框（presence）可能蓋住按鈕：直接送出 click 事件
    pg.wait_for_selector('[data-testid="ui-toast"]:has-text("沒有認列採購單的權限")', timeout=8000)          # 不重新整理、不等防抖
    assert "已通知管理員" in pg.locator('[data-testid="ui-toast"]').first.inner_text()
    pg.wait_for_function("() => !document.querySelector('[data-testid=mat-po-recognized]')", timeout=8000)
    assert not card.locator('[data-testid="mat-ordered"]').is_checked()
    m = _cr()["materials"][0]
    assert not m.get("poLink") and not m["ordered"]
    c = db.get_db()
    try:
        assert c.execute("SELECT COUNT(*) FROM audit_log WHERE action='material.recognize_denied' AND username='rd_adm'").fetchone()[0] == 1
    finally:
        c.close()

    ctx2.close()                                                                      # 對照前關掉管理員的瀏覽器（避免『有人同時在編輯』提示框）
    # 對照：最高管理者同樣操作成立
    page.goto(f"{live_server}/pages/case-management.html?q={NO}")
    page.wait_for_selector('.cm-tab:has-text("執行管理")', timeout=20000)
    page.click('.cm-tab:has-text("執行管理")')
    page.locator('.cm-tab:has-text("材料申請")').dispatch_event('click')
    page.wait_for_selector(".mat-card", timeout=20000)
    page.wait_for_function("() => { const d = Alpine.$data(document.querySelector('[x-data]')); return Array.isArray(d.mlGroups) && d.mlGroups.length > 0 }", timeout=20000)
    page.locator(".mat-card").first.locator('[data-testid="mat-order-oneclick"]').dispatch_event('click')
    page.wait_for_function("() => document.querySelector('[data-testid=mat-po-recognized]')", timeout=8000)
    assert not errors, errors
