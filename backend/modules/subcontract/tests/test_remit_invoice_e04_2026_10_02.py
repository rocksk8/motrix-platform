# -*- coding: utf-8 -*-
"""31-B S4：分期申請的發票與總帳 E04 逐張（使用者裁示 D11：發票可事後補；沒有發票日就不產生該期的應付認列分錄）。
RK11：
- `PATCH /api/contractor-vouchers/{no}/invoice` 只給分期申請（舊式整筆的發票在派發上）、作廢的不能登、不影響金額；
- 有未作廢分期申請的派發：總帳 E04 改由各期申請逐張認列（source_type=contractor_voucher_invoice、source_key＝申請單號、doc_no＝該期發票號、event_date＝該期發票日），
  派發層的 E04 不再出現（同一派發只會有一種層級，否則成本翻倍）；沒有發票日的期別、草稿／未核准的期別都不認列；
- 各期 E04 稅前合計＝派發稅前、稅額合計＝整筆稅額（最後一期補差已凍結在快照）；
- 派發層已登錄發票日 ⇒ 不能改開分期；已改分期 ⇒ 派發層不再收發票日；
- 舊式整筆申請（kind=''）的 E04／E05 形狀不變；E05 的 `meta.dispatch_invoiced` 分期看該期自己的發票日。
反向控制：把分期申請作廢 ⇒ 派發層 E04 回來（證明排除是看『有沒有未作廢的分期申請』）。"""
import json

import pytest


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture()
def hs(client, make_user):
    out = {}
    for name, role in (("rki_admin", "admin"), ("rki_sales", "sales")):
        u, p = make_user(username=name, role=role)[:2]
        out[name] = _login(client, u, p)
    return out


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


def _dispatch(total=1000, status="accepted", invoice_date=""):
    vid = (_db("SELECT id FROM vendor_contractors WHERE name='RKI廠商'") or [{}])[0].get("id")
    if not vid:
        _db("INSERT INTO vendor_contractors (name, tax_id, created_at, updated_at) VALUES ('RKI廠商','12345678','2026-10-01','2026-10-01')")
        vid = _db("SELECT id FROM vendor_contractors WHERE name='RKI廠商'")[0]["id"]
    _db("INSERT INTO contractor_dispatches (quote_no, vendor_id, status, total_amount, tax_rate, items_json, personnel_json, approval_status, invoice_date, invoice_no, created_at, updated_at)"
        " VALUES ('MQ-RKI-1',?,?,?,0.05,?,'[]','',?,?, '2026-10-01','2026-10-01')",
        (vid, status, total, json.dumps([{"description": "工項", "amount": total}], ensure_ascii=False), invoice_date, "DISP-INV" if invoice_date else ""))
    return _db("SELECT MAX(id) AS i FROM contractor_dispatches")[0]["i"]


def _create(client, h, did, **kw):
    r = client.post("/api/contractor-vouchers", headers=h, json=dict({"dispatch_id": did}, **kw))
    assert r.status_code == 201, r.text
    return r.json()["voucher_no"]


def _invoice(client, h, no, inv_no="AB-1", inv_date="2026-10-05"):
    return client.patch("/api/contractor-vouchers/%s/invoice" % no, headers=h, json={"invNo": inv_no, "invDate": inv_date})


def _approve(*nos):
    for n in nos:
        _db("UPDATE contractor_payment_vouchers SET status='已核准' WHERE voucher_no=?", (n,))


def _events():
    from modules.subcontract import gl_events
    return gl_events.gl_events("2026-01-01", "2026-12-31")["events"]


def _of(events, code, **kw):
    return [e for e in events if e["event_code"] == code and all(e.get(k) == v for k, v in kw.items())]


def _sum(ev, role, side):
    return sum(l["amount"] for l in ev["lines"] if l["role"] == role and l["side"] == side)


