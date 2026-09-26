# -*- coding: utf-8 -*-
"""需要應收應付（M05）的題：刪掉 modules/arap 時隨模組消失（PLAYBOOK §B-11）。

（2026-09-26 自 tests/test_tax_basis_r2_2026_09_25.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
R2 零稅率、免稅必填依據（營業稅法 §7、§8；CUSTOMIZATION-SPEC §9.2；BENCHMARK §6.1、§7）。

守住的規則：
① 報價：零稅率／免稅且**非草稿**（送審、解鎖修改）⇒ 沒有有效依據回 400；草稿可以先存。
② §8 與「其他法律規定」一律要填說明。
③ 應稅單存檔時移除殘留的 taxBasis。
④ 開票申請：零稅率／免稅報價要有依據——報價上有就帶入快照；沒有（舊單）就要申請時補填，否則 400。
⑤ 舊資料：沒有依據的舊開票申請照常讀得到（taxBasis=None）。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
from datetime import datetime

import pytest

from helpers.legal_params import TAX_BASIS_OPTIONS, tax_basis_error, tax_basis_label
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


def _hdr(client, make_user, username="r2_root"):
    from tests.test_case_extra_expenses_api_2026_09_11 import _set_empty_approval_flow
    _set_empty_approval_flow()            # 送審需要簽核設定；本檔驗的是依據，不是流程
    u, p = make_user(username=username, role="superadmin")
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _body(status="待審核", **data):
    d = {"customerName": "客戶", "projectName": "專案", "quoteDate": "2026-09-25", "validDays": 30,
         "items": [{"description": "品項", "qty": 1, "unitPrice": 1000, "amount": 1000}],
         "tot": {"total": 1000, "pretax": 1000}}
    d.update(data)
    return {"status": status, "data": d}


def _insert_quote(no, extra, status="已成案", total=20000, pretax=20000):
    import db
    data = {"quoteNo": no, "caseRecord": {"payment": {"items": []}}}
    data.update(extra)
    now = datetime.now().isoformat()
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, total, pretax, data_json, created_at, updated_at, "
            "customer_name) VALUES (?,?,?,?,?,?,?,?)",
            (no, status, total, pretax, json.dumps(data, ensure_ascii=False), now, now, "客戶"))
        conn.commit()
    finally:
        conn.close()


def _stored(no):
    import db
    conn = db.get_db()
    try:
        return json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (no,)).fetchone()[0])
    finally:
        conn.close()


# ── 純函式 ──────────────────────────────────────────────────────────────────────


# ── ① 報價 ──────────────────────────────────────────────────────────────────────


# ── ④ 開票申請 ──────────────────────────────────────────────────────────────────

def _voucher(client, h, body):
    return client.post("/api/invoice-vouchers", json=body, headers=h)


def test_invoice_request_copies_the_quote_basis_into_the_snapshot(client, make_user):
    h = _hdr(client, make_user)
    _insert_quote("MQ-R2Z", {"taxRate": 0, "taxType": "zero", "taxBasis": {"code": "7-1", "note": "出口報單"}})
    rem = client.get("/api/invoice-vouchers/remaining?quote_no=MQ-R2Z", headers=h).json()
    assert rem["taxBasisMissing"] is False and "外銷貨物" in rem["taxBasisLabel"]
    r = _voucher(client, h, {"quote_no": "MQ-R2Z", "scope": "amount", "amount": 5000})
    assert r.status_code == 201, r.text
    v = client.get("/api/invoice-vouchers/" + r.json()["voucher_no"], headers=h).json()
    assert v["taxBasis"] == {"code": "7-1", "note": "出口報單"}
    assert v["taxNote"] == "零稅率依據：" + tax_basis_label({"code": "7-1", "note": "出口報單"})


def test_invoice_request_on_an_old_quote_without_basis_needs_one(client, make_user):
    h = _hdr(client, make_user)
    _insert_quote("MQ-R2E", {"taxRate": 0})
    rem = client.get("/api/invoice-vouchers/remaining?quote_no=MQ-R2E", headers=h).json()
    assert (rem["taxType"], rem["taxBasisMissing"]) == ("exempt", True)
    r = _voucher(client, h, {"quote_no": "MQ-R2E", "scope": "amount", "amount": 5000})
    assert r.status_code == 400 and "開票申請補填" in r.json()["detail"], r.text
    r = _voucher(client, h, {"quote_no": "MQ-R2E", "scope": "amount", "amount": 5000,
                             "taxBasis": {"code": "8-3"}})
    assert r.status_code == 201, r.text


def test_taxable_invoice_request_needs_no_basis(client, make_user):
    h = _hdr(client, make_user)
    _insert_quote("MQ-R2T", {"taxRate": 5, "taxType": "taxable"}, total=21000, pretax=20000)
    r = _voucher(client, h, {"quote_no": "MQ-R2T", "scope": "amount", "amount": 5250})
    assert r.status_code == 201, r.text
    v = client.get("/api/invoice-vouchers/" + r.json()["voucher_no"], headers=h).json()
    assert v["taxBasis"] is None


def test_an_old_voucher_without_basis_still_reads(client, make_user):
    import db
    h = _hdr(client, make_user)
    _insert_quote("MQ-R2V", {"taxRate": 0})
    now = datetime.now().isoformat()
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO invoice_vouchers (voucher_no, quote_no, scope, amount, status, snapshot_json, data_json, "
            "created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("IV-OLD-R2", "MQ-R2V", "amount", 1000, "草稿",
             json.dumps({"customerName": "客戶", "taxType": "exempt"}), "{}", "x", now, now))
        conn.commit()
    finally:
        conn.close()
    r = client.get("/api/invoice-vouchers/IV-OLD-R2", headers=h)
    assert r.status_code == 200 and r.json()["taxBasis"] is None, r.text
