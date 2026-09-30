# -*- coding: utf-8 -*-
"""費用單據 A2-3：出納付款段（IP-100 `case` 提供者擴充）。

驗：採購單登錄付款必須有匯款日＋付款條件（缺 ⇒ 400、狀態不變）；零用金支付單必須選付款方式；其他類型預設轉帳；請購單不進出納、硬打付款 ⇒ 409；
付款後 pay_method／pay_account_code／pay_terms／remit_date／paid_by 落地；收款人銀行資料只有能付款的人看得到（清單只給遮罩、完整資料走專用端點
且每次留稽核、稽核不含帳號）；銀行資料表提供者（`payee.bank_profile`）優先於單據手填；舊版（kind=''）付款行為不變。"""
import json

import pytest

SENT = "/api/quotations/-/extra-expenses"


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _q(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _no_tiers():
    import db
    c = db.get_db()
    try:
        c.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                  ("unified_approval_flow", json.dumps({"tiers": [], "includeSubmitterManagerTier": False}), "2026-01-01T00:00:00"))
        c.commit()
    finally:
        c.close()


@pytest.fixture
def H(client, make_user):
    out = {}
    for u, role, mods in (("po_form", "sales", ["expense_forms"]), ("po_cash", "engineer", ["cashier"]), ("po_fin", "engineer", ["finance"])):
        name, pw = make_user(username=u, role=role, modules=mods)
        out[u] = _login(client, name, pw)
    return out


def _approved(client, h, kind="purchase_order", **extra):
    body = {"kind": kind, "lines": [{"category": "其他", "summary": "測試品", "amount": 1000}], "data": {"applicant": "po_form"}, **extra}
    r = client.post(SENT, headers=h, json=body)
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    _no_tiers()
    assert client.post("%s/%d/submit" % (SENT, eid), headers=h).json()["status"] == "已核准"
    return eid


def _pay(client, h, eid, **body):
    return client.post("/api/cashier/pending-payables/case/%d/pay" % eid, headers=h, json={"paidDate": "2026-10-01", **body})


def _row(eid):
    return _q("SELECT * FROM case_extra_expenses WHERE id=?", (eid,))[0]


def test_purchase_order_needs_remit_date_and_pay_terms(client, H):
    eid = _approved(client, H["po_form"])
    for body in ({}, {"payTerms": "月結 30 天"}, {"remitDate": "2026-10-05"}):
        r = _pay(client, H["po_cash"], eid, **body)
        assert r.status_code == 400, (body, r.status_code, r.text)
        assert _row(eid)["paid_date"] in ("", None)                                   # 狀態不變
    assert _pay(client, H["po_cash"], eid, payTerms="月結 30 天", remitDate="2026-10-05").status_code == 200
    row = _row(eid)
    assert (row["paid_date"], row["pay_terms"], row["remit_date"], row["pay_method"], row["paid_by"]) == ("2026-10-01", "月結 30 天", "2026-10-05", "transfer", "po_cash")
    assert _pay(client, H["po_cash"], eid, payTerms="x", remitDate="2026-10-05").status_code == 409        # 不可重複付款
    bad = _approved(client, H["po_form"])
    assert _pay(client, H["po_cash"], bad, payTerms="x", remitDate="2026-13-45").status_code == 400      # 匯款日要是有效日期


def test_terms_and_remit_date_filled_earlier_are_reused(client, H):
    eid = _approved(client, H["po_form"])
    import db
    c = db.get_db()
    try:
        c.execute("UPDATE case_extra_expenses SET pay_terms='貨到付款', remit_date='2026-10-03' WHERE id=?", (eid,))
        c.commit()
    finally:
        c.close()
    assert _pay(client, H["po_cash"], eid).status_code == 200
    assert (_row(eid)["pay_terms"], _row(eid)["remit_date"]) == ("貨到付款", "2026-10-03")


def test_petty_cash_needs_a_pay_method_and_others_default_to_transfer(client, H):
    pc = _approved(client, H["po_form"], kind="petty_cash")
    assert _pay(client, H["po_cash"], pc).status_code == 400
    assert _pay(client, H["po_cash"], pc, payMethod="credit").status_code == 400
    assert _row(pc)["paid_date"] in ("", None)
    assert _pay(client, H["po_cash"], pc, payMethod="petty_cash", payAccountCode="").status_code == 200
    assert _row(pc)["pay_method"] == "petty_cash"
    tv = _approved(client, H["po_form"], kind="travel")
    assert _pay(client, H["po_cash"], tv).status_code == 200 and _row(tv)["pay_method"] == "transfer"
    tv2 = _approved(client, H["po_form"], kind="travel")
    assert _pay(client, H["po_cash"], tv2, payMethod="cash").status_code == 200 and _row(tv2)["pay_method"] == "cash"


