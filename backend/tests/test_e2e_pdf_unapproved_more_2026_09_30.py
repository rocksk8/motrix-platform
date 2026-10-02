# -*- coding: utf-8 -*-
"""第 27 班規則 R2（續）：承攬商匯款申請、會計傳票、簽核佇列預覽、自訂模組單據、報價單。
同主檔：未核可 ⇒ 紅色「未核可・僅供預覽」、有權決定的人在預覽裡「退回修改」（原因必填、寫稽核、單據回可編輯狀態）；已核准 ⇒ 沒有警示、沒有按鈕。
HTML 預覽的畫面（傳票、佇列傳票、自訂單據、報價單）直接截到紅色橫幅；PDF iframe 在無頭瀏覽器是空白的，另截該單據 PDF 用的 HTML。"""
import json
from datetime import datetime

import pytest

from tests.test_e2e_pdf_unapproved_2026_09_30 import (  # noqa: F401  共用的 fixture 與 helper
    RED_TEXT, ROOT, _approval, _db, _do_return, _eventually, _html_shot, _last_audit, _pdf_ok, _seed_quote, _shot, _users, company,
)

pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.e2e


def _hdr(client, user):
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": user[0], "password": user[1]}).json()["token"]}


# ─────────────────────────────── 承攬商匯款申請（案件頁；以頁面方法開預覽視窗，視窗內按鈕走真實點擊）───────────────────────────────

@pytest.mark.parametrize("approved", [False, True])
def test_contractor_voucher(client, live_server, make_user, new_page, login_as, company, approved):
    import pdf_gen
    req, appr = _users(make_user, "cv%d" % approved, extra_modules=("finance",))
    qno = "MQ-PU-CV%d" % approved
    _seed_quote(qno)
    vno = "CV-PU-%d" % approved
    now = datetime.now().isoformat()
    _db("INSERT INTO vendor_contractors (name) VALUES (?)", ("PU承攬商%d" % approved,), write=True)
    vend = _db("SELECT id FROM vendor_contractors WHERE name=?", ("PU承攬商%d" % approved,))[0]["id"]
    _db("INSERT INTO contractor_dispatches (quote_no, vendor_id) VALUES (?,?)", (qno, vend), write=True)
    disp = _db("SELECT id FROM contractor_dispatches WHERE quote_no=? ORDER BY id DESC LIMIT 1", (qno,))[0]["id"]
    _db("INSERT INTO contractor_payment_vouchers (voucher_no, dispatch_id, quote_no, status, snapshot_json, data_json, created_by, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (vno, disp, qno, "已核准" if approved else "待審核", "{}",
         json.dumps({"approval": _approval(req[0], appr[0])}, ensure_ascii=False), req[0], now, now), write=True)
    _pdf_ok(client, appr, "/api/contractor-vouchers/%s/pdf-download" % vno, not approved)
    page = new_page()
    login_as(page, appr)
    page.goto(f"{live_server}/pages/case-management.html?q={qno}")
    page.wait_for_selector('.cm-tab:has-text("承攬商")', timeout=60000)
    page.click('.cm-tab:has-text("承攬商")')
    page.wait_for_function(f"() => {ROOT}.selected && {ROOT}.selected.quote_no === '{qno}'", timeout=60000)
    page.evaluate(f"async () => {{ const r = {ROOT}; await r.loadContractorVouchers('{qno}'); await r.previewContractorVoucherPdf(r.contractorVouchers[0]) }}")
    page.locator('[x-show="cvPreviewModal"]').wait_for(state="visible", timeout=90000)
    _shot(page, "contractor-voucher-%s" % ("approved" if approved else "unapproved"))
    if approved:
        assert page.locator('[data-testid="preview-return"]:visible').count() == 0
        return
    _html_shot(new_page(), pdf_gen._build_contractor_voucher_html({"voucherNo": vno, "status": "待審核"}), "contractor-voucher-unapproved-html")
    _do_return(page, "匯款對象有誤")
    _eventually("SELECT status FROM contractor_payment_vouchers WHERE voucher_no=?", (vno,), "草稿", "退回後", page=page)
    a = _last_audit("contractor_voucher.reject", page=page)
    assert a and "匯款對象有誤" in (a["detail_json"] or "")