def test_rk11_per_voucher_e04_three_periods_add_up_to_the_dispatch(client, hs):
    h = hs["rki_admin"]
    did = _dispatch(total=100)
    a = _create(client, h, did, kind="deposit", ratio_percent=33.33)
    b = _create(client, h, did, kind="progress", ratio_percent=33.33)
    c = _create(client, h, did, kind="completion", ratio_percent=33.34)
    _approve(a, b, c)
    assert _invoice(client, h, a, "AB-1", "2026-10-05").status_code == 200
    assert _invoice(client, h, b, "AB-2", "2026-10-06").status_code == 200
    ev = _of(_events(), "E04", source_type="contractor_voucher_invoice")
    assert sorted(e["source_key"] for e in ev) == sorted([a, b])                              # 第 3 期沒有發票日 ⇒ 不認列（D11）
    assert not _of(_events(), "E04", source_type="contractor_dispatch")
    assert _invoice(client, h, c, "AB-3", "2026-10-07").status_code == 200
    ev = _of(_events(), "E04", source_type="contractor_voucher_invoice")
    assert len(ev) == 3
    assert sum(_sum(e, "COST_PROJECT", "D") for e in ev) == 100                                  # 稅前合計＝派發稅前
    assert sum(_sum(e, "INPUT_TAX", "D") for e in ev) == 5                                       # 稅額合計＝整筆稅額（最後一期補差）
    assert sum(_sum(e, "AP", "C") for e in ev) == 105
    for e in ev:
        assert _sum(e, "COST_PROJECT", "D") + _sum(e, "INPUT_TAX", "D") == _sum(e, "AP", "C")
    first = [e for e in ev if e["source_key"] == a][0]
    assert first["doc_no"] == "AB-1" and first["event_date"] == "2026-10-05" and first["case_no"] == "MQ-RKI-1" and first["meta"]["remit_kind"] == "deposit"


def test_rk11_draft_or_unapproved_periods_are_not_recognised(client, hs):
    h = hs["rki_admin"]
    did = _dispatch()
    a = _create(client, h, did, kind="deposit", amount=300)
    assert _invoice(client, h, a).status_code == 200
    assert not _of(_events(), "E04", source_type="contractor_voucher_invoice")                   # 草稿
    _approve(a)
    assert len(_of(_events(), "E04", source_type="contractor_voucher_invoice")) == 1
    assert _invoice(client, h, a, "", "").status_code == 200                                     # 清除發票 ⇒ 認列消失
    assert not _of(_events(), "E04", source_type="contractor_voucher_invoice")


def test_rk11_dispatch_level_e04_is_replaced_not_doubled_and_comes_back_when_installments_are_voided(client, hs):
    h = hs["rki_admin"]
    did = _dispatch(total=1000)
    a = _create(client, h, did, kind="deposit", amount=300)
    _approve(a)
    _invoice(client, h, a)
    _db("UPDATE contractor_dispatches SET invoice_date='2026-10-09', invoice_no='DISP-INV' WHERE id=?", (did,))      # 直接改列（API 會擋）：模擬兩邊都有發票日
    ev = _events()
    assert len(_of(ev, "E04")) == 1 and _of(ev, "E04")[0]["source_type"] == "contractor_voucher_invoice"             # 只有一種層級
    _db("UPDATE contractor_payment_vouchers SET status='草稿' WHERE voucher_no=?", (a,))
    assert _void(client, h, a).status_code == 200
    ev = _events()
    assert len(_of(ev, "E04")) == 1 and _of(ev, "E04")[0]["source_type"] == "contractor_dispatch"                    # 反向控制：分期作廢 ⇒ 派發層回來


def _void(client, h, no):
    return client.post("/api/contractor-vouchers/%s/void" % no, headers=h, json={"reason": "測試"})


def test_rk11_legacy_whole_voucher_events_keep_their_shape(client, hs):
    h = hs["rki_admin"]
    did = _dispatch(total=1000, invoice_date="2026-10-03")
    no = client.post("/api/contractor-vouchers", headers=h, json={"dispatch_id": did}).json()["voucher_no"]
    _db("UPDATE contractor_payment_vouchers SET status='已核准', is_paid=1, paid_at='2026-10-10' WHERE voucher_no=?", (no,))
    ev = _events()
    e04 = _of(ev, "E04", source_type="contractor_dispatch")
    assert len(e04) == 1 and e04[0]["source_key"] == str(did) and e04[0]["doc_no"] == "DISP-INV"
    assert (_sum(e04[0], "COST_PROJECT", "D"), _sum(e04[0], "INPUT_TAX", "D"), _sum(e04[0], "AP", "C")) == (1000, 50, 1050)
    e05 = _of(ev, "E05", source_key=no)
    assert len(e05) == 1 and e05[0]["meta"] == {"dispatch_invoiced": True} and _sum(e05[0], "AP", "D") == 1050


