# -*- coding: utf-8 -*-
"""31-B S2：分期（款別）匯款申請的建立與試算——`POST /api/contractor-vouchers`（帶 kind）、`POST /api/contractor-vouchers/preview`。
RK8：款別存在且啟用、派發狀態在該款別的可開立狀態內；金額規則走 `remit_split.plan`（比例或固定金額、最後一期補尾差與補稅差）；
分期與舊式整筆在同一派發互斥；前期只看未作廢的；試算不寫任何東西、與建立算出同一組數字；個人點工只掛最後一期；
舊式整筆申請（不帶 kind）的行為與回傳形狀不變。
反向控制：`previous_periods` 被換成永遠回空 ⇒ 第二張 70% 也放行（證明累計上限靠它，見 test_rk8_reverse_control_without_previous_periods_the_cap_is_gone）。"""
import json

import pytest

from modules.subcontract import remit_create as RC


_MAKE_USER_DEFAULT_ROLE = "superadmin"      # 第42班：財務／出納不再有 admin 直通；舊題的「預設 admin 操作者」改用 superadmin（見 conftest.make_user）


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture()
def hs(client, make_user):
    out = {}
    for name, role in (("rkc_sa", "superadmin"), ("rkc_admin", "superadmin"), ("rkc_sales", "sales")):
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


def _dispatch(status="accepted", total=100, rate=0.05, personnel=None, approval="", quote="MQ-RKC-1"):
    vid = (_db("SELECT id FROM vendor_contractors WHERE name='RKC廠商'") or [{}])[0].get("id")
    if not vid:
        _db("INSERT INTO vendor_contractors (name, tax_id, created_at, updated_at) VALUES ('RKC廠商','12345678','2026-10-01','2026-10-01')")
        vid = _db("SELECT id FROM vendor_contractors WHERE name='RKC廠商'")[0]["id"]
    _db("INSERT INTO contractor_dispatches (quote_no, vendor_id, status, total_amount, tax_rate, items_json, personnel_json, approval_status, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?, '2026-10-01', '2026-10-01')",
        (quote, vid, status, total, rate, json.dumps([{"description": "工項", "amount": total}], ensure_ascii=False),
         json.dumps(personnel or [], ensure_ascii=False), approval))
    return _db("SELECT MAX(id) AS i FROM contractor_dispatches")[0]["i"]


def _create(client, h, did, **kw):
    return client.post("/api/contractor-vouchers", headers=h, json=dict({"dispatch_id": did}, **kw))


def _row(no):
    return _db("SELECT * FROM contractor_payment_vouchers WHERE voucher_no=?", (no,))[0]


# ── 建立：三期 33／33／34（設計 §4 算例）──────────────────────────────────

