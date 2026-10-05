# -*- coding: utf-8 -*-
"""承攬商收款帳號遮蔽（使用者裁示 2026-10-01：只有最高管理者看得到完整帳號，其餘一律遮蔽）。

涵蓋：承攬商（vendor_contractors）列表／詳情／存簿影本、匯款申請（contractor-vouchers）列表／詳情／提供者形狀、
簽核佇列（列表）、匯款申請 PDF 的版面、編輯時遮蔽值原樣送回不可覆蓋真帳號。
反向控制：把 `can_see_full` 改成永遠 True ⇒ 一般管理員會看到全碼（證明題目真的在抓遮蔽）。
"""
from tests._requires import requires_module  # noqa: E402
needs_m01 = requires_module("case", "本題打 M01 的簽核佇列端點")
import json

import pytest

FULL = "00012345678901"
MASKED = "****8901"
PASSBOOK = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGA"


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture()
def world(client, make_user):
    sa, sapw = make_user(username="bm_sa", role="superadmin")[:2]
    ad, adpw = make_user(username="bm_admin", role="admin",
                         modules=["contractor_list", "procurement", "case_manage", "quotation"])[:2]          # 第42班：財務／出納勾選失效（有勾會被當成財務角色）；這題要的是「一般 admin」
    h_sa, h_ad = _login(client, sa, sapw), _login(client, ad, adpw)
    r = client.post("/api/vendor-contractors", headers=h_sa, json={
        "name": "測試承攬商", "tax_id": "12345678",
        "data": {"bankCode": "700", "bankName": "中華郵政", "bankBranch": "台中", "bankAccountName": "測試承攬商",
                 "bankAccountNumber": FULL}})
    assert r.status_code == 201, r.text
    vid = r.json()["id"]
    assert client.put("/api/vendor-contractors/%d/passbook" % vid, headers=h_sa, json={"bank_passbook": PASSBOOK}).status_code == 200
    return client, h_sa, h_ad, vid


def _db():
    import db
    return db.get_db()


