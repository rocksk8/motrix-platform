# -*- coding: utf-8 -*-
"""N1（2026-09-30）案件管理承攬商派工（畫面＋DB）：
① 派發視窗：派工內容是大的多行輸入框、視窗在畫面中央、單位可以自己打（組／式／米之外，例如「坪」「才」）並存進去；
② 承攬商報價單附件：申請刪除要審核——核可前檔案保留、畫面標「刪除待審」；最高管理者核可才真的刪；
③ 報價單成本欄：可逐項帶入該案承攬商報價，與承攬商報價不一致時標差額。
"""
import io
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._requires import requires_module  # noqa: E402
from tests._ui_dialogs import answer_confirm, answer_prompt  # noqa: E402

pytestmark = [requires_module("case", "案件管理（M01）"), requires_module("subcontract", "承攬商派工（M04）")]

NO = "MQ-N1E-001"
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de0000000c4944415478da6360000002000155a5e6ce0000000049454e44ae426082")


def _x(sql, args=()):
    import db
    conn = db.get_db()
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def _q(sql, args=()):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


@pytest.mark.e2e
def test_dispatch_modal_units_and_quote_file_delete_review(live_server, make_user, new_context, client):
    boss = make_user(username="n1e_boss", role="superadmin")
    adm = make_user(username="n1e_admin", role="admin")
    _x("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
       " deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
       (NO, "已送出", "派工客", "派工專案", 100000, 95238,
        json.dumps({"dealTag": "已成案", "caseRecord": {"payment": {"items": []}, "materials": [], "stages": [{"label": "訂單確認"}]}},
                   ensure_ascii=False), "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "2026-08-01"))
    tok = client.post("/api/auth/login", json={"username": boss[0], "password": boss[1]}).json()["token"]
    h = {"Authorization": "Bearer " + tok}
    v = client.post("/api/vendor-contractors", headers=h, json={"name": "N1廠商", "data": {}})
    assert v.status_code == 201, v.text
    d = client.post("/api/contractor-dispatches", headers=h, json={
        "quote_no": NO, "vendor_id": v.json()["id"], "status": "draft", "scope": "既有派工",
        "items_json": [{"id": "i1", "description": "配線", "qty": 10, "unit": "米", "unitPrice": 100, "amount": 1000}]})
    assert d.status_code == 201, d.text
    did = d.json()["id"]
    up = client.post("/api/contractor-dispatches/%d/files" % did, headers=h, files={"files": ("quote.png", io.BytesIO(PNG), "image/png")})
    assert up.status_code == 201, up.text
    fid = up.json()["files"][0]["id"]

    errors = []
    page = new_context().new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, adm[0], adm[1])
    page.goto(live_server + "/pages/case-management.html?q=%s&tab=dispatch" % NO)
    page.wait_for_selector('[data-testid="dispatch-file-delete"]', timeout=20000)

    # ① 新增派發：大的多行「派工內容」、視窗置中、單位可自己打
    page.click("text=新增派發")
    box = page.locator('[data-testid="dispatch-modal-box"]')
    box.wait_for(state="visible")
    box.locator("select").first.select_option(label="N1廠商")
    scope = page.locator('[data-testid="dispatch-form-scope"]')
    assert scope.evaluate("e => e.tagName") == "TEXTAREA"
    sb = scope.bounding_box()
    assert sb["height"] >= 100 and sb["width"] >= 500, sb
    bb = box.bounding_box()
    vp = page.viewport_size
    assert abs((bb["x"] + bb["width"] / 2) - vp["width"] / 2) < 30, (bb, vp)          # 水平置中
    scope.fill("第一行工項\n第二行注意事項")
    if not page.locator('[data-testid="dispatch-item-desc"]').count():
        box.locator("button:has-text(\"新增品項\")").click()
    assert page.locator('[data-testid="dispatch-item-desc"]').first.evaluate("e => e.tagName") == "TEXTAREA"
    unit = page.locator('[data-testid="dispatch-item-unit"]').first
    assert unit.evaluate("e => e.tagName") == "INPUT" and unit.get_attribute("list") == "dispatch-unit-options"
    unit.fill("坪")                                                                    # 清單以外的單位
    page.locator('[data-testid="dispatch-item-desc"]').first.fill("地坪整平")
    page.locator('input[x-model\\.number="it.qty"]').first.fill("3")
    page.locator('input[x-model="it.unitPrice"]').first.fill("500")
    page.click("text=儲存派發紀錄")
    try:
        box.wait_for(state="hidden", timeout=15000)
    except Exception:
        raise AssertionError("派發視窗沒有關閉，訊息：%r" % page.evaluate("() => (document.querySelector('[x-show=\"dispatchMsg\"]')||{}).innerText"))
    rows = _q("SELECT scope, items_json FROM contractor_dispatches WHERE quote_no=? AND scope LIKE '第一行%'", (NO,))
    assert rows and "第二行注意事項" in rows[0]["scope"]
    assert json.loads(rows[0]["items_json"])[0]["unit"] == "坪"

    # ② 報價單附件申請刪除：核可前保留、標「刪除待審」
    page.click('[data-testid="dispatch-file-delete"]')
    answer_prompt(page, "傳錯版本", expect="刪除")
    page.wait_for_selector('[data-testid="dispatch-file-delete-pending"]', timeout=15000)
    files = json.loads(_q("SELECT files_json FROM contractor_dispatches WHERE id=?", (did,))[0]["files_json"])
    req = _q("SELECT reason, status, requested_by FROM dispatch_file_delete_requests WHERE dispatch_id=?", (did,))
    assert len(files) == 1 and len(req) == 1 and req[0]["reason"] == "傳錯版本" and req[0]["status"] == "待審核"
    # 申請人（一般管理員）沒有核可鈕；最高管理者核可（沒設簽核層）⇒ 才真的刪
    assert page.locator('[data-testid="dispatch-file-delete-approve"]').count() == 0
    # 第一位離開（關掉分頁並讓「同時編輯」紀錄過期）——否則第二位開同一案會被 #motrix-presence-modal 蓋住，不可 force click
    page.context.close()
    _x("UPDATE edit_presence SET last_seen_at='2000-01-01T00:00:00'")
    page = new_context().new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, boss[0], boss[1])
    page.goto(live_server + "/pages/case-management.html?q=%s&tab=dispatch" % NO)
    page.wait_for_selector('[data-testid="dispatch-file-delete-pending"]', timeout=20000)
    assert page.locator("#motrix-presence-modal").count() == 0
    page.click('[data-testid="dispatch-file-delete-approve"]')
    answer_confirm(page, ok=True, expect="刪除")
    page.wait_for_selector('[data-testid="dispatch-file-delete-pending"]', state="detached", timeout=15000)
    assert json.loads(_q("SELECT files_json FROM contractor_dispatches WHERE id=?", (did,))[0]["files_json"]) == []
    assert not errors, errors