def test_purchase_req_is_not_in_cashier_and_cannot_be_paid(client, H):
    rq = _approved(client, H["po_form"], kind="purchase_req")
    assert str(rq) not in {i["key"] for i in client.get("/api/cashier/pending-payables", headers=H["po_cash"]).json()["items"]}
    r = _pay(client, H["po_cash"], rq)
    assert r.status_code == 409 and "核准文件" in r.json()["detail"] and _row(rq)["paid_date"] in ("", None)


def test_non_cashier_cannot_pay_or_read_bank(client, H):
    eid = _approved(client, H["po_form"], kind="travel", payeeType="employee", payeeName="王小明", payeeBank="玉山", payeeAccount="1234567890123")
    assert _pay(client, H["po_form"], eid).status_code == 403
    assert _pay(client, H["po_fin"], eid).status_code == 403                                        # 財務可看不可付
    for who in ("po_form", "po_fin"):
        assert client.get("/api/cashier/pending-payables/case/%d/payee-bank" % eid, headers=H[who]).status_code == 403
    assert _row(eid)["paid_date"] in ("", None)


def test_bank_data_masked_in_list_full_only_via_cashier_endpoint_and_audited(client, H):
    eid = _approved(client, H["po_form"], kind="travel", payeeType="employee", payeeName="王小明", payeeBank="玉山", payeeAccount="1234567890123")
    for who in ("po_cash", "po_fin"):
        items = {i["key"]: i for i in client.get("/api/cashier/pending-payables", headers=H[who]).json()["items"]}
        if str(eid) in items:
            assert items[str(eid)]["payeeBank"] == "玉山 ****0123" and "1234567890123" not in json.dumps(items[str(eid)], ensure_ascii=False)
    r = client.get("/api/cashier/pending-payables/case/%d/payee-bank" % eid, headers=H["po_cash"])
    assert r.status_code == 200 and r.json()["source"] == "form" and r.json()["account"] == "1234567890123" and r.json()["bank"] == "玉山"
    rows = _q("SELECT action, detail FROM audit_log WHERE action='cashier.payee_bank_view'")
    assert rows and all("1234567890123" not in (x["detail"] or "") and "1234567890123" not in json.dumps(x, ensure_ascii=False) for x in rows)
    assert client.get("/api/cashier/pending-payables/case/999999/payee-bank", headers=H["po_cash"]).status_code == 404


def test_profile_provider_wins_over_form_and_absent_says_so(client, H, monkeypatch):
    from core import registry
    eid = _approved(client, H["po_form"], kind="travel", payeeType="employee", payeeName="王小明")
    r = client.get("/api/cashier/pending-payables/case/%d/payee-bank" % eid, headers=H["po_cash"])
    assert r.json()["source"] == "none" and "尚未登錄" in r.json()["notice"]                      # 沒提供者也沒手填 ⇒ 明說
    seen = {}

    def fake(conn, username, viewer):
        seen["args"] = (username, viewer.get("username"))
        return {"bank": "台新", "account": "000111222333", "accountName": "王小明"}
    real = registry.single_provider
    monkeypatch.setattr(registry, "single_provider", lambda name, *a, **k: fake if name == "payee.bank_profile" else real(name, *a, **k))
    r = client.get("/api/cashier/pending-payables/case/%d/payee-bank" % eid, headers=H["po_cash"])
    assert r.json()["source"] == "profile" and r.json()["account"] == "000111222333" and seen["args"] == ("po_form", "po_cash")


def test_legacy_rows_pay_as_before(client, H, seed_extra_expense):
    import db
    c = db.get_db()
    try:
        c.execute("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag)"
                  " VALUES ('MQ-PO-LEG','已送出','c','p',1,1,'{}','2026-01-01','2026-01-01','已成案')")
        c.commit()
    finally:
        c.close()
    eid = seed_extra_expense("MQ-PO-LEG", total_cost=300, category="運費", description="舊", expense_date="2026-09-10")
    assert _pay(client, H["po_cash"], eid).status_code == 200
    row = _row(eid)
    assert row["paid_date"] == "2026-10-01" and row["pay_method"] == "transfer" and row["kind"] == ""
