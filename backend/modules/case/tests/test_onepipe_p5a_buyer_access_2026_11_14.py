# -*- coding: utf-8 -*-
"""一條龍 P5a（旗標 `onepipe.buyer_access`，預設關）：採購同仁看供應商唯讀清單＋提「請購單」。

- 旗標關 ⇒ 與今天位元組相同（非管理員供應商清單＝`[]`；採購同仁碰不到請購單）。
- 旗標開 ⇒ 供應商清單只回白名單欄位（沒有銀行帳號／customFields／聯絡人明細）；請購單只限看得到的案件、只限「請購單」種類與自己的單。
- 沒有採購模組權限、案件看不到（404）、其他單據種類（403/404）一律照舊。
"""
import json

import pytest

import db

NO = "MQ-P5A-1"
HIDDEN = "MQ-P5A-2"
BASE = "/api/quotations/%s/extra-expenses" % NO
SUP_DATA = {"alias": "輝", "category": "網通", "currency": "TWD", "paymentTerms": "月結30天", "active": True,
            "contacts": [{"name": "王小姐", "title": "業務", "phone": "0912345678", "email": "w@x.com"}],
            "bankAccount": "012-345-6789", "bankName": "某銀行", "customFields": {"內部成本係數": "0.7"}, "note": "不能外洩"}


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _flag(monkeypatch, on):
    from helpers import onepipe_flags
    monkeypatch.setattr(onepipe_flags, "flag_on", lambda field, conn=None: bool(on) and field == "buyer_access")


@pytest.fixture
def W(client, make_user):
    make_user(username="p5a_sa", role="superadmin")
    buyer = make_user(username="p5a_buyer", role="sales", modules=["procurement", "case_manage"])
    other = make_user(username="p5a_buyer2", role="sales", modules=["procurement", "case_manage"])
    nomod = make_user(username="p5a_nomod", role="sales", modules=["case_manage"])
    conn = db.get_db()
    try:
        for no in (NO, HIDDEN):
            conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at, sales_person, deal_tag)"
                         " VALUES (?,?,?,?,?,?,?,?,?)", (no, "已送出", "客", "案", "{}", "2026-11-14T00:00:00", "2026-11-14T00:00:00", "p5a_sa", "已成案"))
        conn.execute("INSERT INTO suppliers (code, name, tax_id, phone, lead_time_days, data_json) VALUES (?,?,?,?,?,?)",
                     ("S001", "輝煌網通", "12345678", "02-1234", 7, json.dumps(SUP_DATA)))
        conn.commit()
    finally:
        conn.close()
    return client, {"sa": _login(client, "p5a_sa", "Test-Pass-123"), "buyer": _login(client, *buyer),
                    "other": _login(client, *other), "nomod": _login(client, *nomod)}


def _body(kind="purchase_req"):
    return {"kind": kind, "lines": [{"category": "雜項", "summary": "x", "qty": 1, "unitCost": 100}],
            "payeeName": "某人", "payeeType": "employee", "data": {"applicant": "p5a_buyer"}}


def _grant_case(username, no=NO):
    """把使用者加為案件協作者（看得到案件）——用 assigned_user_ids。"""
    conn = db.get_db()
    try:
        uid = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
        conn.execute("UPDATE quotations SET assigned_user_ids=? WHERE quote_no=?", (json.dumps([uid]), no))
        conn.commit()
    finally:
        conn.close()


# ── 登錄表欄位 ──────────────────────────────────────────────────────────────
def test_registry_field_is_default_off_loosening_and_labeled():
    from helpers import settings_registry as R
    f = R.field_defs("onepipe")["buyer_access"]
    assert f.default == 0 and f.recommended == 0 and f.loosen == "up"
    assert "放寬權限，需最高管理者開啟" in f.label


def test_flag_is_not_switched_on_by_the_default_on_migration():
    from helpers import startup
    assert "buyer_access" in startup._ONEPIPE_PERMISSION_FLAGS


# ── 供應商唯讀清單 ──────────────────────────────────────────────────────────
def test_flag_off_non_admin_supplier_list_is_empty_like_today(W, monkeypatch):
    _flag(monkeypatch, False)
    c, h = W
    r = c.get("/api/suppliers", headers=h["buyer"])
    assert r.status_code in (200, 403)
    if r.status_code == 200:
        assert r.json() == []


def test_flag_on_buyer_gets_only_whitelisted_supplier_fields(W, monkeypatch):
    from modules.supply.api.suppliers import BUYER_SUPPLIER_FIELDS
    _flag(monkeypatch, True)
    c, h = W
    r = c.get("/api/suppliers", headers=h["buyer"])
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 1
    row = rows[0]
    assert set(row) == set(BUYER_SUPPLIER_FIELDS)
    assert row["name"] == "輝煌網通" and row["taxId"] == "12345678" and row["contact"] == "王小姐" and row["paymentTerms"] == "月結30天"
    text = json.dumps(row, ensure_ascii=False)
    for leaked in ("012-345-6789", "某銀行", "內部成本係數", "不能外洩", "0912345678", "w@x.com", "業務"):
        assert leaked not in text, leaked