def _seed_voucher():
    snap = {"vendorName": "測試承攬商", "grandTotal": 1000, "bankAccountName": "測試承攬商", "bankAccountNumber": FULL,
            "bankPassbookImage": PASSBOOK,
            "personnel": [{"name": "甲", "bankAccountNumber": "99887766554433", "bankPassbookImage": PASSBOOK}]}
    conn = _db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                     ("MQ-BM-001", "已送出", "客", "案", "{}", "2026-01-01", "2026-01-01"))
        conn.execute("INSERT INTO contractor_dispatches (id, quote_no, vendor_id, dispatch_date, scope, items_json, personnel_json, total_amount,"
                     " tax_rate, status, notes, created_by, created_at, updated_at, accepted_at, accepted_by, files_json, invoice_files_json)"
                     " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (99201, "MQ-BM-001", None, "2026-09-01", "測試", "[]", "[]", 1000, 0, "已完成", "", "x",
                      "2026-01-01T00:00:00", "2026-01-01T00:00:00", "", "", "[]", "[]"))
        conn.execute("INSERT INTO contractor_payment_vouchers (voucher_no, quote_no, dispatch_id, status, snapshot_json, data_json, created_by, created_at, updated_at)"
                     " VALUES (?,?,?,?,?,?,?,?,?)",
                     ("CV-BM-001", "MQ-BM-001", 99201, "待審核", json.dumps(snap, ensure_ascii=False),
                      json.dumps({"approval": {"tiers": [{"approvers": [{"username": "bm_sa", "status": "pending"}]}], "currentTier": 0}},
                                 ensure_ascii=False),
                      "x", "2026-01-01T00:00:00", "2026-01-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _stored_number(vid):
    conn = _db()
    try:
        return json.loads(conn.execute("SELECT data_json FROM vendor_contractors WHERE id=?", (vid,)).fetchone()[0])["bankAccountNumber"]
    finally:
        conn.close()


# ── 承攬商 ───────────────────────────────────────────────────────────────

def test_vendor_detail_and_list_mask_for_admin_full_for_superadmin(world):
    client, h_sa, h_ad, vid = world
    for hdr, want in ((h_sa, FULL), (h_ad, MASKED)):                       # 正向控制：最高管理者要看得到全碼
        d = client.get("/api/vendor-contractors/%d" % vid, headers=hdr).json()
        assert d["bankAccountNumber"] == want and d["hasPassbook"] is True
        lst = client.get("/api/vendor-contractors", headers=hdr).json()
        assert [x["bankAccountNumber"] for x in lst if x["id"] == vid] == [want]
    assert FULL not in client.get("/api/vendor-contractors/%d" % vid, headers=h_ad).text


def test_vendor_passbook_image_only_for_superadmin(world):
    client, h_sa, h_ad, vid = world
    assert client.get("/api/vendor-contractors/%d/passbook" % vid, headers=h_sa).json()["bank_passbook"].startswith("data:image/")
    r = client.get("/api/vendor-contractors/%d/passbook" % vid, headers=h_ad).json()
    assert r["bank_passbook"] == "" and r["masked"] is True


def test_editing_with_masked_value_keeps_the_real_number(world):
    client, h_sa, h_ad, vid = world
    body = {"name": "測試承攬商", "tax_id": "12345678", "contact_name": "改了聯絡人",
            "data": {"bankCode": "700", "bankName": "中華郵政", "bankBranch": "台中", "bankAccountName": "測試承攬商",
                     "bankAccountNumber": MASKED}}
    assert client.put("/api/vendor-contractors/%d" % vid, headers=h_ad, json=body).status_code == 200
    assert _stored_number(vid) == FULL, "遮蔽值被原樣存回，真帳號被覆蓋"
    body["data"]["bankAccountNumber"] = "11112222333344"                     # 輸入新帳號才會更換
    assert client.put("/api/vendor-contractors/%d" % vid, headers=h_ad, json=body).status_code == 200
    assert _stored_number(vid) == "11112222333344"


# ── 匯款申請 ─────────────────────────────────────────────────────────────

@needs_m01
def test_voucher_list_detail_mask_for_admin_full_for_superadmin(world, make_user):
    # 第42班：匯款申請的金額層＝財務角色；「一般管理員（非 superadmin）看遮罩」改由財務角色代表
    _u = make_user(username="bm_fin_peradmin", role="finance")
    client, h_sa, h_ad, _vid = world
    h_ad = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": _u[0], "password": _u[1]}).json()["token"]}
    _seed_voucher()
    d_sa = client.get("/api/contractor-vouchers/CV-BM-001", headers=h_sa).json()
    assert d_sa["bankAccountNumber"] == FULL and d_sa["snapshot"]["bankAccountNumber"] == FULL and d_sa["bankPassbookImage"] == PASSBOOK
    r = client.get("/api/contractor-vouchers/CV-BM-001", headers=h_ad)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["bankAccountNumber"] == MASKED and d["snapshot"]["bankAccountNumber"] == MASKED
    assert d["bankPassbookImage"] == "" and d["snapshot"]["bankPassbookImage"] == ""
    assert d["snapshot"]["personnel"][0]["bankAccountNumber"] == "****4433" and d["snapshot"]["personnel"][0]["bankPassbookImage"] == ""
    assert FULL not in r.text and "99887766554433" not in r.text
    lst = client.get("/api/contractor-vouchers", headers=h_ad).json()
    assert [x["bankAccountNumber"] for x in lst if x["voucherNo"] == "CV-BM-001"] == [MASKED]


@needs_m01
def test_voucher_provider_shape_is_masked_without_a_viewer(world):
    """IP-14 提供者（出納／會計）沒有檢視者 ⇒ fail closed：遮蔽。"""
    from modules.subcontract.api import contractor_vouchers as cv
    _seed_voucher()
    conn = _db()
    try:
        row = conn.execute("SELECT * FROM contractor_payment_vouchers WHERE voucher_no='CV-BM-001'").fetchone()
    finally:
        conn.close()
    assert cv._voucher_public(row)["bankAccountNumber"] == MASKED
    assert cv._voucher_public(row, viewer={"role": "superadmin"})["bankAccountNumber"] == FULL


# ── 簽核佇列 ─────────────────────────────────────────────────────────────

@needs_m01
def test_approval_queue_masks_bank_for_non_superadmin(world):
    client, h_sa, h_ad, _vid = world
    _seed_voucher()

    def item(hdr):
        q = client.get("/api/approval-queue", headers=hdr).json()["queue"]
        its = [it for g in q for it in g["items"] if "CV-BM-001" in json.dumps(it, ensure_ascii=False)]
        return its[0] if its else None
    it_sa = item(h_sa)
    assert it_sa and it_sa["bankAccountNumber"] == FULL                     # 正向控制
    it_ad = item(h_ad)
    if it_ad is not None:                                                    # admin 在這張單的可見範圍內時：遮蔽
        assert it_ad["bankAccountNumber"] == MASKED and it_ad["bankPassbookImage"] == ""
        assert it_ad["personnelBanks"][0]["bankAccountNumber"] == "****4433"


def test_mask_bank_deep_is_pure_and_recursive():
    from routers.approval_queue import _mask_bank_deep
    src = {"a": [{"bankAccountNumber": FULL, "x": {"bank_passbook_image": PASSBOOK, "bank_account_number": "12"}}], "ok": 1}
    out = _mask_bank_deep(src)
    assert out["a"][0]["bankAccountNumber"] == MASKED and out["a"][0]["x"]["bank_passbook_image"] == ""
    assert out["a"][0]["x"]["bank_account_number"] == "****"
    assert src["a"][0]["bankAccountNumber"] == FULL, "不可改原物件"


# ── PDF 版面 ─────────────────────────────────────────────────────────────

def test_voucher_pdf_html_masks_account_and_drops_passbook(world):
    import pdf_gen
    v = {"vendorName": "測試承攬商", "bankAccountNumber": FULL, "bankPassbookImage": PASSBOOK, "status": "已核准",
         "personnel": [{"name": "甲", "bankAccountNumber": "99887766554433", "bankPassbookImage": PASSBOOK}]}
    full = pdf_gen._build_contractor_voucher_html(v)
    assert FULL in full and "99887766554433" in full                          # 正向控制：不遮蔽時看得到
    masked = pdf_gen._build_contractor_voucher_html(v, mask_bank=True)
    assert FULL not in masked and "99887766554433" not in masked and PASSBOOK not in masked
    assert MASKED in masked and "****4433" in masked


# ── 反向控制 ─────────────────────────────────────────────────────────────

def test_reverse_control_without_the_mask_admin_would_see_the_full_number(world, monkeypatch):
    client, _h_sa, h_ad, vid = world
    from modules.subcontract import bank_mask
    monkeypatch.setattr(bank_mask, "can_see_full", lambda user: True)
    assert client.get("/api/vendor-contractors/%d" % vid, headers=h_ad).json()["bankAccountNumber"] == FULL


# ── G1（稽核）：匯款申請 PDF 在「PDF 文字」層級也遮蔽（不只 HTML 版面）──────────────────────────────

def _pdf_text(pdf_bytes):
    import io
    import pypdf
    return "".join((p.extract_text() or "") for p in pypdf.PdfReader(io.BytesIO(pdf_bytes)).pages)


def test_g1_voucher_pdf_download_text_is_masked_for_admin_and_full_for_superadmin(world, make_user):
    # 第42班：匯款申請的金額層＝財務角色；「一般管理員（非 superadmin）看遮罩」改由財務角色代表
    _u = make_user(username="bm_fin_peradmin", role="finance")
    client, h_sa, h_ad, _vid = world
    h_ad = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": _u[0], "password": _u[1]}).json()["token"]}
    _seed_voucher()
    ad = client.get("/api/contractor-vouchers/CV-BM-001/pdf-download", headers=h_ad)
    assert ad.status_code == 200 and ad.content[:5] == b"%PDF-", ad.text[:200]
    t_ad = _pdf_text(ad.content)
    assert FULL not in t_ad and "99887766554433" not in t_ad and "8901" in t_ad          # 一般管理員：PDF 文字裡找不到全碼、有末四碼
    sa = client.get("/api/contractor-vouchers/CV-BM-001/pdf-download", headers=h_sa)
    assert sa.status_code == 200
    t_sa = _pdf_text(sa.content)
    assert FULL in t_sa                                                                  # 正對照：最高管理者的 PDF 看得到全碼（證明抽文字有效）


def test_g1_mutation_mask_bank_false_turns_the_pdf_assertion_red(world, make_user, monkeypatch):
    # 第42班：匯款申請的金額層＝財務角色；「一般管理員（非 superadmin）看遮罩」改由財務角色代表
    _u = make_user(username="bm_fin_tion_red", role="finance")
    """突變：端點對一般管理員也傳 mask_bank=False ⇒ PDF 文字出現全碼 ⇒ 上一題的斷言會紅（偵測器本身有被驗過）。"""
    client, _h_sa, h_ad, _vid = world
    h_ad = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": _u[0], "password": _u[1]}).json()["token"]}
    _seed_voucher()
    import modules.subcontract.api.contractor_vouchers as CV
    real = CV.generate_contractor_voucher_pdf_bytes
    monkeypatch.setattr(CV, "generate_contractor_voucher_pdf_bytes", lambda no, mask_bank=True: real(no, mask_bank=False))
    r = client.get("/api/contractor-vouchers/CV-BM-001/pdf-download", headers=h_ad)
    assert r.status_code == 200
    assert FULL in _pdf_text(r.content), "突變沒讓 PDF 洩漏 ⇒ 偵測器壞了"