def test_rk8_three_periods_via_the_api_match_the_worked_example_and_personnel_goes_to_the_last_period_only(client, hs):
    h = hs["rkc_admin"]
    person = [{"id": None, "name": "甲", "amount": 500}]
    did = _dispatch(status="accepted", total=100, rate=0.05, personnel=person)
    r1 = _create(client, h, did, kind="progress", ratio_percent=33.33)
    assert r1.status_code == 201, r1.text
    j1 = r1.json()
    assert j1["kind"] == "progress" and j1["kindName"] == "進度款" and j1["seq"] == 1
    assert j1["plan"]["pretax"] == 33 and j1["plan"]["tax"] == 2 and j1["plan"]["is_last"] is False
    r2 = _create(client, h, did, kind="progress", ratio_percent=33.33)
    r3 = _create(client, h, did, kind="progress", ratio_percent=33.34)
    assert r2.status_code == 201 and r3.status_code == 201, (r2.text, r3.text)
    assert r3.json()["plan"]["pretax"] == 34 and r3.json()["plan"]["tax"] == 1 and r3.json()["plan"]["is_last"] is True and r3.json()["plan"]["make_up"] == -1
    assert any("補差" in w for w in r3.json()["warnings"])
    rows = [_row(x.json()["voucher_no"]) for x in (r1, r2, r3)]
    assert [x["pretax_amount"] for x in rows] == [33, 33, 34] and [x["seq"] for x in rows] == [1, 2, 3] and all(x["kind"] == "progress" for x in rows)
    assert [x["kinds_version"] for x in rows] == [0, 0, 0] and rows[0]["ratio"] == pytest.approx(0.3333)
    snaps = [json.loads(x["snapshot_json"]) for x in rows]
    assert [s["taxAmount"] for s in snaps] == [2, 2, 1] and sum(s["taxAmount"] for s in snaps) == 5          # Σ稅額＝整筆稅額
    assert [s["personnelTotal"] for s in snaps] == [0, 0, 500] and snaps[0]["personnel"] == [] and len(snaps[2]["personnel"]) == 1
    assert [s["grandTotal"] for s in snaps] == [35, 35, 535] and snaps[2]["isLastPeriod"] and snaps[2]["makeUp"] == -1 and snaps[2]["dispatchTotal"] == 100
    pub = client.get("/api/contractor-vouchers/%s" % r1.json()["voucher_no"], headers=h).json()
    assert pub["kind"] == "progress" and pub["kindName"] == "進度款" and pub["seq"] == 1 and pub["pretaxAmount"] == 33 and pub["grandTotal"] == 35
    # 全部申請完了 ⇒ 不能再開
    again = _create(client, h, did, kind="progress", amount=1)
    assert again.status_code == 400 and "已經全部申請完" in again.json()["detail"]


def test_rk8_fixed_amount_mode_and_mixed_modes(client, hs):
    h = hs["rkc_admin"]
    did = _dispatch(status="confirmed", total=1000)
    d = _create(client, h, did, kind="deposit", amount=300)                                     # 已確認就能開訂金款（舊規則做不到）
    assert d.status_code == 201 and d.json()["plan"]["pretax"] == 300 and d.json()["plan"]["tax"] == 15
    p = _create(client, h, did, kind="progress", ratio_percent=30)
    assert p.status_code == 201 and p.json()["plan"]["pretax"] == 300 and p.json()["plan"]["is_last"] is False
    assert _row(p.json()["voucher_no"])["ratio"] == pytest.approx(0.3) and _row(d.json()["voucher_no"])["ratio"] is None
    over = _create(client, h, did, kind="progress", amount=401)
    assert over.status_code == 400 and "超過剩餘額度 400" in over.json()["detail"]
    c = _create(client, h, did, kind="progress", amount=400)                                    # 剛好等於剩餘額 ⇒ 最後一期
    assert c.status_code == 201 and c.json()["plan"]["is_last"] is True and c.json()["seq"] == 2


# ── 試算＝建立 ───────────────────────────────────────────────────────────

def test_rk8_preview_writes_nothing_and_returns_exactly_what_create_will_store(client, hs):
    h = hs["rkc_admin"]
    did = _dispatch(status="accepted", total=100000)
    n0 = _db("SELECT COUNT(*) AS n FROM contractor_payment_vouchers")[0]["n"]
    pv = client.post("/api/contractor-vouchers/preview", headers=h, json={"dispatch_id": did, "kind": "deposit", "ratio_percent": 30})
    assert pv.status_code == 200, pv.text
    j = pv.json()
    assert j["plan"]["pretax"] == 30000 and j["plan"]["tax"] == 1500 and j["kindName"] == "訂金款" and j["seq"] == 1 and j["previous"] == [] and j["dispatchTotal"] == 100000
    assert _db("SELECT COUNT(*) AS n FROM contractor_payment_vouchers")[0]["n"] == n0                            # 沒寫任何東西
    cr = _create(client, h, did, kind="deposit", ratio_percent=30)
    assert cr.json()["plan"] == j["plan"] and cr.json()["seq"] == j["seq"]                                         # 同一組數字
    pv2 = client.post("/api/contractor-vouchers/preview", headers=h, json={"dispatch_id": did, "kind": "progress", "ratio_percent": 30}).json()
    assert pv2["previous"][0]["voucherNo"] == cr.json()["voucher_no"] and pv2["previous"][0]["pretax"] == 30000 and pv2["plan"]["remaining_before"] == 70000


