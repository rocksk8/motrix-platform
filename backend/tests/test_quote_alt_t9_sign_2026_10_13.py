# -*- coding: utf-8 -*-
"""M3 T9a（T57）：擇一單的回簽選定／取消回簽、唯一清除入口 `clear_signed_selection` 與守門鏈 P8→P7→P6→P2。
端點題建單會觸發自動 PDF（啟動 Edge）——閘門才跑，作者不在安靜期外跑。"""
import json
import sqlite3

import pytest
from fastapi import HTTPException

import db
from modules.case import alt_policy, alt_sign
from modules.case import profit_guard as PG


def _it(id_, qty, price, cost, group=None, **kw):
    d = {"id": id_, "qty": qty, "unitPrice": price, "cost": cost, "amount": qty * price, "description": "品" + id_, "unit": "式"}
    if group is not None:
        d["altGroup"] = group
    d.update(kw)
    return d


def _items():
    return [_it("a", 1, 1000, 600), _it("x1", 1, 3000, 2000, "投影機"), _it("x2", 1, 5000, 3500, "投影機"),
            _it("y1", 1, 100, 60, "線材"), _it("y2", 1, 150, 90, "線材")]


# --- 純函式 ----------------------------------------------------------------------------

def _data(**kw):
    d = {"items": _items(), "taxRate": 5, "totalsByAlt": True}
    d.update(kw)
    return d


def test_applies_only_when_switch_on_with_groups_or_picks_stored():
    assert alt_sign.applies(_data())
    assert not alt_sign.applies(_data(totalsByAlt=False))
    assert not alt_sign.applies({"items": [_it("a", 1, 1, 1)], "totalsByAlt": True})
    assert alt_sign.applies({"items": [_it("a", 1, 1, 1)], "altPicks": {"G": "a"}})
    assert not alt_sign.applies(None)


def _422(data, picks):
    with pytest.raises(HTTPException) as e:
        alt_sign.validate_picks(data, picks)
    assert e.value.status_code == 422
    return e.value.detail


def test_validate_picks_needs_every_group_and_member_of_group():
    d = _data()
    assert alt_sign.validate_picks(d, {"投影機": "x1", "線材": "y2"}) == {"投影機": "x1", "線材": "y2"}
    assert "請先選擇" in _422(d, {"投影機": "x1"})
    assert "請先選擇" in _422(d, {})
    assert "請先選擇" in _422(d, {"投影機": "x1", "線材": ""})
    assert "不一致" in _422(d, {"投影機": "y1", "線材": "y2"})
    assert "不一致" in _422(d, {"投影機": "x1", "線材": "y2", "多餘": "a"})
    _422(d, None)
    _422(d, ["x1"])


def test_recompute_tot_follows_picks_and_keeps_stamps():
    d = _data(tot={"formulaVer": 2, "overheadPct": 30, "charityBasis": "direct"}, altPicks={"投影機": "x2", "線材": "y1"})
    tot = alt_sign.recompute_tot(d)
    t = PG.server_totals(d)
    assert tot["pretax"] == t["pretax"] == 6100 and tot["total"] == t["total"]
    assert tot["formulaVer"] == 2 and tot["overheadPct"] == 30
    p = PG.server_profit(d, 30, 2, pretax=t["pretax"], total=t["total"])
    assert tot["netProfit"] == p["netProfit"] and tot["totalCost"] == p["totalCost"] == 4160
    d.pop("altPicks")
    assert alt_sign.recompute_tot(d)["pretax"] == 1000                 # 回暫估：只剩一般品項


# --- 守門鏈（假連線／假列，不碰資料庫）------------------------------------------------------

class _Row(dict):
    pass


def _row(deal="", settle="", dealtag_in_data=""):
    return _Row(deal_tag=deal, settle_status=settle)


def _policies(monkeypatch, **vals):
    base = {"cancel_after_settle": 1, "cancel_after_invoice": 1, "cancel_after_export": 1, "cancel_after_deal": 1}
    base.update(vals)
    monkeypatch.setattr(alt_policy, "policy", lambda k, conn=None: base[k])