# ─────────────────────────────── 會計傳票（預覽窗是 iframe srcdoc 的 HTML ⇒ 真的看得到紅色橫幅）───────────────────────────────

def _flow_and_voucher(client, make_user, tag, approved):
    boss = make_user(username="pu_vboss" + tag, role="superadmin", modules=["cashier"])
    appr = make_user(username="pu_vappr" + tag, role="admin", modules=["cashier"])
    bh = _hdr(client, boss)
    uid = _db("SELECT id FROM users WHERE username=?", (appr[0],))[0]["id"]
    r = client.put("/api/settings/approval-flow/voucher", headers=bh, json={
        "includeSubmitterManagerTier": False,
        "tiers": [{"approvers": [{"userId": uid, "username": appr[0], "displayName": appr[0]}]}]})
    assert r.status_code == 200, r.text
    lines = [{"account_code": "1113", "debit": 1000, "credit": 0}, {"account_code": "4111", "debit": 0, "credit": 1000}]
    vid = client.post("/api/vouchers", headers=bh, json={"summary": "PU", "lines": lines}).json()["id"]
    assert client.post("/api/vouchers/%s/submit" % vid, headers=bh).status_code == 200
    if approved:
        # 傳票最後一層是最高管理者（會計主管，系統規定；W4）：簽核人簽完第一層，最後一層由「當時存在的最高管理者」簽
        # （名單在送審時算出來：含製票人本人（JV30 製票人在當層名單內可自簽）與展示帳號）⇒ 用製票的最高管理者簽最後一層才算核准
        assert client.post("/api/vouchers/%s/approve" % vid, headers=_hdr(client, appr)).status_code == 200
        r = client.post("/api/vouchers/%s/approve" % vid, headers=_hdr(client, boss))
        assert r.status_code == 200 and r.json().get("status") == "已核准", r.text
    return boss, appr, vid


@pytest.mark.parametrize("approved", [False, True])
def test_accounting_voucher(client, live_server, make_user, new_page, login_as, company, approved):
    boss, appr, vid = _flow_and_voucher(client, make_user, "a%d" % approved, approved)
    page = new_page()
    login_as(page, appr)
    page.goto(f"{live_server}/pages/voucher.html?id={vid}")
    btn = page.locator('[data-testid="voucher-preview"]')
    btn.wait_for(state="visible", timeout=60000)
    page.wait_for_function("() => !document.querySelector('[data-testid=\"voucher-preview\"]').disabled", timeout=60000)
    btn.click()
    frame = page.frame_locator('[data-testid="voucher-preview-frame"]')
    if approved:
        page.locator('[data-testid="voucher-preview-frame"]').wait_for(state="visible", timeout=60000)
        frame.locator("body").wait_for(timeout=60000)
        assert frame.locator('[data-unapproved="1"]').count() == 0
        assert page.locator('[data-testid="preview-return"]:visible').count() == 0
        _shot(page, "accounting-voucher-approved")
        return
    frame.locator('[data-unapproved="1"]').wait_for(state="visible", timeout=60000)      # 紅色橫幅真的在預覽畫面裡
    assert RED_TEXT in frame.locator('[data-unapproved="1"]').inner_text()
    _shot(page, "accounting-voucher-unapproved")
    _do_return(page, "科目有誤")
    row = _db("SELECT status, voucher_no FROM vouchers_all WHERE id=?", (vid,))[0]
    assert row["status"] == "草稿" and row["voucher_no"].endswith("-R1"), row
    assert _last_audit("voucher.send_back", page=page) is not None


# ─────────────────────────────── 簽核佇列預覽（傳票＝HTML 預覽稿，不再 400；出貨單＝PDF，簽核人非管理者）───────────────────────────────

