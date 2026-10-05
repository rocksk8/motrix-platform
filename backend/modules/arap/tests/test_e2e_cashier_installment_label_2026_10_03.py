# -*- coding: utf-8 -*-
"""瀏覽器端對端（含截圖）：出納「待付款」表與標記已匯款視窗顯示分期申請的款別／期別（31-B 收尾，第 34 班）。
出納看到同一承攬商同一案件的兩筆待匯款，要分得出是訂金第 1 期還是進度款第 1 期，否則有付錯的風險。
流程：管理員建兩期分期申請（訂金／進度款）＋一張舊式整筆（另一派發）並核准 → 出納開待付款：分期兩列各有「款別 第 N 期」標籤、舊式整筆沒有 →
按其中一列「標記已匯款」：視窗標題含款別／期別 → 取消。終點以畫面為準（標籤文字＋視窗標題）；截圖在暫存夾。"""
import json
import os
import tempfile

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402


def _db(sql, args=()):
    import db
    c = db.get_db()
    try:
        cur = c.execute(sql, args)
        rows = [dict(r) for r in cur.fetchall()] if cur.description else []
        c.commit()
        return rows
    finally:
        c.close()


def _shot(page, name):
    try:
        d = os.path.join(os.environ.get("MOTRIX_SHOTS_DIR") or os.path.join(tempfile.gettempdir(), "w2-shots"), "wip-t34-cashier-kinds-a3")
        os.makedirs(d, exist_ok=True)
        page.screenshot(path=os.path.join(d, name + ".png"), full_page=True)
    except Exception:  # noqa: BLE001
        pass


def _dispatch(vid, total=1000):
    _db("INSERT INTO contractor_dispatches (quote_no, vendor_id, status, total_amount, tax_rate, items_json, personnel_json, approval_status, created_at, updated_at)"
        " VALUES ('MQ-CIK-1',?,'accepted',?,0.05,'[]','[]','', '2026-10-01','2026-10-01')", (vid, total))
    return _db("SELECT MAX(id) AS i FROM contractor_dispatches")[0]["i"]


@pytest.mark.e2e
def test_cashier_payable_table_shows_kind_and_period(live_server, make_user, e2e_browser):
    adm = make_user(username="cik_adm", role="finance")      # 第42班：建立匯款申請＝財務角色（admin 直通拿掉）
    cash = make_user(username="cik_cash", role="engineer", modules=["cashier"])
    _db("INSERT INTO vendor_contractors (name, tax_id, created_at, updated_at) VALUES ('CIK廠商','12345678','2026-10-01','2026-10-01')")
    vid = _db("SELECT id FROM vendor_contractors WHERE name='CIK廠商'")[0]["id"]
    d1, d2 = _dispatch(vid), _dispatch(vid)
    req = e2e_browser.new_context().request
    tok = req.post(f"{live_server}/api/auth/login", data={"username": adm[0], "password": adm[1]}).json()["token"]
    h = {"Authorization": "Bearer " + tok}
    nos = {}
    for key, body in (("deposit", {"dispatch_id": d1, "kind": "deposit", "amount": 300}), ("progress", {"dispatch_id": d1, "kind": "progress", "amount": 700}),
                      ("whole", {"dispatch_id": d2})):
        r = req.post(f"{live_server}/api/contractor-vouchers", headers=h, data=body)
        assert r.status in (200, 201), r.text()
        nos[key] = r.json()["voucher_no"]
    _db("UPDATE contractor_payment_vouchers SET status='已核准' WHERE voucher_no IN (?,?,?)", (nos["deposit"], nos["progress"], nos["whole"]))

    page = e2e_browser.new_context(viewport={"width": 1500, "height": 1000}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, *cash)
    page.goto(live_server + "/pages/cashier.html")
    labels = page.locator('[data-testid="cashier-kind-label"]:visible')
    labels.first.wait_for(timeout=20000)
    texts = sorted(labels.all_inner_texts())
    assert texts == ["訂金款 第 1 期", "進度款 第 1 期"], texts                              # 兩個分期各一個；舊式整筆沒有標籤
    rows = page.locator("tr", has=page.locator('[data-testid="cashier-kind-label"]:visible'))
    assert rows.count() == 2
    whole_row = page.locator("tr", has_text=nos["whole"])
    assert whole_row.count() == 1 and whole_row.locator('[data-testid="cashier-kind-label"]').count() == 1 and not whole_row.locator('[data-testid="cashier-kind-label"]').first.is_visible()
    _shot(page, "01-payable")
    # 標記已匯款視窗標題帶款別／期別
    row = page.locator("tr", has_text=nos["progress"])
    row.get_by_role("button", name="標記已匯款").click()
    title = page.locator(".modal-title", has_text="標記已匯款").first
    title.wait_for(state="visible", timeout=8000)
    assert nos["progress"] in title.inner_text() and "進度款 第 1 期" in title.inner_text(), title.inner_text()
    _shot(page, "02-pay-modal")
    assert not errors, errors