# ── 款別／狀態驗證 ───────────────────────────────────────────────────────

def test_rk8_kind_and_dispatch_status_rules(client, hs):
    h = hs["rkc_admin"]
    sent = _dispatch(status="sent", total=1000)
    r = _create(client, h, sent, kind="completion", amount=100)
    assert r.status_code == 409 and "已送出" in r.json()["detail"] and "已驗收" in r.json()["detail"]
    assert _create(client, h, sent, kind="deposit", amount=100).status_code == 409                # 訂金款最早要已確認
    done = _dispatch(status="completed", total=1000)
    assert _create(client, h, done, kind="progress", amount=100).status_code == 409                # 進度款到已驗收為止
    assert _create(client, h, done, kind="acceptance", amount=100).status_code == 201
    cancelled = _dispatch(status="cancelled", total=1000)
    assert _create(client, h, cancelled, kind="deposit", amount=100).status_code == 409
    ok = _dispatch(status="accepted", total=1000)
    assert _create(client, h, ok, kind="nope", amount=100).status_code == 400                      # 沒有這個款別
    assert _create(client, h, ok, kind="deposit").status_code == 400                               # 比例與金額都沒給
    assert _create(client, h, ok, kind="deposit", amount=100, ratio_percent=10).status_code == 400   # 兩個都給
    assert _create(client, h, ok, kind="deposit", ratio_percent=0).status_code == 400
    assert _create(client, h, ok, kind="deposit", amount=0).status_code == 400
    pend = _dispatch(status="accepted", total=1000, approval="待審核")
    assert _create(client, h, pend, kind="deposit", amount=100).status_code == 409                   # 31-A 審核未核准不能請款
    assert client.post("/api/contractor-vouchers/preview", headers=h, json={"dispatch_id": pend, "kind": "deposit", "amount": 100}).status_code == 409


def test_rk8_deactivated_kind_and_company_changes_apply_only_to_new_vouchers_with_the_version_recorded(client, hs):
    sa, ad = hs["rkc_sa"], hs["rkc_admin"]
    did = _dispatch(status="accepted", total=1000)
    first = _create(client, ad, did, kind="deposit", amount=100)
    assert first.status_code == 201 and _row(first.json()["voucher_no"])["kinds_version"] == 0
    from modules.subcontract import remit_kinds as RK
    body = RK.default_body()
    body["kinds"][0].update(active=False)                                                         # 停用訂金款
    body["kinds"][2]["name"] = "完工尾款"
    assert client.put("/api/definitions/remit_kinds/default/draft", json={"body": body}, headers=sa).status_code == 200
    assert client.post("/api/definitions/remit_kinds/default/publish", json={"note": "停用訂金"}, headers=sa).status_code in (200, 201)
    blocked = _create(client, ad, did, kind="deposit", amount=100)
    assert blocked.status_code == 409 and "已停用" in blocked.json()["detail"]
    ok = _create(client, ad, did, kind="completion", amount=100)
    assert ok.status_code == 201 and ok.json()["kindName"] == "完工尾款" and _row(ok.json()["voucher_no"])["kinds_version"] == 1
    assert _row(first.json()["voucher_no"])["kind_name"] == "訂金款"                              # 舊申請的名稱快照不變
    assert client.get("/api/contractor-vouchers/%s" % first.json()["voucher_no"], headers=ad).json()["kindName"] == "訂金款"


# ── 互斥、作廢、舊行為不變 ───────────────────────────────────────────────