def test_approval_queue_preview_voucher_and_shipping(client, live_server, make_user, new_page, login_as, company):
    boss, appr, vid = _flow_and_voucher(client, make_user, "q", False)
    qno = "MQ-PU-Q"
    _seed_quote(qno)
    nno = "SN-PU-Q"
    now = datetime.now().isoformat()
    _db("INSERT INTO shipping_notes (note_no, quote_no, status, customer_name, project_name, data_json, created_by, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)", (nno, qno, "待審核", "測試客戶", "測試案",
                                       json.dumps({"approval": _approval(boss[0], appr[0])}, ensure_ascii=False), boss[0], now, now), write=True)
    _db("UPDATE users SET modules=? WHERE username=?", (json.dumps(["cashier", "case_manage", "quotation"]), appr[0]), write=True)
    page = new_page()
    login_as(page, appr)
    page.goto(f"{live_server}/pages/approval-queue.html")
    page.wait_for_function(f"() => {ROOT}.queue && {ROOT}.queue.length > 0", timeout=60000)
    page.evaluate(f"""async () => {{ const r = {ROOT}; const it = r.queue.flatMap(g => g.items).find(i => i.type === 'voucher');
        r.selected = it; await r.previewItem(it) }}""")
    page.locator('[x-show="previewModal"]').wait_for(state="visible", timeout=90000)
    html = client.get("/api/vouchers/%s/preview" % vid, headers=_hdr(client, appr)).text      # 預覽視窗載入的就是這一支
    assert page.evaluate(f"() => !!{ROOT}.previewBlobUrl")
    assert 'data-unapproved="1"' in html and RED_TEXT in html
    _shot(page, "approval-queue-voucher-preview")
    _html_shot(new_page(), html, "approval-queue-voucher-preview-html")
    ret = page.locator('[data-testid="preview-return"]:visible')
    ret.wait_for(state="visible", timeout=30000)
    ret.click()
    page.locator('[data-testid="reject-reason"]').wait_for(state="visible", timeout=15000)
    page.once("dialog", lambda d: d.accept())                                   # 沒填原因：頁面先擋（alert）
    page.locator('[data-testid="reject-confirm"]').click()
    assert _db("SELECT status FROM vouchers_all WHERE id=?", (vid,))[0]["status"] != "草稿"
    page.fill('[data-testid="reject-reason"]', "佇列預覽退回")
    page.locator('[data-testid="reject-confirm"]').click()
    page.wait_for_function("() => { const e = document.querySelector('[data-testid=\"reject-reason\"]'); return !e || e.offsetParent === null }", timeout=45000)
    assert _db("SELECT status FROM vouchers_all WHERE id=?", (vid,))[0]["status"] == "草稿"
    page.evaluate(f"""async () => {{ const r = {ROOT}; await r.loadQueue(); const it = r.queue.flatMap(g => g.items).find(i => i.type === 'shipping_note');
        r.selected = it; await r.previewItem(it) }}""")
    page.locator('[x-show="previewModal"]').wait_for(state="visible", timeout=90000)
    assert page.locator('[data-testid="preview-return"]:visible').count() == 1
    _shot(page, "approval-queue-shipping-preview")


# ─────────────────────────────── 自訂模組單據（輸出 iframe 是 HTML ⇒ 看得到紅色橫幅；退回在同頁簽核區）───────────────────────────────

def _cr_module(approver, key):
    return {"name": "預覽警示測試", "permission": "custom.%s" % key, "numbering": {"prefix": "PC", "date": "", "digits": 3},
            "fields": [{"key": "a", "label": "甲", "type": "text", "dataClass": "T1"}],
            "workflow": {"initial": "draft", "states": [
                {"key": "draft", "label": "草稿"},
                {"key": "pending", "label": "簽核中", "approval": {"tiers": [{"approvers": [{"username": approver}]}],
                                                                  "on_approved": "done", "on_rejected": "draft"}},
                {"key": "done", "label": "完成", "final": True}],
                "transitions": [{"key": "submit", "label": "送審", "from": "draft", "to": "pending"}]}}


