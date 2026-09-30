# -*- coding: utf-8 -*-
"""第 27 班規則 R2：未核可單據的 PDF 預覽 —— 紅色「未核可・僅供預覽」＋有權決定的人可在預覽裡「退回修改」（原因必填、寫稽核）。

每種單據各一題（有簽核人、非最高管理者，驗「簽核人也看得到預覽」）：
  未核准：開預覽 ⇒ 下載到的 PDF 文字含警示字樣、預覽視窗有「退回修改」；不填原因 ⇒ 擋下；填原因送出 ⇒ 單據回草稿（DB）＋稽核；
  已核准：PDF 沒有警示字樣、預覽視窗沒有「退回修改」。
截圖：D:\\開發測試檔\\shots\\wip-w1-pdf-unapproved\\（視窗畫面＋該單據 PDF 用的 HTML 畫面，後者看得到紅色橫幅）。
"""
import json
import os
from datetime import datetime

import pytest

pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.e2e

SHOTS = r"D:\開發測試檔\shots\wip-w1-pdf-unapproved"
RED_TEXT = "未核可・僅供預覽"
ROOT = "Alpine.$data(document.querySelector('[x-data]'))"


def _shot(page, name):
    """截圖先存 tmp（conftest BK19 不准測試寫到 repo／tmp 之外），跑完由 tools／手動複製到 SHOTS（見檔頭）。"""
    try:
        import tempfile
        d = os.path.join(tempfile.gettempdir(), "w1-shots-pdf-unapproved")
        os.makedirs(d, exist_ok=True)
        page.screenshot(path=os.path.join(d, name + ".png"))
    except Exception as e:                                                # noqa: BLE001 — 截圖失敗不讓題目失敗
        print("SHOT FAIL", name, ascii(e)[:200])


@pytest.fixture()
def company(client):
    from helpers.settings import _set_setting
    _set_setting("company_profile", {"companyName": "測試股份有限公司", "companyNameEn": "Test Co.", "taxId": "12345678",
                                     "phone": "02-1234-5678", "email": "a@b.c", "locations": [],
                                     "bank_name": "測試銀行", "bank_account_name": "測試股份有限公司", "bank_account_number": "0001234567"})


def _db(sql, args=(), write=False):
    import db
    c = db.get_db()
    try:
        rows = [dict(r) for r in c.execute(sql, args).fetchall()] if not write else c.execute(sql, args) and []
        if write:
            c.commit()
        return rows
    finally:
        c.close()


def _approval(requester, approver):
    return {"requestedBy": requester, "requestedByDisplay": requester, "requestedAt": datetime.now().isoformat(),
            "tiers": [{"order": 0, "approvers": [{"username": approver, "displayName": approver, "status": "pending"}]}],
            "currentTier": 0}


def _seed_quote(no):
    now = datetime.now().isoformat()
    data = {"quoteNo": no, "dealTag": "已成案", "customerName": "測試客戶", "projectName": "測試案", "caseRecord": {},
            "items": [{"id": 1, "type": "item", "description": "設備", "qty": 1, "unitPrice": 1000, "amount": 1000}]}
    _db("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, "
        "deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (no, "已送出", "測試客戶", "測試案", 1000, 1000, json.dumps(data, ensure_ascii=False), now, now, "已成案", "2026-09-01"), write=True)


def _pdf_text(body: bytes) -> str:
    import io
    from pypdf import PdfReader
    return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(body)).pages)


def _last_audit(action):
    r = _db("SELECT target_label, detail AS detail_json FROM audit_log WHERE action=? ORDER BY id DESC LIMIT 1", (action,))
    return r[0] if r else None


def _users(make_user, tag, extra_modules=()):
    boss = make_user(username="pu_req_" + tag, role="admin", modules=["case_manage", "quotation", *extra_modules])
    appr = make_user(username="pu_appr_" + tag, role="admin", modules=["case_manage", "quotation", *extra_modules])
    return boss, appr


