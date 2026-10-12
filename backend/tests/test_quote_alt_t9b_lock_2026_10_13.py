# -*- coding: utf-8 -*-
"""M3 T9b（T57）：已回簽擇一單的鎖定（P1）、解鎖修改（P4）、移出『已送出』（P3）。
純函式題不碰資料庫；端點題建單會觸發自動 PDF（Edge）——閘門才跑。"""
import json

import pytest
from fastapi import HTTPException

import db
from modules.case import alt_lock, alt_policy, alt_sign


def _it(id_, qty, price, cost, group=None, **kw):
    d = {"id": id_, "qty": qty, "unitPrice": price, "cost": cost, "amount": qty * price, "description": "品" + id_, "unit": "式", "notes": ""}
    if group is not None:
        d["altGroup"] = group
    d.update(kw)
    return d


def _body(**kw):
    d = {"customerName": "客", "projectName": "案", "quoteDate": "2026-10-13", "validDays": 30, "taxRate": 5, "totalsByAlt": True,
         "paymentTerms": "月結", "afterSales": "保固一年", "discount": 0, "freight": 0,
         "items": [_it("a", 1, 1000, 600), _it("x1", 1, 3000, 2000, "投影機"), _it("x2", 1, 5000, 3500, "投影機")],
         "tot": {"total": 1}, "approval": {"status": "approved"}, "caseRecord": {"x": 1}}
    d.update(kw)
    return d


def _copy(d):
    return json.loads(json.dumps(d))


# --- alt_lock.changed ------------------------------------------------------------------------

def test_unchanged_body_has_no_diff_even_with_derived_noise():
    old = _body()
    new = _copy(old)
    new["items"][0]["amount"] = 999999             # 衍生值不比對
    new["tot"] = {"total": 777}                    # 流程／衍生鍵不比對
    new["approval"] = {"status": "x"}
    new["items"][1]["unitPrice"] = 3000.0          # 數值相同
    new["items"][2]["brand"] = ""                  # 空值＝缺鍵
    assert alt_lock.changed(new, old, 1) == [] and alt_lock.changed(new, old, 2) == []


@pytest.mark.parametrize("mut,key", [
    (lambda d: d["items"][0].update(qty=2), "items"),
    (lambda d: d["items"][1].update(unitPrice=3001), "items"),
    (lambda d: d["items"][1].update(cost=1), "items"),
    (lambda d: d["items"][1].update(altGroup="別組"), "items"),
    (lambda d: d["items"].pop(), "items"),
    (lambda d: d["items"].append(_it("n", 1, 1, 1)), "items"),
    (lambda d: d.update(discount=100), "discount"),
    (lambda d: d.update(freight=1), "freight"),
    (lambda d: d.update(taxRate=0), "taxRate"),
    (lambda d: d.update(totalsByAlt=False), "totalsByAlt"),
])
def test_money_and_structure_edits_are_caught_in_both_scopes(mut, key):
    old = _body()
    new = _copy(old)
    mut(new)
    assert key in alt_lock.changed(new, old, 1) and key in alt_lock.changed(new, old, 2)


def test_scope_two_lets_notes_and_terms_through_scope_one_does_not():
    old = _body()
    new = _copy(old)
    new["afterSales"] = "保固兩年"
    new["paymentTerms"] = "現金"
    new["items"][0]["notes"] = "加註"
    assert alt_lock.changed(new, old, 2) == []
    assert set(alt_lock.changed(new, old, 1)) == {"afterSales", "paymentTerms", "items"}


def test_scope_one_catches_unknown_new_body_key_fail_closed_scope_two_ignores_it():
    old = _body()
    new = _copy(old)
    new["someNewBodyKey"] = "x"
    assert alt_lock.changed(new, old, 1) == ["someNewBodyKey"]
    assert alt_lock.changed(new, old, 2) == []
    new["someNewBodyKey"] = ""                       # 空值不算改
    assert alt_lock.changed(new, old, 1) == []


def test_unknown_scope_value_is_treated_as_scope_one():
    old = _body()
    new = _copy(old)
    new["afterSales"] = "x"
    assert alt_lock.changed(new, old, 99) == ["afterSales"]


def test_process_keys_are_never_compared():
    old = _body()
    new = _copy(old)
    for k in alt_lock.PROCESS_KEYS:
        new[k] = "改了"
    assert alt_lock.changed(new, old, 1) == []


def test_body_catalogue_is_subset_of_compared_set():
    """『本文欄位目錄 ⊆ 比對集合』：已存的每個非流程頂層鍵，只要被改，scope 1 都抓得到。"""
    old = _body()
    for k in alt_lock.body_keys(old):
        if k == "items":
            continue
        new = _copy(old)
        new[k] = "__changed__" if not isinstance(old[k], (int, float)) else old[k] + 1
        assert k in alt_lock.changed(new, old, 1), k


# --- guard_update ------------------------------------------------------------------------------

def _policy(monkeypatch, **vals):
    base = {"lock_scope": 1, "unlock_edit_signed": 1, "move_out_of_sent": 1}
    base.update(vals)
    monkeypatch.setattr(alt_policy, "policy", lambda k, conn=None: base[k])


def _409(fn, *a):
    with pytest.raises(HTTPException) as e:
        fn(*a)
    assert e.value.status_code == 409
    return e.value.detail