@pytest.mark.parametrize("approved", [False, True])
def test_custom_record(client, live_server, make_user, new_page, login_as, company, approved):
    key = "pu_cr%d" % approved
    admin = make_user(username="pu_cadmin%d" % approved, role="superadmin")
    mgr = make_user(username="pu_cmgr%d" % approved, role="viewer", modules=[])
    ha = _hdr(client, admin)
    assert client.put("/api/definitions/custom_module/%s/draft" % key, json={"body": _cr_module(mgr[0], key)}, headers=ha).status_code == 200
    assert client.post("/api/definitions/custom_module/%s/publish" % key, json={}, headers=ha).status_code == 200
    user = make_user(username="pu_cuser%d" % approved, role="viewer", modules=["custom.%s" % key])
    hu, hm = _hdr(client, user), _hdr(client, mgr)
    no = client.post("/api/custom/%s/records" % key, json={"values": {"a": "x"}}, headers=hu).json()["record_no"]
    r = client.post("/api/custom/%s/records/%s/transitions/submit" % (key, no), json={}, headers=hu)
    assert r.status_code == 200, r.text
    if approved:
        assert client.post("/api/custom/%s/records/%s/approve" % (key, no), json={"note": "ok"}, headers=hm).status_code == 200
    page = new_page()
    login_as(page, mgr)
    page.goto(f"{live_server}/pages/custom-records.html?key={key}&no={no}")
    page.wait_for_selector("#cr-output-frame", state="attached", timeout=60000)
    frame = page.frame_locator("#cr-output-frame")
    frame.locator("body").wait_for(timeout=60000)
    if approved:
        assert frame.locator('[data-unapproved="1"]').count() == 0
        assert page.locator('[data-testid="preview-return"]:visible').count() == 0
        _shot(page, "custom-record-approved")
        return
    frame.locator('[data-unapproved="1"]').wait_for(state="visible", timeout=60000)
    assert RED_TEXT in frame.locator('[data-unapproved="1"]').inner_text()
    _shot(page, "custom-record-unapproved")
    btn = page.locator('[data-testid="preview-return"]')
    btn.wait_for(state="visible", timeout=30000)
    btn.click()                                                                  # 備註空白 ⇒ 前端先擋，狀態不變
    page.wait_for_function("() => document.querySelector('#cr-record').dataset.busy === '0'", timeout=45000)
    assert _db("SELECT status FROM custom_records WHERE module_key=? AND record_no=?", (key, no))[0]["status"] == "pending"
    page.fill("#cr-decide-note", "預覽頁退回")
    btn.click()
    page.wait_for_function("() => !document.querySelector('#cr-reject')", timeout=45000)
    assert _db("SELECT status FROM custom_records WHERE module_key=? AND record_no=?", (key, no))[0]["status"] == "draft"
    a = _last_audit("custom.reject", page=page)
    assert a and "預覽頁退回" in (a["detail_json"] or "")


# ─────────────────────────────── 報價單（預覽窗 iframe srcdoc；既有「退回修改」，原因必填）───────────────────────────────