@pytest.mark.e2e
def test_quotation_cost_pick_vendor_quote_and_diff(live_server, make_user, new_context, client):
    """報價單成本欄「帶入承攬商報價」：值正確（未稅單價）；改成本後出現總差額（單價差×數量）；改回一致即消失；
    反向控制：沒有派工的案件，成本欄沒有帶入選單。"""
    boss = make_user(username="n1v_boss", role="superadmin")
    for no, extra in (("MQ-N1V-001", True), ("MQ-N1V-002", False)):
        items = [{"id": 1, "description": "配線", "qty": 10, "unit": "米", "unitPrice": 200, "amount": 2000,
                  "cost": 0, "margin": 0.3}]
        _x("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at,"
           " updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
           (no, "草稿", "消底客", "消底專案", 2100, 2000,
            json.dumps({"quoteNo": no, "customerName": "消底客", "projectName": "消底專案", "status": "草稿", "items": items,
                        "tot": {"total": 2100, "pretax": 2000, "directMarginPct": 0, "netMarginPct": 0}}, ensure_ascii=False),
            "2026-09-01T00:00:00", "2026-09-01T00:00:00", "", "2026-09-01"))
    tok = client.post("/api/auth/login", json={"username": boss[0], "password": boss[1]}).json()["token"]
    h = {"Authorization": "Bearer " + tok}
    v = client.post("/api/vendor-contractors", headers=h, json={"name": "消底廠商", "data": {}})
    assert v.status_code == 201, v.text
    d = client.post("/api/contractor-dispatches", headers=h, json={
        "quote_no": "MQ-N1V-001", "vendor_id": v.json()["id"], "status": "draft",
        "items_json": [{"id": "a1", "description": "配線工資", "qty": 10, "unit": "米", "unitPrice": 100, "amount": 1000}]})
    assert d.status_code == 201, d.text
    errors = []
    page = new_context().new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, boss[0], boss[1])
    page.goto(live_server + "/pages/quotation-form.html?id=MQ-N1V-001")
    pick = page.locator('[data-testid="vq-pick"]').first
    pick.wait_for(state="visible", timeout=20000)
    cost = page.locator('tr:has([data-testid="vq-pick"]) td.internal input').first
    pick.select_option(index=1)                                                   # 帶入
    assert cost.input_value() == "100"                                            # 承攬商未稅單價
    assert page.locator('[data-testid="vq-diff"]').first.is_hidden()              # 一致 ⇒ 沒有差額提示
    cost.fill("90")
    page.wait_for_selector('[data-testid="vq-diff"]', state="visible", timeout=5000)
    txt = page.locator('[data-testid="vq-diff"]').first.inner_text()
    assert "-100" in txt and "未稅" in txt and "10" in txt, txt                   # (90-100)×10
    cost.fill("100")
    page.wait_for_selector('[data-testid="vq-diff"]', state="hidden", timeout=5000)
    # 反向控制：沒有派工 ⇒ 沒有帶入選單
    page2 = new_context().new_page()
    inject_login(page2, live_server, boss[0], boss[1])
    page2.goto(live_server + "/pages/quotation-form.html?id=MQ-N1V-002")
    page2.wait_for_function("() => document.body.innerText.includes('消底客')", timeout=20000)
    page2.wait_for_timeout(1500)
    assert page2.locator('[data-testid="vq-pick"]').count() == 0
    assert not errors, errors


# 上傳檔頭：這支用真的檢查（conftest 預設把 _magic_matches 換成一律符合；上傳的 e2e 要走真的，2026-09-30）
import pytest as _pt_magic
pytestmark = (list(pytestmark) if isinstance(pytestmark, (list, tuple)) else [pytestmark]) + [_pt_magic.mark.upload_magic]