def _pdf_ok(client, user, url, expect_red):
    """以簽核人身分打 pdf-download（驗：簽核人（非最高管理者）拿得到、PDF 文字含／不含紅色警示字樣）。"""
    tok = client.post("/api/auth/login", json={"username": user[0], "password": user[1]}).json()["token"]
    r = client.get(url, headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 200, (url, r.status_code, r.text[:200])
    text = _pdf_text(r.content)
    assert (RED_TEXT in text) is expect_red, "PDF 文字%s含警示字樣：%s" % ("應" if expect_red else "不應", text[:120])


def _click_preview(page, click):
    with page.expect_response(lambda r: "/pdf-download" in r.url and r.request.method == "GET", timeout=60000) as ri:
        click()
    assert ri.value.status == 200, ri.value.status


def _do_return(page, reason):
    btn = page.locator('[data-testid="preview-return"]:visible')
    btn.wait_for(state="visible", timeout=10000)
    btn.click()
    page.locator('[data-testid="return-dialog"]').wait_for(state="visible", timeout=5000)
    page.locator('[data-testid="return-confirm"]').click()                     # 沒填原因
    assert "要填原因" in page.locator('[data-testid="return-error"]').inner_text()
    page.fill('[data-testid="return-reason"]', reason)
    page.locator('[data-testid="return-confirm"]').click()
    page.locator('[data-testid="return-dialog"]').wait_for(state="detached", timeout=15000)


def _html_shot(page, html, name):
    """該單據 PDF 用的 HTML 畫在頁面上截圖（真 PDF 在無頭瀏覽器的 iframe 裡畫不出來）。"""
    page.set_content(html)
    _shot(page, name)


# ─────────────────────────────── 出貨單（簽核人＝非最高管理者；原本 pdf-download 要 admin）───────────────────────────────

@pytest.mark.parametrize("approved", [False, True])
def test_shipping_note(client, live_server, make_user, new_page, login_as, company, approved):
    import pdf_gen
    tag = "ship%d" % approved
    req, appr = _users(make_user, tag)
    qno = "MQ-PU-SH%d" % approved
    _seed_quote(qno)
    nno = "SN-PU-%d" % approved
    _db("INSERT INTO shipping_notes (note_no, quote_no, status, customer_name, project_name, data_json, created_by, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (nno, qno, "已核准" if approved else "待審核", "測試客戶", "測試案",
         json.dumps({"approval": _approval(req[0], appr[0])}, ensure_ascii=False), req[0], datetime.now().isoformat(), datetime.now().isoformat()), write=True)
    page = new_page()
    login_as(page, appr)
    page.goto(f"{live_server}/pages/case-management.html?q={qno}")
    page.wait_for_selector('.cm-tab:has-text("出貨單")', timeout=20000)
    page.click('.cm-tab:has-text("出貨單")')
    row = page.locator("button:has-text('預覽')").first
    row.wait_for(state="visible", timeout=20000)
    _pdf_ok(client, appr, "/api/shipping-notes/%s/pdf-download" % nno, not approved)
    _click_preview(page, lambda: row.click())
    page.locator('[x-show="shippingPreviewModal"]').wait_for(state="visible", timeout=10000)
    _shot(page, "shipping-%s" % ("approved" if approved else "unapproved"))
    ret = page.locator('[data-testid="preview-return"]:visible')
    if approved:
        assert ret.count() == 0
        return
    _html_shot(new_page(), pdf_gen._build_shipping_html({"noteNo": nno, "status": "待審核", "items": []}), "shipping-unapproved-html")
    _do_return(page, "出貨數量有誤")
    page.wait_for_function("() => true")
    assert _db("SELECT status FROM shipping_notes WHERE note_no=?", (nno,))[0]["status"] == "草稿"
    a = _last_audit("shipping.reject")
    assert a and nno in a["target_label"] and "出貨數量有誤" in (a["detail_json"] or "")


# ─────────────────────────────── 完工單（案件頁預覽視窗；不再 window.open、不計匯出次數）───────────────────────────────