@pytest.mark.parametrize("approved", [False, True])
def test_quotation(client, live_server, make_user, new_page, login_as, company, approved):
    req, appr = _users(make_user, "qt%d" % approved)
    qno = "MQ-PU-QT%d" % approved
    now = datetime.now().isoformat()
    data = {"quoteNo": qno, "customerName": "測試客戶", "projectName": "測試案", "taxRate": 5,
            "items": [{"id": 1, "type": "item", "description": "設備", "qty": 1, "unitPrice": 1000, "amount": 1000}],
            "approval": _approval(req[0], appr[0])}
    _db("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, quote_date, sales_person) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (qno, "已送出" if approved else "待審核", "測試客戶", "測試案", 1050, 1000, json.dumps(data, ensure_ascii=False), now, now, "洽談中", "2026-09-30", req[0]), write=True)
    r = client.post("/api/quotations/preview-html", headers=_hdr(client, appr), json={"quoteNo": qno, "data": data, "internal": False})
    assert r.status_code == 200, r.text[:300]
    assert ('data-unapproved="1"' in r.json()["html"]) is (not approved), "預覽 HTML %s含警示" % ("應" if not approved else "不應")
    page = new_page()
    login_as(page, appr)
    page.goto(f"{live_server}/pages/quotation-form.html?id={qno}")
    pv = page.locator("button:has-text('預覽'):visible").first
    pv.wait_for(state="visible", timeout=60000)
    page.wait_for_function(f"() => {ROOT}.q && {ROOT}.q.quoteNo === '{qno}'", timeout=60000)
    page.wait_for_load_state("networkidle")                # init() 最後才註冊 $watch('previewMode')：等載入完再點，否則點了沒人取預覽
    pv.click()
    page.wait_for_function(f"() => {ROOT}.previewMode && !{ROOT}.previewLoading && (({ROOT}.previewHtml || '').length > 0 || {ROOT}.previewError)", timeout=90000)
    assert not page.evaluate(f"() => {ROOT}.previewError"), page.evaluate(f"() => {ROOT}.previewError")
    frame = page.frame_locator("#quote-preview-frame")
    frame.locator("html").wait_for(state="attached", timeout=90000)
    if approved:
        assert frame.locator('[data-unapproved="1"]').count() == 0
        assert page.locator(".modal-foot button:has-text('退回修改'):visible").count() == 0
        _shot(page, "quotation-approved")
        return
    frame.locator('[data-unapproved="1"]').wait_for(state="attached", timeout=60000)      # 預覽 iframe 高度由內容回報，先以「在 DOM 裡」為準
    assert RED_TEXT in frame.locator('[data-unapproved="1"]').text_content()
    _shot(page, "quotation-unapproved")
    ret = page.locator(".modal-foot button:has-text('退回修改'):visible").first
    ret.wait_for(state="visible", timeout=30000)
    ret.click()
    # 🔴 不可用 `textarea:visible`：報價單頁背後的表單（品名、付款條件…）本來就有可見的 textarea，而退回視窗的 textarea 要等
    # x-show 顯示出來才算「可見」——點下去到顯示之間（機器忙時更久），`:visible` 會先命中表單的 textarea ⇒ 原因被填進品名、
    # rejectNote 仍是空的 ⇒「確認退回」disabled ⇒ 點了逾時。依賴的是機器負載（競態），不是日期或資料。
    # 鎖定退回視窗自己的 textarea（x-model=rejectNote，quotation-form.html）並等它真的可見才填。
    reject_box = page.locator('textarea[x-model="rejectNote"]')
    reject_box.wait_for(state="visible", timeout=15000)
    reject_box.fill("報價預覽退回")
    page.locator("button:has-text('確認退回'):visible").first.click()
    page.wait_for_function("() => location.href.indexOf('-R1') >= 0", timeout=60000)
    rows = _db("SELECT status, quote_no FROM quotations WHERE quote_no LIKE ?", (qno + "%",))
    assert any(r["status"] == "草稿" and r["quote_no"].endswith("-R1") for r in rows), rows


def test_last_audit_waits_for_a_late_row_and_gives_up_with_none(client):
    """反向控制：稽核列晚一步才寫入 ⇒ _last_audit 要等到；真的沒有 ⇒ 到時間回 None（不是無限等、也不是假的有）。"""
    import threading
    import time
    action = "zz.late_probe"
    assert _last_audit(action, timeout=0.4) is None
    def late():
        time.sleep(0.6)
        _db("INSERT INTO audit_log (at, action, target_label, detail) VALUES (?,?,?,?)", ("2026-10-02T00:00:00", action, "t", "延遲寫入"), write=True)
    th = threading.Thread(target=late)
    th.start()
    try:
        got = _last_audit(action, timeout=8)
    finally:
        th.join()
    assert got and got["detail_json"] == "延遲寫入"