def test_rk11_e05_meta_for_a_period_looks_at_its_own_invoice_date(client, hs):
    h = hs["rki_admin"]
    did = _dispatch()
    a = _create(client, h, did, kind="deposit", amount=300)
    b = _create(client, h, did, kind="progress", amount=400)
    _approve(a, b)
    _invoice(client, h, a)
    _db("UPDATE contractor_payment_vouchers SET is_paid=1, paid_at='2026-10-10' WHERE dispatch_id=?", (did,))
    ev = _events()
    assert _of(ev, "E05", source_key=a)[0]["meta"]["dispatch_invoiced"] is True
    assert _of(ev, "E05", source_key=b)[0]["meta"]["dispatch_invoiced"] is False
    from modules.subcontract import gl_events
    assert "沒有登錄發票日" in gl_events.gl_events("2026-01-01", "2026-12-31")["notice"]


def test_rk11_invoice_endpoint_rules(client, hs):
    h = hs["rki_admin"]
    did = _dispatch()
    a = _create(client, h, did, kind="deposit", amount=300)
    assert client.patch("/api/contractor-vouchers/%s/invoice" % a, headers=hs["rki_sales"], json={"invNo": "X", "invDate": "2026-10-05"}).status_code in (401, 403)
    assert _invoice(client, h, "PV-NOPE").status_code == 404
    assert _invoice(client, h, a, "X" * 41).status_code == 400
    assert _invoice(client, h, a, "AB-1", "not-a-date").status_code == 400
    r = _invoice(client, h, a, "AB-1", "2026-10-05")
    assert r.status_code == 200 and r.json()["invNo"] == "AB-1" and r.json()["invDate"] == "2026-10-05"
    got = client.get("/api/contractor-vouchers/%s" % a, headers=h).json()
    assert got["invNo"] == "AB-1" and got["invDate"] == "2026-10-05"
    row = _db("SELECT inv_no, inv_date, snapshot_json, pretax_amount FROM contractor_payment_vouchers WHERE voucher_no=?", (a,))[0]
    assert row["pretax_amount"] == 300 and json.loads(row["snapshot_json"])["totalAmount"] == 300                 # 不影響金額
    # 舊式整筆：發票在派發上
    did2 = _dispatch()
    legacy = client.post("/api/contractor-vouchers", headers=h, json={"dispatch_id": did2}).json()["voucher_no"]
    r = _invoice(client, h, legacy)
    assert r.status_code == 409 and "派發" in r.json()["detail"]
    # 作廢的不能登
    assert _void(client, h, a).status_code == 200
    assert _invoice(client, h, a).status_code == 409


def test_rk11_dispatch_level_and_installment_invoices_exclude_each_other(client, hs):
    h = hs["rki_admin"]
    d1 = _dispatch(invoice_date="2026-10-03")
    r = client.post("/api/contractor-vouchers", headers=h, json={"dispatch_id": d1, "kind": "deposit", "amount": 100})
    assert r.status_code == 409 and "整筆發票日" in r.json()["detail"]
    assert client.post("/api/contractor-vouchers/preview", headers=h, json={"dispatch_id": d1, "kind": "deposit", "amount": 100}).status_code == 409
    d2 = _dispatch()
    _create(client, h, d2, kind="deposit", amount=100)
    r = client.patch("/api/contractor-dispatches/%d/invoice-date" % d2, headers=h, json={"invoiceDate": "2026-10-03"})
    assert r.status_code == 409 and "各期" in r.json()["detail"]
    assert client.patch("/api/contractor-dispatches/%d/invoice-date" % d2, headers=h, json={"invoiceDate": ""}).status_code == 200      # 清除永遠可以