def test_flag_on_without_procurement_module_still_empty(W, monkeypatch):
    _flag(monkeypatch, True)
    c, h = W
    r = c.get("/api/suppliers", headers=h["nomod"])
    assert r.status_code in (200, 403)
    if r.status_code == 200:
        assert r.json() == []


def test_admin_path_is_unchanged_and_still_full(W, monkeypatch):
    _flag(monkeypatch, True)
    c, h = W
    rows = c.get("/api/suppliers", headers=h["sa"]).json()
    assert len(rows) == 1 and "bankAccount" in json.dumps(rows[0], ensure_ascii=False) or "customFields" in json.dumps(rows[0])


# ── 請購單 ─────────────────────────────────────────────────────────────────
def test_flag_off_buyer_who_cannot_see_the_case_gets_404_on_create(W, monkeypatch):
    _flag(monkeypatch, False)
    c, h = W
    r = c.post(BASE, headers=h["buyer"], json=_body())
    assert r.status_code in (403, 404), r.text


def test_flag_on_buyer_can_create_edit_submit_and_delete_own_purchase_req(W, monkeypatch):
    _flag(monkeypatch, True)
    c, h = W
    r = c.post(BASE, headers=h["buyer"], json=_body())
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    r = c.patch("%s/%d" % (BASE, eid), headers=h["buyer"], json=_body())
    assert r.status_code == 200, r.text
    r = c.post("%s/%d/submit" % (BASE, eid), headers=h["buyer"])
    # 已通過案件守門；測試帳號沒有組織部門，所以是簽核鏈（組織設定）擋下，而不是 403／404
    assert r.status_code not in (403, 404) and "部門" in r.text, r.text
    r2 = c.post(BASE, headers=h["buyer"], json=_body())
    assert r2.status_code == 201
    assert c.delete("%s/%d" % (BASE, r2.json()["id"]), headers=h["buyer"]).status_code == 200


def test_flag_on_buyer_cannot_create_other_kinds(W, monkeypatch):
    _flag(monkeypatch, True)
    c, h = W
    for kind in ("purchase_order", "expense", "payment_request"):
        r = c.post(BASE, headers=h["buyer"], json=_body(kind))
        assert r.status_code in (400, 403, 404), (kind, r.status_code, r.text)


def test_flag_on_other_buyer_cannot_touch_someone_elses_purchase_req(W, monkeypatch):
    _flag(monkeypatch, True)
    c, h = W
    eid = c.post(BASE, headers=h["buyer"], json=_body()).json()["id"]
    for r in (c.patch("%s/%d" % (BASE, eid), headers=h["other"], json=_body()),
              c.post("%s/%d/submit" % (BASE, eid), headers=h["other"]),
              c.delete("%s/%d" % (BASE, eid), headers=h["other"])):
        assert r.status_code in (403, 404), r.text


def test_flag_on_without_procurement_module_cannot_create(W, monkeypatch):
    _flag(monkeypatch, True)
    c, h = W
    r = c.post(BASE, headers=h["nomod"], json=_body())      # 有案件管理模組、沒採購模組：看得到案件但不是採購同仁 ⇒ 照舊擋
    assert r.status_code in (403, 404), r.text


def test_flag_on_buyer_on_a_case_they_cannot_see_gets_404(W, monkeypatch):
    """不是案件成員、也沒有案件管理模組 ⇒ 看不到案件 ⇒ 404（不洩漏案件存在）。"""
    _flag(monkeypatch, True)
    c, h = W
    conn = db.get_db()
    try:
        conn.execute("UPDATE users SET modules=? WHERE username='p5a_buyer'", (json.dumps(["procurement"]),))
        conn.commit()
    finally:
        conn.close()
    r = c.post(BASE, headers=h["buyer"], json=_body())
    assert r.status_code == 404, r.text


def test_flag_on_buyer_cannot_list_the_cases_expenses(W, monkeypatch):
    """只開「提請購單」，不開「看這案的支出清單」。"""
    _flag(monkeypatch, True)
    c, h = W
    r = c.get(BASE, headers=h["buyer"])
    assert r.status_code in (200, 403, 404)
    if r.status_code == 200:
        assert r.json() in ([], {"items": []}) or not r.json().get("items", r.json())


# ── 叫料：仍需金額檢視權限，被擋有白話訊息 ───────────────────────────────────
def test_material_order_refusal_explains_in_plain_words_only_when_flag_on(W, monkeypatch):
    c, h = W
    url = "/api/quotations/%s/material-orders" % NO
    body = {"materialOrders": []}
    _flag(monkeypatch, False)
    off = c.patch(url, headers=h["buyer"], json=body)
    _flag(monkeypatch, True)
    on = c.patch(url, headers=h["buyer"], json=body)
    assert off.status_code == on.status_code, (off.text, on.text)
    if on.status_code == 403:
        assert "請購單" not in off.text
        assert "請購單" in on.text