def test_p4_default_rejects_unlock_edit_regardless_of_client_flag(monkeypatch):
    _policy(monkeypatch)
    old = _body(altPicks={"投影機": "x1"})
    assert _409(alt_sign.guard_update, _copy(old), old, True) == alt_lock.LOCKED_MSG        # 即使內容完全沒改
    alt_sign.guard_update(_copy(old), old, False)                                           # 非解鎖修改且沒改本文 ⇒ 過


def test_p4_allow_keeps_p1_in_force(monkeypatch):
    _policy(monkeypatch, unlock_edit_signed=2)
    old = _body(altPicks={"投影機": "x1"})
    alt_sign.guard_update(_copy(old), old, True)
    new = _copy(old)
    new["items"][1]["unitPrice"] = 1
    assert _409(alt_sign.guard_update, new, old, True) == alt_lock.LOCKED_MSG


def test_p1_scope_two_allows_notes_blocks_money(monkeypatch):
    _policy(monkeypatch, lock_scope=2)
    old = _body(altPicks={"投影機": "x1"})
    new = _copy(old)
    new["afterSales"] = "改"
    alt_sign.guard_update(new, old, False)
    new["discount"] = 5
    _409(alt_sign.guard_update, new, old, False)


def test_non_alt_signed_quote_is_not_affected(monkeypatch):
    _policy(monkeypatch)
    old = {"items": [_it("a", 1, 1000, 600)], "taxRate": 5}
    new = _copy(old)
    new["items"][0]["unitPrice"] = 5
    alt_sign.guard_update(new, old, True)                          # H5：無擇一資料 ⇒ 完全不管
    old2 = _body(totalsByAlt=False)                                # 開關沒開 ⇒ 惰性
    alt_sign.guard_update(_copy(old2), old2, True)


def test_move_out_of_sent_p3_default_blocks_alt_only(monkeypatch):
    _policy(monkeypatch)
    alt = _body(altPicks={"投影機": "x1"})
    for target in ("草稿", "待審核", "已取消", "已拒絕"):
        assert _409(alt_sign.guard_move_out_of_sent, True, alt, target) == alt_lock.LOCKED_MSG
    alt_sign.guard_move_out_of_sent(True, alt, "已送出")
    alt_sign.guard_move_out_of_sent(False, alt, "草稿")            # 沒回簽
    alt_sign.guard_move_out_of_sent(True, {"items": [_it("a", 1, 1, 1)]}, "草稿")      # 非擇一


def test_availability_flips_match_consumers():
    from helpers import settings_groups as SG
    assert "lock_scope" not in SG.UNAVAILABLE_ALT_CHOICES and "unlock_edit_signed" not in SG.UNAVAILABLE_ALT_CHOICES
    for k in ("move_out_of_sent", "reject_final_keep", "approval_basis", "cancel_after_export", "cancel_after_invoice", "cancel_after_settle"):
        assert k in SG.UNAVAILABLE_ALT_CHOICES                     # 沒有消費者 ⇒ 仍不可選


# --- 端點（整合；Edge）------------------------------------------------------------------------------

def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def su_h(client, make_user):
    u, p = make_user(username="alt_lock_su", role="superadmin")
    return _login(client, u, p)


def _signed_quote(client, h):
    body = _body()
    body.pop("tot"); body.pop("approval"); body.pop("caseRecord")
    r = client.post("/api/quotations", json={"status": "草稿", "data": body}, headers=h)
    assert r.status_code == 201, r.text
    no = r.json()["quote_no"]
    cn = db.get_db()
    try:
        cn.execute("UPDATE quotations SET status='已送出' WHERE quote_no=?", (no,))
        cn.commit()
    finally:
        cn.close()
    r = client.post("/api/quotations/%s/signed-toggle" % no, json={"action": "sign", "picks": {"投影機": "x2"}}, headers=h)
    assert r.status_code == 200, r.text
    return no


def _row(no):
    cn = db.get_db()
    try:
        return dict(cn.execute("SELECT * FROM quotations WHERE quote_no=?", (no,)).fetchone())
    finally:
        cn.close()


def test_status_changes_of_signed_alt_quote_are_409_and_change_nothing(client, su_h):
    no = _signed_quote(client, su_h)
    before = _row(no)
    for st in ("草稿", "待審核", "已取消", "已拒絕"):
        r = client.patch("/api/quotations/%s/status" % no, json={"status": st}, headers=su_h)
        assert r.status_code == 409, (st, r.status_code, r.text)
    after = _row(no)
    assert after["status"] == "已送出" and after["is_signed"] == 1 and after["data_json"] == before["data_json"]


def test_put_with_unlock_edit_is_409_by_default_and_server_ignores_client_flag(client, su_h):
    no = _signed_quote(client, su_h)
    d = json.loads(_row(no)["data_json"])
    d["_isUnlockEdit"] = True
    r = client.put("/api/quotations/%s" % no, json={"status": "待審核", "data": d}, headers=su_h)
    assert r.status_code == 409 and "取消回簽" in r.text, (r.status_code, r.text[:300])
    d.pop("_isUnlockEdit")
    d["items"][1]["unitPrice"] = 1
    r = client.put("/api/quotations/%s" % no, json={"status": "已送出", "data": d}, headers=su_h)
    assert r.status_code in (403, 409)                              # 已送出本來就 403；任何情況都不可寫入
    assert json.loads(_row(no)["data_json"])["items"][1]["unitPrice"] == 3000
