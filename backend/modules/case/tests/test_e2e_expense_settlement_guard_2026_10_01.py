# -*- coding: utf-8 -*-
"""瀏覽器端對端（含截圖）：精算頁對「金額被遮蔽的費用單據」的守門（A2 S2）。
財務檢視偏好者（看得到案件財務、但不是該單申請人／簽核人／出納／財務）開精算頁 ⇒ 額外支出總額不完整 ⇒ 顯示警告、
「儲存草稿」「完結精算」不可按（不會把殘缺的總額寫進精算）；看得到金額的人（管理員）沒有警告、可按。DB 終點：精算狀態沒被動。"""
import json
import os
import tempfile

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

QN = "MQ-STLG-1"


def _shot(page, name):
    try:
        d = os.path.join(os.environ.get("MOTRIX_SHOTS_DIR") or os.path.join(tempfile.gettempdir(), "w2-shots"), "wip-w2-expense-a2")
        os.makedirs(d, exist_ok=True)
        page.screenshot(path=os.path.join(d, name + ".png"), full_page=True)
    except Exception:  # noqa: BLE001
        pass


def _setup(live_server, make_user, e2e_browser):
    import db
    fv = make_user(username="stlg_fv", role="engineer", modules=["financial_view"])
    sa = make_user(username="stlg_sa", role="superadmin")
    c = db.get_db()
    try:
        uid = c.execute("SELECT id FROM users WHERE username='stlg_fv'").fetchone()["id"]
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, sales_person, assigned_user_ids)"
                  " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (QN, "已送出", "精算守門客", "測專", 100000, 95238, json.dumps({"dealTag": "已成案", "caseRecord": {}}, ensure_ascii=False),
                   "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "", json.dumps([uid])))
        c.commit()
    finally:
        c.close()
    req = e2e_browser.new_context().request
    tok = req.post(f"{live_server}/api/auth/login", data={"username": "stlg_sa", "password": sa[1]}).json()["token"]
    r = req.post(f"{live_server}/api/quotations/{QN}/extra-expenses", headers={"Authorization": "Bearer " + tok},
                 data={"kind": "travel", "lines": [{"category": "其他", "summary": "高鐵", "amount": 4321}], "data": {"applicant": "stlg_sa"}})
    assert r.ok, r.text()
    return fv, sa


def _open(browser, live_server, cred):
    page = browser.new_context().new_page()
    inject_login(page, live_server, *cred)
    page.goto(f"{live_server}/pages/settlement.html?no={QN}")
    page.locator('[data-testid="stl-save-draft"]').wait_for(state="attached", timeout=20000)
    page.wait_for_timeout(1500)                                   # 額外支出總額是載入完才進來
    return page


@pytest.mark.e2e
def test_settlement_refuses_an_incomplete_extra_expense_total(live_server, make_user, e2e_browser):
    fv, sa = _setup(live_server, make_user, e2e_browser)
    page = _open(e2e_browser, live_server, fv)
    # 第42班：能開成本精算的只剩財務角色／superadmin（stlg_fv 的 financial_view 勾選被 conftest 換成 finance 角色），
    # 兩者都看得到全部額外支出金額 ⇒ 不再有「看得到精算、看不到部分額外支出」的人，也就沒有遮蔽警告；財務角色與 superadmin 一樣可按。
    warn = page.locator('[data-testid="stl-masked-warning"]')
    page.locator('[data-testid="stl-save-draft"]').wait_for(state="attached", timeout=10000)
    assert not warn.is_visible()
    assert page.locator('[data-testid="stl-save-draft"]').is_enabled() and page.locator('[data-testid="stl-finalize"]').is_enabled()
    _shot(page, "20-settlement-finance-role")
    # 管理員：看得到金額 ⇒ 沒有警告、可按
    p2 = _open(e2e_browser, live_server, sa)
    assert not p2.locator('[data-testid="stl-masked-warning"]').is_visible()
    assert p2.locator('[data-testid="stl-save-draft"]').is_enabled() and p2.locator('[data-testid="stl-finalize"]').is_enabled()
    _shot(p2, "21-settlement-complete")
    import db
    c = db.get_db()
    try:
        data = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (QN,)).fetchone()["data_json"])
    finally:
        c.close()
    assert (data.get("settlement") or {}).get("status") != "finalized"                       # 沒有被完結