def _counts(monkeypatch, unexported, exported):
    monkeypatch.setattr(alt_sign, "_arap_counts", lambda conn, no: (unexported, exported))


def _chain(row, data=None):
    return alt_sign.check_downstream(None, "Q1", row, data or {})


def _409(row, data=None):
    with pytest.raises(HTTPException) as e:
        _chain(row, data)
    assert e.value.status_code == 409
    return e.value.detail


def test_chain_order_is_p8_then_p7_then_p6_then_p2(monkeypatch):
    _policies(monkeypatch)
    _counts(monkeypatch, 1, 1)
    assert _409(_row(deal="已成案", settle="finalized")) == alt_sign.MSG_P8
    assert _409(_row(deal="已成案")) == alt_sign.MSG_P7
    _policies(monkeypatch, cancel_after_invoice=2)             # 假設日後 P7 放寬：下一層 P6 接手
    assert _409(_row(deal="已成案")) == alt_sign.MSG_P6
    _policies(monkeypatch, cancel_after_invoice=2, cancel_after_export=2)
    assert _409(_row(deal="已成案")) == alt_sign.MSG_P2


def test_chain_passes_when_nothing_downstream(monkeypatch):
    _policies(monkeypatch)
    _counts(monkeypatch, 0, 0)
    assert _chain(_row()) == []


def test_p2_option_three_allows_with_warning(monkeypatch):
    _policies(monkeypatch, cancel_after_deal=3)
    _counts(monkeypatch, 0, 0)
    assert _chain(_row(deal="已成案")) == [alt_sign.WARN_P2]
    assert _chain(_row(), {"dealTag": "已成案"}) == [alt_sign.WARN_P2]          # 單上標籤也算


def test_settled_by_deal_tag_closed_is_p8(monkeypatch):
    _policies(monkeypatch)
    _counts(monkeypatch, 0, 0)
    assert _409(_row(deal="已結案")) == alt_sign.MSG_P8


def test_arap_not_loaded_or_missing_tables_means_no_downstream(monkeypatch):
    from core import registry
    cn = sqlite3.connect(":memory:")
    cn.row_factory = sqlite3.Row
    monkeypatch.setattr(registry, "is_loaded", lambda k: False)
    assert alt_sign._arap_counts(cn, "Q1") == (0, 0)
    monkeypatch.setattr(registry, "is_loaded", lambda k: True)
    assert alt_sign._arap_counts(cn, "Q1") == (0, 0)              # 缺表 ⇒ OperationalError ⇒ 視為沒有，不是 500、不是永久 409


def test_arap_counts_exclude_drafts_and_split_by_export_count(monkeypatch):
    from core import registry
    monkeypatch.setattr(registry, "is_loaded", lambda k: True)
    cn = sqlite3.connect(":memory:")
    cn.row_factory = sqlite3.Row
    cn.execute("CREATE TABLE invoice_vouchers (voucher_no TEXT, quote_no TEXT, status TEXT, export_count INTEGER)")
    cn.execute("CREATE TABLE payment_requests (request_no TEXT, quote_no TEXT, status TEXT, export_count INTEGER)")
    cn.executemany("INSERT INTO invoice_vouchers VALUES (?,?,?,?)", [("V1", "Q1", "草稿", 0), ("V2", "Q1", "已核准", 0), ("V3", "Q1", "已核准", 2), ("V4", "Q9", "已核准", 1)])
    cn.execute("INSERT INTO payment_requests VALUES ('R1','Q1','待審核',NULL)")
    assert alt_sign._arap_counts(cn, "Q1") == (2, 1)               # 草稿不算；NULL export_count 視為未匯出
    assert alt_sign._arap_counts(cn, "Q2") == (0, 0)


# --- 端點（整合）--------------------------------------------------------------------------

def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def admin_h(client, make_user):
    u, p = make_user(username="alt_sign_admin", role="admin")
    return _login(client, u, p)