def test_rk8_legacy_whole_amount_and_installments_exclude_each_other_and_legacy_shape_is_unchanged(client, hs):
    h = hs["rkc_admin"]
    a = _dispatch(status="accepted", total=1000)
    leg = _create(client, h, a)                                                                   # 舊式：不帶 kind
    assert leg.status_code == 201 and set(leg.json()) == {"voucher_no", "created_at"}              # 回傳形狀不變
    row = _row(leg.json()["voucher_no"])
    assert row["kind"] == "" and row["seq"] == 0 and row["pretax_amount"] is None
    k = _create(client, h, a, kind="completion", amount=100)
    assert k.status_code == 409 and "整筆方式" in k.json()["detail"]
    assert _create(client, h, a).status_code == 409                                                 # 舊式第二張仍擋
    b = _dispatch(status="accepted", total=1000)
    assert _create(client, h, b, kind="completion", amount=100).status_code == 201
    r = _create(client, h, b)
    assert r.status_code == 409 and "分期" in r.json()["detail"]


def test_rk8_voided_periods_do_not_count_and_the_sequence_is_not_reused(client, hs):
    h = hs["rkc_admin"]
    did = _dispatch(status="accepted", total=1000)
    p1 = _create(client, h, did, kind="progress", amount=600).json()
    _db("UPDATE contractor_payment_vouchers SET voided_at='2026-10-02T00:00:00' WHERE voucher_no=?", (p1["voucher_no"],))
    p2 = _create(client, h, did, kind="progress", amount=1000)                                      # 作廢的不佔額度
    assert p2.status_code == 201 and p2.json()["plan"]["is_last"] is True and p2.json()["seq"] == 2     # 序號不回頭重用


def test_rk8_reverse_control_without_previous_periods_the_cap_is_gone(client, hs, monkeypatch):
    h = hs["rkc_admin"]
    did = _dispatch(status="accepted", total=1000)
    assert _create(client, h, did, kind="progress", amount=700).status_code == 201
    assert _create(client, h, did, kind="progress", amount=700).status_code == 400                   # 正常：超過剩餘額度
    monkeypatch.setattr(RC, "previous_periods", lambda conn, dispatch_id: [])
    assert _create(client, h, did, kind="progress", amount=700).status_code in (201, 500)            # 偵測器壞了 ⇒ 放行（或撞唯一索引）⇒ 上一行確實在靠它


def test_rk8_permissions(client, hs):
    did = _dispatch(status="accepted", total=1000)
    assert _create(client, hs["rkc_sales"], did, kind="deposit", amount=10).status_code == 403
    assert client.post("/api/contractor-vouchers/preview", headers=hs["rkc_sales"], json={"dispatch_id": did, "kind": "deposit", "amount": 10}).status_code == 403
    assert client.post("/api/contractor-vouchers/preview", json={"dispatch_id": did, "kind": "deposit", "amount": 10}).status_code == 401
    assert _create(client, hs["rkc_sa"], did, kind="deposit", amount=10).status_code == 201
    assert client.post("/api/contractor-vouchers/preview", headers=hs["rkc_admin"], json={"dispatch_id": 99999, "kind": "deposit", "amount": 10}).status_code == 404


def test_rk8_cents_in_dispatch_total_are_rounded_half_up_to_whole_yuan_with_a_warning(client, hs):
    did = _dispatch(status="accepted", total=1000.5)
    r = _create(client, hs["rkc_admin"], did, kind="deposit", amount=100)
    assert r.status_code == 201, r.text
    assert any("含角分" in w and "1001" in w for w in r.json().get("warnings", []))
    r2 = client.post("/api/contractor-vouchers/preview", headers=hs["rkc_admin"], json={"dispatch_id": did, "kind": "progress", "amount": 901})
    assert r2.status_code == 200 and r2.json()["plan"]["is_last"] is True          # 剩餘額度以 1001 計：100＋901 補齊
