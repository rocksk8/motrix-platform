# -*- coding: utf-8 -*-
"""需要外包工班（M04）的題：刪掉 modules/subcontract 時隨模組消失（PLAYBOOK §B-11，稽核 D M04-M1）。

（2026-09-26 自 tests/test_privacy_notice_forms_2026_09_26.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
個資蒐集告知擴大到其他表單（2026-09-26；CUSTOMIZATION-SPEC §9.3，沿用 R3 機制）。

守住的規則：
① 告知文字依用途分開（承攬／聯絡人／使用者帳號），公司可各自改寫，空白 ⇒ 該用途的範本；不認得的用途 400。
② 客戶／供應商的每一位聯絡人、承攬商、使用者帳號：「已告知」由伺服器蓋時間、人員、當下告知文字的雜湊，
   存在設定鍵 `privacy_notice_acks`；已記錄的不能被覆蓋（告知文字改版後再記一次也不變），並寫稽核。
③ 沒有紀錄不擋存檔。
"""
import pytest

from helpers import privacy_notice as pn


def _hdr(client, make_user, username="pn2_root", role="superadmin"):
    u, p = make_user(username=username, role=role)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _audit_count(action, target_id):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT COUNT(*) FROM audit_log WHERE action=? AND target_id=?",
                            (action, str(target_id))).fetchone()[0]
    finally:
        conn.close()


# ── ① 用途別的告知文字 ─────────────────────────────────────────────────────────


# ── ② 客戶／供應商的聯絡人 ─────────────────────────────────────────────────────

_CONTACT_KINDS = [("customers", "customer_contact", "customer.privacy_notice_ack"),
                  ("suppliers", "supplier_contact", "supplier.privacy_notice_ack")]


def _with_contacts(client, h, base):
    body = {"name": "聯絡測試公司", "data": {"contacts": [{"id": 111, "name": "王聯絡", "phone": "0912"},
                                                        {"id": "abc", "name": "李聯絡"}]}}
    r = client.post(f"/api/{base}", json=body, headers=h)
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ── ② 承攬商、使用者帳號 ──────────────────────────────────────────────────────

def test_vendor_ack_is_recorded_once_and_needs_admin(client, make_user):
    h = _hdr(client, make_user)
    r = client.post("/api/vendor-contractors", json={"name": "承攬商甲", "contact_name": "陳窗口"}, headers=h)
    assert r.status_code == 201, r.text
    vid = r.json()["id"]
    assert client.get(f"/api/vendor-contractors/{vid}/privacy-notice", headers=h).json()["ack"] is None
    r1 = client.post(f"/api/vendor-contractors/{vid}/privacy-notice/ack", headers=h)
    assert r1.status_code == 200 and r1.json()["created"] is True, r1.text
    assert r1.json()["ack"]["noticeHash"] == pn.notice_hash(pn.current_purpose_notice("contact"))
    r2 = client.post(f"/api/vendor-contractors/{vid}/privacy-notice/ack", headers=h)
    assert r2.json()["created"] is False and r2.json()["ack"] == r1.json()["ack"]
    assert _audit_count("vendor.privacy_notice_ack", vid) == 1
    assert client.post("/api/vendor-contractors/999999/privacy-notice/ack", headers=h).status_code == 404
    hv = _hdr(client, make_user, "pn2_sales", role="sales")
    assert client.post(f"/api/vendor-contractors/{vid}/privacy-notice/ack", headers=hv).status_code == 403


# ── ④ 單據上手動輸入的聯絡人（2026-09-26 主持裁示：報價單、案件、完工單、網路規劃書）─────────

def _insert_quote(quote_no, contact="林聯絡", site="趙現場"):
    import json as _json
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "告知測試", 1000, 952,
             _json.dumps({"dealTag": "已成案", "contactName": contact,
                          "caseRecord": {"contract": {"contactPerson": site}}}, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"))
        conn.commit()
    finally:
        conn.close()