def _make(client, h, *, switch=True, items=None):
    body = {"customerName": "回簽客", "projectName": "回簽案", "salesPerson": "", "quoteDate": "2026-10-13", "taxRate": 5,
            "items": items or _items(), "tot": {}}
    if switch:
        body["totalsByAlt"] = True
    r = client.post("/api/quotations", json={"status": "草稿", "data": body}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["quote_no"]


def _row_of(no):
    cn = db.get_db()
    try:
        return dict(cn.execute("SELECT * FROM quotations WHERE quote_no=?", (no,)).fetchone())
    finally:
        cn.close()


def _set(no, **cols):
    cn = db.get_db()
    try:
        cn.execute("UPDATE quotations SET %s WHERE quote_no=?" % ",".join("%s=?" % k for k in cols), (*cols.values(), no))
        cn.commit()
    finally:
        cn.close()


def _sent(client, h, **kw):
    no = _make(client, h, **kw)
    _set(no, status="已送出")
    return no


def _toggle(client, h, no, action, **extra):
    return client.post("/api/quotations/%s/signed-toggle" % no, json=dict({"action": action}, **extra), headers=h)


def _audits(no, action):
    cn = db.get_db()
    try:
        return [json.loads(r["detail"]) for r in cn.execute("SELECT detail FROM audit_log WHERE target_id=? AND action=?", (no, action)).fetchall()]
    finally:
        cn.close()


def test_sign_without_or_with_bad_picks_is_422_and_writes_nothing(client, admin_h):
    no = _sent(client, admin_h)
    before = _row_of(no)
    for picks in (None, {}, {"投影機": "x1"}, {"投影機": "y1", "線材": "y2"}):
        r = _toggle(client, admin_h, no, "sign", **({"picks": picks} if picks is not None else {}))
        assert r.status_code == 422, (picks, r.text)
    after = _row_of(no)
    assert after["is_signed"] == 0 and after["data_json"] == before["data_json"] and after["updated_at"] == before["updated_at"]
    assert _audits(no, "quotation.sign_alt") == []


def test_sign_with_picks_writes_picks_totals_columns_and_audit_together(client, admin_h):
    no = _sent(client, admin_h)
    r = _toggle(client, admin_h, no, "sign", picks={"投影機": "x2", "線材": "y1"})
    assert r.status_code == 200, r.text
    row = _row_of(no)
    d = json.loads(row["data_json"])
    assert row["is_signed"] == 1 and d["altPicks"] == {"投影機": "x2", "線材": "y1"} and d["altPickedAt"] and d["altPickedBy"]
    t = PG.server_totals(d)
    assert d["tot"]["pretax"] == t["pretax"] == 6100 and row["pretax"] == 6100 and row["total"] == t["total"]
    assert row["direct_margin_pct"] == d["tot"]["directMarginPct"] and row["net_margin_pct"] == d["tot"]["netMarginPct"]
    a = _audits(no, "quotation.sign_alt")
    assert len(a) == 1 and a[0]["picks"] == {"投影機": "x2", "線材": "y1"} and a[0]["after"]["pretax"] == 6100
    assert _toggle(client, admin_h, no, "sign", picks={"投影機": "x1", "線材": "y1"}).status_code == 409      # 不重複回簽，也沒有『改選』


def test_unsign_clears_everything_in_one_go_and_audits_what_was_cleared(client, admin_h):
    no = _sent(client, admin_h)
    assert _toggle(client, admin_h, no, "sign", picks={"投影機": "x2", "線材": "y1"}).status_code == 200
    r = _toggle(client, admin_h, no, "unsign", note="客戶改主意")
    assert r.status_code == 200, r.text
    row = _row_of(no)
    d = json.loads(row["data_json"])
    assert row["is_signed"] == 0 and row["signed_by"] == "" and "altPicks" not in d and "altPickedAt" not in d and "altPickedBy" not in d
    assert d["tot"]["pretax"] == 1000 and row["pretax"] == 1000
    a = _audits(no, "quotation.unsign_alt")
    assert len(a) == 1 and a[0]["cleared"] == {"投影機": "x2", "線材": "y1"} and a[0]["before"]["pretax"] == 6100 and a[0]["after"]["pretax"] == 1000


def test_unsign_blocked_by_chain_changes_nothing(client, admin_h):
    no = _sent(client, admin_h)
    assert _toggle(client, admin_h, no, "sign", picks={"投影機": "x1", "線材": "y1"}).status_code == 200
    _set(no, deal_tag="已成案")
    before = _row_of(no)
    r = _toggle(client, admin_h, no, "unsign")
    assert r.status_code == 409 and "已成案" in r.text
    after = _row_of(no)
    assert after["is_signed"] == 1 and after["data_json"] == before["data_json"] and after["signed_log"] == before["signed_log"]
    assert _audits(no, "quotation.unsign_alt") == []


def test_unsign_allowed_in_non_approval_states_and_blocked_while_in_approval(client, admin_h):
    no = _sent(client, admin_h)
    assert _toggle(client, admin_h, no, "sign", picks={"投影機": "x1", "線材": "y1"}).status_code == 200
    _set(no, status="待審核")
    r = _toggle(client, admin_h, no, "unsign")
    assert r.status_code == 409 and "簽核中" in r.text and _row_of(no)["is_signed"] == 1
    _set(no, status="草稿")
    assert _toggle(client, admin_h, no, "unsign").status_code == 200           # H4：鎖定必有出口


def test_non_alt_quote_keeps_todays_behaviour_bit_for_bit(client, admin_h):
    no = _sent(client, admin_h, switch=False)
    assert _toggle(client, admin_h, no, "sign").status_code == 200
    row = _row_of(no)
    assert row["is_signed"] == 1 and "altPicks" not in json.loads(row["data_json"])
    assert _audits(no, "quotation.sign_alt") == []
    _set(no, status="草稿")
    assert _toggle(client, admin_h, no, "unsign").status_code == 409           # 今日：僅已送出可操作
    _set(no, status="已送出")
    assert _toggle(client, admin_h, no, "unsign").status_code == 200


def test_picks_sent_for_a_quote_without_alt_is_422(client, admin_h):
    no = _sent(client, admin_h, switch=False)
    assert _toggle(client, admin_h, no, "sign", picks={"投影機": "x1"}).status_code == 422
    assert _row_of(no)["is_signed"] == 0


def test_switch_off_quote_with_leftover_single_item_group_still_saves_and_signs(client, admin_h):
    items = [_it("a", 1, 1000, 600), _it("x1", 1, 3000, 2000, "孤組")]
    no = _sent(client, admin_h, switch=False, items=items)                    # 惰性：不算價、不驗組內數量
    assert _toggle(client, admin_h, no, "sign").status_code == 200


def test_only_admin_roles_may_toggle(client, make_user, admin_h):
    no = _sent(client, admin_h)
    u, p = make_user(username="alt_sign_sales", role="sales")
    assert _toggle(client, _login(client, u, p), no, "sign", picks={"投影機": "x1", "線材": "y1"}).status_code == 403


# --- 0d S1／S2 ------------------------------------------------------------------------------

def test_validate_alt_skips_size_rules_when_switch_off_but_keeps_type_checks():
    q = {"items": [_it("a", 1, 1, 1), _it("x", 1, 1, 1, "孤組")]}
    PG.validate_alt(q, 1)                                          # 開關沒開：孤組、組數都不擋
    q["items"][1]["altGroup"] = 5
    with pytest.raises(HTTPException):
        PG.validate_alt(q, 10)                                     # 型別錯誤照擋
    q = {"items": [_it("a", 1, 1, 1), _it("x", 1, 1, 1, "孤組")], "totalsByAlt": True}
    with pytest.raises(HTTPException):
        PG.validate_alt(q, 10)                                     # 開關開了：孤組 422


def test_frozen_snapshot_survives_switch_off():
    old = {"altTexts": {"total_text": "當時", "note_template": "當時{group}"}}
    q = {"items": [_it("a", 1, 1, 1)], "totalsByAlt": False}
    PG.stamp_alt_texts(q, old, freeze=True)
    assert q["altTexts"]["total_text"] == "當時"
    q = {"items": [_it("a", 1, 1, 1)], "totalsByAlt": False}
    PG.stamp_alt_texts(q, old, freeze=False)
    assert "altTexts" not in q
