# -*- coding: utf-8 -*-
"""31-B S2b：分期匯款申請作廢——`POST /api/contractor-vouchers/{no}/void`（後進先出）。
RK9：admin＋、必填原因；只能作廢該派發最新一張未作廢的分期申請；已付款先撤銷付款；舊式整筆不能走作廢；
作廢後狀態＝已作廢、不佔額度（可重開最後一期）、序號不回頭重用、不進待付款；分期草稿刪除也守後進先出。
反向控制：`void_blocker` 被換成永遠放行 ⇒ 中間一期也能作廢（證明順序規則靠它）。"""
import json

import pytest

from modules.subcontract import remit_create as RC


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture()
def hs(client, make_user):
    out = {}
    for name, role in (("rkv_admin", "admin"), ("rkv_sales", "sales")):
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


def _dispatch(total=1000):
    vid = (_db("SELECT id FROM vendor_contractors WHERE name='RKV廠商'") or [{}])[0].get("id")
    if not vid:
        _db("INSERT INTO vendor_contractors (name, tax_id, created_at, updated_at) VALUES ('RKV廠商','12345678','2026-10-01','2026-10-01')")
        vid = _db("SELECT id FROM vendor_contractors WHERE name='RKV廠商'")[0]["id"]
    _db("INSERT INTO contractor_dispatches (quote_no, vendor_id, status, total_amount, tax_rate, items_json, personnel_json, approval_status, created_at, updated_at)"
        " VALUES ('MQ-RKV-1',?,'accepted',?,0.05,?,'[]','', '2026-10-01','2026-10-01')",
        (vid, total, json.dumps([{"description": "工項", "amount": total}], ensure_ascii=False)))
    return _db("SELECT MAX(id) AS i FROM contractor_dispatches")[0]["i"]


def _create(client, h, did, **kw):
    r = client.post("/api/contractor-vouchers", headers=h, json=dict({"dispatch_id": did}, **kw))
    assert r.status_code == 201, r.text
    return r.json()["voucher_no"]


def _void(client, h, no, reason="測試作廢"):
    return client.post("/api/contractor-vouchers/%s/void" % no, headers=h, json={"reason": reason})


def _row(no):
    return _db("SELECT * FROM contractor_payment_vouchers WHERE voucher_no=?", (no,))[0]


def _open_count(did):
    return _db("SELECT COUNT(*) AS n FROM contractor_payment_vouchers WHERE dispatch_id=? AND voided_at=''", (did,))[0]["n"]


def test_rk9_only_the_latest_open_period_can_be_voided_then_the_one_before(client, hs):
    h = hs["rkv_admin"]
    did = _dispatch()
    a = _create(client, h, did, kind="deposit", amount=300)
    b = _create(client, h, did, kind="progress", amount=400)
    r = _void(client, h, a)
    assert r.status_code == 409 and b in r.json()["detail"] and _row(a)["voided_at"] == ""
    assert _void(client, h, b).status_code == 200
    row = _row(b)
    assert row["status"] == "已作廢" and row["voided_at"] and row["voided_by"] == "rkv_admin" and row["void_reason"] == "測試作廢"
    assert _void(client, h, a).status_code == 200                                    # b 作廢後 a 成了最新一張
    assert _void(client, h, a).status_code == 409                                    # 已作廢不能再作廢


def test_rk9_voided_period_frees_the_quota_and_the_sequence_moves_on(client, hs):
    h = hs["rkv_admin"]
    did = _dispatch(total=1000)
    a = _create(client, h, did, kind="progress", amount=600)
    assert _void(client, h, a).status_code == 200
    r = client.post("/api/contractor-vouchers", headers=h, json={"dispatch_id": did, "kind": "progress", "amount": 1000})
    assert r.status_code == 201 and r.json()["seq"] == 2 and r.json()["plan"]["is_last"] is True
    voided = client.get("/api/contractor-vouchers/%s" % a, headers=h).json()
    assert voided["voidedAt"] and voided["voidReason"] == "測試作廢"


def test_rk9_reason_required_permission_paid_and_legacy_rules(client, hs):
    h = hs["rkv_admin"]
    did = _dispatch()
    a = _create(client, h, did, kind="deposit", amount=300)
    assert _void(client, h, a, reason="  ").status_code == 400
    assert _void(client, hs["rkv_sales"], a).status_code in (401, 403)
    assert _void(client, h, "PV-NOPE").status_code == 404
    _db("UPDATE contractor_payment_vouchers SET is_paid=1 WHERE voucher_no=?", (a,))
    r = _void(client, h, a)
    assert r.status_code == 409 and "撤銷付款" in r.json()["detail"]
    _db("UPDATE contractor_payment_vouchers SET is_paid=0 WHERE voucher_no=?", (a,))
    did2 = _dispatch()
    legacy = client.post("/api/contractor-vouchers", headers=h, json={"dispatch_id": did2}).json()["voucher_no"]
    r = _void(client, h, legacy)
    assert r.status_code == 409 and "舊式" in r.json()["detail"] and _row(legacy)["voided_at"] == ""


def test_rk9_voided_period_is_not_payable_or_submittable(client, hs):
    h = hs["rkv_admin"]
    did = _dispatch()
    a = _create(client, h, did, kind="deposit", amount=300)
    _db("UPDATE contractor_payment_vouchers SET status='已核准' WHERE voucher_no=?", (a,))
    assert _void(client, h, a).status_code == 200
    assert not _db("SELECT 1 FROM contractor_payment_vouchers WHERE status='已核准' AND is_paid=0 AND voucher_no=?", (a,))   # 待付款清單（cashier）靠 status 過濾
    assert client.post("/api/contractor-vouchers/%s/submit" % a, headers=h).status_code == 409


def test_rk9_draft_delete_also_follows_last_in_first_out(client, hs):
    h = hs["rkv_admin"]
    did = _dispatch()
    a = _create(client, h, did, kind="deposit", amount=300)
    b = _create(client, h, did, kind="progress", amount=400)
    assert client.delete("/api/contractor-vouchers/%s" % a, headers=h).status_code == 409
    assert client.delete("/api/contractor-vouchers/%s" % b, headers=h).status_code == 200
    assert client.delete("/api/contractor-vouchers/%s" % a, headers=h).status_code == 200


def test_rk9_dispatch_with_only_voided_periods_has_no_open_voucher_left_for_the_edit_guards(client, hs):
    h = hs["rkv_admin"]
    did = _dispatch()
    a = _create(client, h, did, kind="deposit", amount=300)
    assert _open_count(did) == 1
    assert _void(client, h, a).status_code == 200
    assert _open_count(did) == 0


def test_rk9_reverse_control_without_the_blocker_a_middle_period_can_be_voided(client, hs, monkeypatch):
    h = hs["rkv_admin"]
    did = _dispatch()
    a = _create(client, h, did, kind="deposit", amount=300)
    _create(client, h, did, kind="progress", amount=400)
    assert _void(client, h, a).status_code == 409
    monkeypatch.setattr(RC, "void_blocker", lambda conn, row: None)
    assert _void(client, h, a).status_code == 200                                    # 偵測器拿掉 ⇒ 順序規則消失 ⇒ 上面的 409 確實是它擋的
