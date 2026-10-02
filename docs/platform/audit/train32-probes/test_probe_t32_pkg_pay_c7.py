# -*- coding: utf-8 -*-
"""第 32 包稽核（c7）獨立探針：材料申請匯款——手續費>500 進差額審核、完整帳號端點角色、差額審核項目的內容。
斷言是「應該怎樣」；印出實測值供報告引用。重用作者的 world／helper。不隨產品出貨。"""
import pytest

from tests._requires import skip_module_unless

skip_module_unless("case", "本檔全部是 M01 的材料申請匯款")

from modules.case.tests.test_material_payment_api_2026_10_02 import (  # noqa: E402,F401
    ACCT, ITEM, NO, _approved, _create, _flow, _login, _q, _x, world)

PAY = "/api/cashier/pending-payables/case_material/%d/pay"


def _pay(client, w, pid, amount, fee=None, date="2031-03-05"):
    body = {"paidDate": date, "actualAmount": amount}
    if fee is not None:
        body.update(hasFee=True, fee=fee)
    return client.post(PAY % pid, json=body, headers=w["cash"])


def _lines():
    return [dict(r) for r in _q("SELECT amount, fee, remit_review FROM case_material_payment_lines ORDER BY id")]


@pytest.mark.parametrize("fee, want_review", [(500, ""), (500.01, "pending"), (501, "pending"), (0, "")])
def test_fee_over_500_goes_to_review_boundary(client, world, fee, want_review):
    w = world
    pid = _approved(client, w, 6000)
    r = _pay(client, w, pid, 2000, fee if fee else None)
    ln = _lines()
    print("fee=%s -> %s %s" % (fee, r.status_code, ln))
    assert r.status_code == 200 and ln[-1]["remit_review"] == want_review


def test_fee_review_item_shows_what_the_approver_needs(client, world):
    """差額審核表（cashier.html）有 手續費／付款日 兩欄；手續費偏高的覆核項目必須帶這兩個值。"""
    w = world
    pid = _approved(client, w, 6000)
    assert _pay(client, w, pid, 2000, 600).status_code == 200
    r = client.get("/api/cashier/remit-reviews", headers=w["adm"])
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    print("remit-review items:", items)
    assert len(items) == 1
    it = items[0]
    assert it["diff"] == 0 and "手續費" in (it.get("reason") or "")
    assert it.get("fee") == 600, "差額審核表有「手續費」欄，項目沒帶 fee：%r" % (it.get("fee"),)
    assert it.get("paidAt"), "差額審核表有「付款日」欄，項目沒帶 paidAt：%r" % (it.get("paidAt"),)


def test_overpay_review_item_also_keeps_fee_and_paidat(client, world):
    w = world
    pid = _approved(client, w, 6000)
    assert _pay(client, w, pid, 7000, 10).status_code == 200                                    # 多付 1,000 ＋ 手續費 10
    it = client.get("/api/cashier/remit-reviews", headers=w["adm"]).json()["items"][0]
    print("overpay item:", it)
    assert it["diff"] == 1000 and it.get("fee") == 10 and it.get("paidAt")


def test_fee_review_can_be_decided_and_clears_the_queue(client, world):
    w = world
    pid = _approved(client, w, 6000)
    assert _pay(client, w, pid, 2000, 600).status_code == 200
    it = client.get("/api/cashier/remit-reviews", headers=w["adm"]).json()["items"][0]
    r = client.post("/api/cashier/remit-reviews/%s/%s/decision" % (it["source"], it["key"]), json={"decision": "approve", "note": "ok"}, headers=w["adm"])
    print("decision:", r.status_code, r.text[:200])
    assert r.status_code == 200
    assert client.get("/api/cashier/remit-reviews", headers=w["adm"]).json()["items"] == []
    assert _lines()[-1]["remit_review"] == "approved"


def test_fee_cannot_exceed_actual_and_negative_fee_rejected(client, world):
    w = world
    pid = _approved(client, w, 6000)
    for fee in (2001, -1, 1e12):
        r = _pay(client, w, pid, 2000, fee)
        print("fee=%s -> %s" % (fee, r.status_code))
        assert r.status_code == 400
    assert _lines() == []


def test_payee_bank_full_account_only_for_superadmin_and_cashier_module(client, world):
    w = world
    pid = _approved(client, w, 6000)
    res = {}
    for who in ("sa", "adm", "adm2", "cash", "boss", "eng", "out"):
        r = client.get("/api/cashier/pending-payables/case_material/%d/payee-bank" % pid, headers=w[who])
        res[who] = (r.status_code, (r.json().get("account") if r.status_code == 200 else None))
    print("payee-bank:", res)
    assert res["sa"][1] == ACCT and res["cash"][1] == ACCT
    for who in ("adm", "adm2"):
        assert res[who][0] == 200 and res[who][1] != ACCT and res[who][1].startswith("****"), (who, res[who])
    assert all(res[x][0] in (403, 404) for x in ("boss", "eng", "out"))


def test_admin_who_also_has_the_cashier_module_is_still_masked(client, world, make_user):
    """程式註解：admin 的角色樣板含 cashier 模組，所以明確排除——實測：給 admin 明確勾 cashier 模組仍遮罩。"""
    w = world
    pid = _approved(client, w, 6000)
    u, p = make_user(username="mpa_adm_c", role="admin", modules=["cashier"])
    h = _login(client, u, p)
    r = client.get("/api/cashier/pending-payables/case_material/%d/payee-bank" % pid, headers=h)
    print("admin+cashier:", r.status_code, r.json().get("account"))
    assert r.status_code == 200 and r.json()["account"].startswith("****")


def test_masked_view_is_audited_as_masked_and_full_view_is_not_flagged(client, world):
    w = world
    pid = _approved(client, w, 6000)
    client.get("/api/cashier/pending-payables/case_material/%d/payee-bank" % pid, headers=w["adm"])
    client.get("/api/cashier/pending-payables/case_material/%d/payee-bank" % pid, headers=w["cash"])
    rows = [r["target_label"] for r in _q("SELECT target_label FROM audit_log WHERE action='cashier.payee_bank_view' ORDER BY id")]
    print(rows)
    assert len(rows) == 2 and "遮罩" in rows[0] and "遮罩" not in rows[1]
    assert not [r for r in rows if ACCT in r]