@pytest.mark.parametrize("approved", [False, True])
def test_completion_note(client, live_server, make_user, new_page, login_as, company, approved):
    from modules.case import completion_pdf as cp
    tag = "comp%d" % approved
    req, appr = _users(make_user, tag)
    qno = "MQ-PU-CP%d" % approved
    _seed_quote(qno)
    nno = "CN-PU-%d" % approved
    now = datetime.now().isoformat()
    _db("INSERT INTO completion_notes (note_no, quote_no, status, customer_name, project_name, data_json, created_by, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (nno, qno, "已核准" if approved else "待審核", "測試客戶", "測試案",
         json.dumps({"approval": _approval(req[0], appr[0])}, ensure_ascii=False), req[0], now, now), write=True)
    page = new_page()
    login_as(page, appr)
    page.goto(f"{live_server}/pages/case-management.html?q={qno}")
    page.wait_for_selector('.cm-tab:has-text("完工")', timeout=20000)
    page.click('.cm-tab:has-text("完工")')
    row = page.locator("button:has-text('預覽 PDF')").first
    row.wait_for(state="visible", timeout=20000)
    _pdf_ok(client, appr, "/api/completion-notes/%s/pdf-download" % nno, not approved)
    _click_preview(page, lambda: row.click())
    page.locator('[x-show="completionPreviewModal"]').wait_for(state="visible", timeout=10000)
    _shot(page, "completion-%s" % ("approved" if approved else "unapproved"))
    # 預覽不是匯出：不計次
    assert _db("SELECT export_count FROM completion_notes WHERE note_no=?", (nno,))[0]["export_count"] == 0
    if approved:
        assert page.locator('[data-testid="preview-return"]:visible').count() == 0
        return
    _html_shot(new_page(), cp._build_completion_html({"noteNo": nno, "status": "待審核"}), "completion-unapproved-html")
    _do_return(page, "完工日期不對")
    assert _db("SELECT status FROM completion_notes WHERE note_no=?", (nno,))[0]["status"] == "草稿"
    a = _last_audit("completion.reject")
    assert a and "完工日期不對" in (a["detail_json"] or "")


# ─────────────────────────────── 請款單（獨立頁）───────────────────────────────

@pytest.mark.parametrize("approved", [False, True])
def test_payment_request(client, live_server, make_user, new_page, login_as, company, approved):
    import pdf_gen
    tag = "pr%d" % approved
    req, appr = _users(make_user, tag)
    qno = "MQ-PU-PR%d" % approved
    _seed_quote(qno)
    rno = "PR-PU-%d" % approved
    now = datetime.now().isoformat()
    _db("INSERT INTO payment_requests (request_no, quote_no, status, amount, data_json, created_by, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (rno, qno, "已核准" if approved else "待審核", 1000, json.dumps({"approval": _approval(req[0], appr[0])}, ensure_ascii=False), req[0], now, now), write=True)
    page = new_page()
    login_as(page, appr)
    page.goto(f"{live_server}/pages/payment-request-form.html?id={rno}")
    btn = page.locator("button:has-text('預覽')").first
    btn.wait_for(state="visible", timeout=20000)
    _pdf_ok(client, appr, "/api/payment-requests/%s/pdf-download" % rno, not approved)
    _click_preview(page, lambda: btn.click())
    _shot(page, "payment-request-%s" % ("approved" if approved else "unapproved"))
    if approved:
        assert page.locator('[data-testid="preview-return"]:visible').count() == 0
        return
    _html_shot(new_page(), pdf_gen._build_payment_request_html({"requestNo": rno, "status": "待審核"}), "payment-request-unapproved-html")
    _do_return(page, "請款金額有誤")
    assert _db("SELECT status FROM payment_requests WHERE request_no=?", (rno,))[0]["status"] == "草稿"
    a = _last_audit("payment_request.reject")
    assert a and "請款金額有誤" in (a["detail_json"] or "")


# ─────────────────────────────── 開票申請（案件頁財務頁籤）───────────────────────────────

@pytest.mark.parametrize("approved", [False, True])
def test_invoice_voucher(client, live_server, make_user, new_page, login_as, company, approved):
    tag = "iv%d" % approved
    req, appr = _users(make_user, tag, extra_modules=("finance",))
    qno = "MQ-PU-IV%d" % approved
    _seed_quote(qno)
    vno = "IV-PU-%d" % approved
    now = datetime.now().isoformat()
    _db("INSERT INTO invoice_vouchers (voucher_no, quote_no, scope, amount, status, snapshot_json, data_json, created_by, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (vno, qno, "amount", 1000, "已核准" if approved else "待審核", "{}", json.dumps({"approval": _approval(req[0], appr[0])}, ensure_ascii=False),
         req[0], now, now), write=True)
    page = new_page()
    login_as(page, appr)
    page.goto(f"{live_server}/pages/case-management.html?q={qno}")
    page.wait_for_selector('.cm-tab:has-text("財務")', timeout=20000)
    page.click('.cm-tab:has-text("財務")')
    row = page.locator("button:has-text('預覽')").first
    row.wait_for(state="visible", timeout=20000)
    _pdf_ok(client, appr, "/api/invoice-vouchers/%s/pdf-download" % vno, not approved)
    _click_preview(page, lambda: row.click())
    _shot(page, "invoice-voucher-%s" % ("approved" if approved else "unapproved"))
    if approved:
        assert page.locator('[data-testid="preview-return"]:visible').count() == 0
        return
    _do_return(page, "稅額有誤")
    assert _db("SELECT status FROM invoice_vouchers WHERE voucher_no=?", (vno,))[0]["status"] == "草稿"
    a = _last_audit("invoice_voucher.reject")
    assert a and "稅額有誤" in (a["detail_json"] or "")


# ─────────────────────────────── 後端：退回原因必填（順序：先狀態／權限，最後才是原因）───────────────────────────────

@pytest.mark.parametrize("path", ["/api/shipping-notes/{no}/reject", "/api/completion-notes/{no}/reject",
                                  "/api/payment-requests/{no}/reject", "/api/invoice-vouchers/{no}/reject",
                                  "/api/contractor-vouchers/{no}/reject"])
def test_reject_checks_state_before_reason(client, make_user, path):
    """不存在／不在待審核的單據：先 404（狀態），不是 400；原因那一關在狀態與權限之後（第 27 班 build：409 被 400 蓋掉）。"""
    u = make_user(username="pu_rr_" + path.split("/")[2], role="superadmin")
    tok = client.post("/api/auth/login", json={"username": u[0], "password": u[1]}).json()["token"]
    h = {"Authorization": "Bearer " + tok}
    r = client.post(path.format(no="X-NOPE"), headers=h, json={})
    assert r.status_code == 404, (path, r.status_code, r.text)


def test_reject_without_reason_is_400_on_a_real_pending_doc(client, make_user):
    req = make_user(username="pu_rr_req", role="superadmin")
    qno = "MQ-PU-RR"
    _seed_quote(qno)
    now = datetime.now().isoformat()
    _db("INSERT INTO shipping_notes (note_no, quote_no, status, customer_name, project_name, data_json, created_by, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)", ("SN-PU-RR", qno, "待審核", "測試客戶", "測試案",
                                      json.dumps({"approval": _approval(req[0], req[0])}, ensure_ascii=False), req[0], now, now), write=True)
    tok = client.post("/api/auth/login", json={"username": req[0], "password": req[1]}).json()["token"]
    h = {"Authorization": "Bearer " + tok}
    for body in ({}, {"note": ""}, {"note": "   "}):
        r = client.post("/api/shipping-notes/SN-PU-RR/reject", headers=h, json=body)
        assert r.status_code == 400 and "要填原因" in r.json()["detail"], (body, r.status_code, r.text)
    assert _db("SELECT status FROM shipping_notes WHERE note_no=?", ("SN-PU-RR",))[0]["status"] == "待審核"      # 沒有被退回
    assert client.post("/api/shipping-notes/SN-PU-RR/reject", headers=h, json={"note": "有原因"}).status_code == 200
