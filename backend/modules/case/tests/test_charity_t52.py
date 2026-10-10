# -*- coding: utf-8 -*-
"""第 52 班：公益捐款改『報價含稅金額 × 1%』（`charity_basis_mode`＝total）＋ 精算頁調整管銷比率端點。

設計：docs/platform/plans/CHARITY-QUOTE-1PCT-DESIGN-T52.md。預設 direct（新行為關）：數字、戳記完全不變。
total 要同時：overhead_rule_mode=v2 ＋ overhead_migration_done ＋ charity_migration_done ＋ charity_basis_mode=total，缺一就當 direct。
"""
import json

import pytest

import db
from modules.case import settlement_actuals as SA
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W  # noqa: F401
from modules.case.tests.test_settlement_actuals_2026_10_03 import _get  # noqa: F401
from modules.case.tests.test_settlement_finalize_integrity_2026_10_03 import QUOTED_PRETAX, _set_tot, page_payload
from modules.case.tests._t40_won import quote_is_won  # noqa: F401  完結要已成案（autouse）

KEYS = ("overhead_rule_mode", "overhead_migration_done", "charity_basis_mode", "charity_migration_done", "overhead_default_pct")
URL = "/api/quotations/%s/settlement" % NO


def _set(key, value):
    cn = db.get_db()
    try:
        cn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?, ?, '2031-01-01T00:00:00') "
                   "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json", (key, json.dumps(value)))
        cn.commit()
    finally:
        cn.close()


def _unset(*keys):
    cn = db.get_db()
    try:
        for k in keys:
            cn.execute("DELETE FROM system_settings WHERE key=?", (k,))
        cn.commit()
    finally:
        cn.close()


@pytest.fixture(autouse=True)
def _reset():
    yield
    _unset(*KEYS)


def _all_on(charity="total"):
    _set("overhead_rule_mode", "v2")
    _set("overhead_migration_done", {"doneAt": "2026-10-09T00:00:00"})
    _set("charity_basis_mode", charity)
    _set("charity_migration_done", {"doneAt": "2026-10-10T00:00:00"})


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def who(client, make_user):
    su, sp = make_user(username="ch_su", role="superadmin")
    ad, ap = make_user(username="ch_admin", role="admin")
    return _login(client, su, sp), _login(client, ad, ap)


def _q(**over):
    d = {"customerName": "公益測客", "projectName": "公益測專", "salesPerson": "", "quoteDate": "2026-10-10",
         "items": [{"type": "item", "qty": 1, "unitPrice": 100000, "amount": 100000, "cost": 60000}],
         "tot": {"subtotal": 100000, "pretax": 100000, "tax": 5000, "total": 105000, "totalCost": 60000, "inputVat": 3000,
                 "directProfit": 37000, "directMarginPct": 37.0, "adminCost": 10000, "charityDonation": 370, "totalIndirect": 10370,
                 "netProfit": 26630, "netMarginPct": 26.6}}
    d.update(over)
    return d


def _row(qno):
    cn = db.get_db()
    try:
        r = cn.execute("SELECT data_json, net_margin_pct, updated_at FROM quotations WHERE quote_no=?", (qno,)).fetchone()
        return json.loads(r["data_json"]), r["net_margin_pct"], r["updated_at"]
    finally:
        cn.close()


def _post(client, h, data):
    r = client.post("/api/quotations", json={"status": "草稿", "data": data}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["quote_no"]


def _audits(action):
    cn = db.get_db()
    try:
        return [dict(r) for r in cn.execute("SELECT * FROM audit_log WHERE action=?", (action,)).fetchall()]
    finally:
        cn.close()


# ── 失效安全：缺任一條件就是舊基 ───────────────────────────────────────────────
@pytest.mark.parametrize("missing", ["overhead_rule_mode", "overhead_migration_done", "charity_migration_done", "charity_basis_mode"])
def test_total_basis_needs_all_four_conditions(client, who, missing):
    su, ad = who
    _all_on()
    _unset(missing)
    qno = _post(client, su, _q())
    d = _row(qno)[0]
    if missing in ("overhead_rule_mode", "overhead_migration_done"):                    # 管銷口徑不是 v2 ⇒ 連 formulaVer 都沒有
        assert d["tot"].get("formulaVer") != 2
    else:
        assert d["tot"]["formulaVer"] == 2 and d["tot"]["charityDonation"] == 370, "v2 但公益基數沒就緒 ⇒ 仍是直接毛利×1%"
    assert "charityBasis" not in d["tot"]


def test_default_mode_direct_is_unchanged_in_v2(client, who):
    su, _ = who
    _set("overhead_rule_mode", "v2")
    _set("overhead_migration_done", {"doneAt": "2026-10-09T00:00:00"})
    d = _row(_post(client, su, _q()))[0]
    assert d["tot"]["formulaVer"] == 2 and d["tot"]["charityDonation"] == 370 and "charityBasis" not in d["tot"]


# ── total 基數：公式、戳記、偽造 ─────────────────────────────────────────────
def test_total_basis_create_uses_tax_inclusive_total_and_stamps(client, who):
    su, _ = who
    _all_on()
    qno = _post(client, su, _q())
    d, col, _ = _row(qno)
    t = d["tot"]
    assert t["total"] == 105000 and t["charityDonation"] == 1050 and t["charityBasis"] == "total" and t["formulaVer"] == 2
    assert t["adminCost"] == 9250 and t["totalIndirect"] == 9250 + 1050 and t["netProfit"] == 37000 - 9250 - 1050
    assert col == t["netMarginPct"]


def test_total_basis_loss_case_still_pays_charity_and_floor_is_on_total_only(client, who):
    su, _ = who
    _all_on()
    loss = _q(items=[{"type": "item", "qty": 1, "unitPrice": 100000, "amount": 100000, "cost": 120000}])
    t = _row(_post(client, su, loss))[0]["tot"]
    assert t["directProfit"] < 0 and t["adminCost"] == 0 and t["charityDonation"] == 1050, "虧損案照扣（不再下限 0）"
    assert t["netProfit"] == t["directProfit"] - 1050


def test_forged_charity_stamps_from_the_client_are_dropped_and_server_restamps(client, who):
    su, ad = who
    qno = _post(client, su, _q())                                       # 預設 direct
    body = _q()
    body["tot"].update(charityBasis="total", _legacyCharity={"x": 1})
    r = client.put("/api/quotations/%s" % qno, json={"status": "草稿", "data": body}, headers=ad)
    assert r.status_code == 200, r.text
    t = _row(qno)[0]["tot"]
    assert "charityBasis" not in t and "_legacyCharity" not in t
    _all_on()                                                           # total 模式下送 direct 戳記 ⇒ 伺服器重蓋 total
    body = _q()
    body["tot"].update(charityBasis="direct")
    assert client.put("/api/quotations/%s" % qno, json={"status": "草稿", "data": body}, headers=ad).status_code == 200
    assert _row(qno)[0]["tot"]["charityBasis"] == "total"


def test_legacy_charity_snapshot_survives_a_resave(client, who):
    su, ad = who
    _all_on()
    qno = _post(client, su, _q())
    cn = db.get_db()
    d = _row(qno)[0]
    d["tot"]["_legacyCharity"] = {"charityDonation": 370, "totalIndirect": 9620, "netProfit": 27380, "netMarginPct": 27.4}
    cn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), qno))
    cn.commit()
    cn.close()
    body = _q(customerName="改名")
    body["tot"]["_legacyCharity"] = {"forged": True}
    assert client.put("/api/quotations/%s" % qno, json={"status": "草稿", "data": body}, headers=ad).status_code == 200
    assert _row(qno)[0]["tot"]["_legacyCharity"]["charityDonation"] == 370, "回滾依據沿用資料庫現值"


def test_settled_quote_is_not_touched_by_a_resave(client, who):
    su, _ = who
    qno = _post(client, su, _q())
    cn = db.get_db()
    cn.execute("UPDATE quotations SET deal_tag='已結案' WHERE quote_no=?", (qno,))
    cn.commit()
    cn.close()
    _all_on()
    before = _row(qno)[0]["tot"]
    r = client.put("/api/quotations/%s" % qno, json={"status": "草稿", "data": _q()}, headers=su)
    assert r.status_code in (200, 403, 409), r.text
    assert _row(qno)[0]["tot"] == before and "charityBasis" not in before


# ── 設定端點：切換條件 ─────────────────────────────────────────────────────────
def test_settings_get_reports_effective_charity_basis(client, who):
    su, _ = who
    assert client.get("/api/overhead/settings", headers=su).json()["charityBasis"] == "direct"
    _all_on()
    j = client.get("/api/overhead/settings", headers=su).json()
    assert j["charityBasis"] == "total" and j["charityMode"] == "total" and j["charityMigrationDone"] is True


def test_charity_mode_switch_conditions_and_forced_revert(client, who):
    su, ad = who
    put = lambda h, **b: client.put("/api/overhead/settings", json=b, headers=h)               # noqa: E731
    assert put(ad, charityMode="total", confirm=True).status_code == 403, "只有最高管理者"
    assert put(su, charityMode="oops").status_code == 422
    assert put(su, charityMode="total").status_code == 422, "沒有 confirm"
    assert put(su, charityMode="total", confirm=True).status_code == 409, "管銷不是 v2"
    _set("overhead_rule_mode", "v2")
    _set("overhead_migration_done", {"doneAt": "x"})
    assert put(su, charityMode="total", confirm=True).status_code == 409, "沒有公益遷移完成標記"
    _set("charity_migration_done", {"doneAt": "y"})
    assert put(su, charityMode="total", confirm=True).status_code == 200
    assert client.get("/api/overhead/settings", headers=su).json()["charityBasis"] == "total"
    assert any("公益基數" in json.dumps(a, ensure_ascii=False) for a in _audits("settings.overhead.update"))
    # 管銷退回 legacy ⇒ 公益基數強制退回 direct 並移除標記
    assert put(su, ruleMode="legacy").status_code == 200
    j = client.get("/api/overhead/settings", headers=su).json()
    assert j["charityBasis"] == "direct" and j["charityMode"] == "direct" and j["charityMigrationDone"] is False
    # 單獨切回 direct 也會移除標記
    _all_on()
    assert put(su, charityMode="direct").status_code == 200
    assert client.get("/api/overhead/settings", headers=su).json()["charityMigrationDone"] is False


# ── 精算頁調整管銷比率端點 ─────────────────────────────────────────────────────
def _v2_quote(client, su, charity="direct"):
    _set("overhead_rule_mode", "v2")
    _set("overhead_migration_done", {"doneAt": "x"})
    if charity == "total":
        _set("charity_basis_mode", "total")
        _set("charity_migration_done", {"doneAt": "y"})
    return _post(client, su, _q())


def test_overhead_pct_endpoint_permissions_and_validation(client, who):
    su, ad = who
    qno = _v2_quote(client, su)
    url = "/api/quotations/%s/overhead-pct" % qno
    assert client.put(url, json={"pct": 20, "confirm": True}, headers=ad).status_code == 403
    assert client.put(url, json={}, headers=su).status_code == 422
    assert client.put(url, json={"pct": "abc", "confirm": True}, headers=su).status_code == 422
    assert client.put(url, json={"pct": 12.34, "confirm": True}, headers=su).status_code == 422
    assert client.put(url, json={"pct": 101, "confirm": True}, headers=su).status_code == 422
    assert client.put(url, json={"pct": 20}, headers=su).status_code == 422, "偏離預設需 confirm=true"
    assert client.put("/api/quotations/NOPE-1/overhead-pct", json={"pct": 25}, headers=su).status_code == 404


@pytest.mark.parametrize("charity", ["direct", "total"])
def test_overhead_pct_endpoint_recalcs_with_the_quotes_own_stamps_and_audits(client, who, charity):
    su, _ = who
    qno = _v2_quote(client, su, charity)
    before, _, ua0 = _row(qno)
    url = "/api/quotations/%s/overhead-pct" % qno
    r = client.put(url, json={"pct": 20, "confirm": True}, headers=su)
    assert r.status_code == 200, r.text
    d, col, ua1 = _row(qno)
    t = d["tot"]
    ch = 1050 if charity == "total" else 370
    assert d["overheadPct"] == 20 and t["overheadPct"] == 20 and t["formulaVer"] == 2
    assert t["adminCost"] == 7400 and t["charityDonation"] == ch and t["totalIndirect"] == 7400 + ch and t["netProfit"] == 37000 - 7400 - ch
    assert (t.get("charityBasis") == "total") == (charity == "total")
    assert t["pretax"] == before["tot"]["pretax"] and t["tax"] == before["tot"]["tax"] and t["total"] == before["tot"]["total"], "價格不動"
    assert col == t["netMarginPct"] and ua1 > ua0 and r.json()["updatedAt"] == ua1
    a = _audits("quotation.overhead_pct_change")
    assert len(a) >= 1 and "25% → 20%" in json.dumps(a[-1], ensure_ascii=False)
    # 設回預設不需 confirm
    assert client.put(url, json={"pct": 25}, headers=su).status_code == 200
    assert _row(qno)[0]["tot"]["adminCost"] == 9250


def test_overhead_pct_endpoint_refuses_settled_non_v2_and_legacy_mode(client, who):
    su, _ = who
    qno = _v2_quote(client, su)
    url = "/api/quotations/%s/overhead-pct" % qno
    cn = db.get_db()
    cn.execute("UPDATE quotations SET settle_status='finalized' WHERE quote_no=?", (qno,))
    cn.commit()
    cn.close()
    assert client.put(url, json={"pct": 20, "confirm": True}, headers=su).status_code == 409, "已精算"
    cn = db.get_db()
    cn.execute("UPDATE quotations SET settle_status='', deal_tag='已結案' WHERE quote_no=?", (qno,))
    cn.commit()
    cn.close()
    assert client.put(url, json={"pct": 20, "confirm": True}, headers=su).status_code == 409, "已結案"
    cn = db.get_db()
    d = _row(qno)[0]
    d["tot"]["formulaVer"] = 1
    cn.execute("UPDATE quotations SET deal_tag='', data_json=? WHERE quote_no=?", (json.dumps(d), qno))
    cn.commit()
    cn.close()
    assert client.put(url, json={"pct": 20, "confirm": True}, headers=su).status_code == 409, "不是新口徑的單"
    _unset("overhead_rule_mode")
    assert client.put(url, json={"pct": 20, "confirm": True}, headers=su).status_code == 409, "legacy 模式"
    d = _row(qno)[0]
    assert d["tot"]["formulaVer"] == 1 and d.get("overheadPct") in (None, 25), "被拒絕就一個字都不改"


def test_stale_form_of_a_non_superadmin_gets_409_not_403_after_the_pct_was_changed(client, who):
    """超管在精算頁改了比率 ⇒ updated_at 變動；開著舊表單（帶舊 _expectedUpdatedAt、舊比率）的一般管理員儲存，得到『已被其他人更新』409，不是莫名其妙的 403。"""
    su, ad = who
    qno = _v2_quote(client, su)
    ua_old = _row(qno)[2]
    assert client.put("/api/quotations/%s/overhead-pct" % qno, json={"pct": 20, "confirm": True}, headers=su).status_code == 200
    body = _q(overheadPct=20)                                           # 表單載入的是新比率 20，但 _expectedUpdatedAt 是舊的
    body["_expectedUpdatedAt"] = ua_old
    r = client.put("/api/quotations/%s" % qno, json={"status": "草稿", "data": body}, headers=ad)
    assert r.status_code == 409 and "其他人更新" in r.text, r.text
    body["_expectedUpdatedAt"] = _row(qno)[2]                           # 重新載入後（帶新 updated_at、新比率 20）⇒ 沒改比率 ⇒ 可存
    assert client.put("/api/quotations/%s" % qno, json={"status": "草稿", "data": body}, headers=ad).status_code == 200
    assert _row(qno)[0]["overheadPct"] == 20


# ── 精算（完結比對／補齊）──────────────────────────────────────────────────────
def _quote_stamp(basis):
    cn = db.get_db()
    try:
        d = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        d["tot"].update(formulaVer=2, overheadPct=25)
        if basis:
            d["tot"]["charityBasis"] = basis
        cn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), NO))
        cn.commit()
    finally:
        cn.close()


def _saved_summary():
    cn = db.get_db()
    try:
        return json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])["settlement"]["summary"]
    finally:
        cn.close()


def _payload(c, h, basis):
    p = page_payload(c, h)
    s = p["summary"]
    gross = s["grossProfit"]
    admin = SA.round_half_up(max(gross, 0), "0.25")
    charity = SA.round_half_up(105000, 0.01) if basis == "total" else max(0, SA.round_half_up(gross, 0.01))
    net = gross - admin - charity
    s.update(adminCost=admin, charityDonation=charity, netProfit=net, netMarginPct=round(net / QUOTED_PRETAX * 100, 1), formulaVer=2, overheadPct=25)
    return p


def test_finalize_total_basis_uses_quoted_total_exact_and_stamps(W):
    c, h = W
    _set_tot()
    _quote_stamp("total")
    _all_on()
    p = _payload(c, h, "total")
    r = c.put(URL, json={"settlement": p}, headers=h)
    assert r.status_code == 200, r.text
    s = _saved_summary()
    assert s["charityBasis"] == "total" and s["charityDonation"] == 1050 and s["origCharityBasis"] == "total"
    assert s["netProfit"] == s["grossProfit"] - s["adminCost"] - 1050


def test_finalize_total_basis_refuses_a_charity_off_by_even_one_dollar(W):
    c, h = W
    _set_tot()
    _quote_stamp("total")
    _all_on()
    p = _payload(c, h, "total")
    p["summary"]["charityDonation"] += 1
    p["summary"]["netProfit"] -= 1
    r = c.put(URL, json={"settlement": p}, headers=h)
    assert r.status_code == 409 and "公益金" in r.text, r.text


def test_finalize_total_basis_refuses_the_old_direct_basis_number(W):
    c, h = W
    _set_tot()
    _all_on()
    r = c.put(URL, json={"settlement": _payload(c, h, "direct")}, headers=h)
    assert r.status_code == 409 and "公益金" in r.text, r.text


def test_finalize_forged_charity_basis_stamps_are_overwritten(W):
    c, h = W
    _set_tot()
    _set("overhead_rule_mode", "v2")
    _set("overhead_migration_done", {"doneAt": "x"})                    # 公益模式 direct（預設）
    p = _payload(c, h, "direct")
    p["summary"].update(charityBasis="total", origCharityBasis="total")
    r = c.put(URL, json={"settlement": p}, headers=h)
    assert r.status_code == 200, r.text
    s = _saved_summary()
    assert "charityBasis" not in s and "origCharityBasis" not in s, "戳記只由伺服器蓋"


def test_orig_side_basis_comes_from_the_quote_stamp_while_actual_side_follows_the_mode(W):
    c, h = W
    _set_tot()
    _quote_stamp("total")                                               # 報價單是 total 戳記
    _set("overhead_rule_mode", "v2")
    _set("overhead_migration_done", {"doneAt": "x"})                    # 但目前公益模式是 direct
    r = c.put(URL, json={"settlement": _payload(c, h, "direct")}, headers=h)
    assert r.status_code == 200, r.text
    s = _saved_summary()
    assert s["origCharityBasis"] == "total" and "charityBasis" not in s
    assert s["origCharity"] == 1050 and s["charityDonation"] == max(0, SA.round_half_up(s["grossProfit"], 0.01))


def test_legacy_ver1_finalize_never_gets_the_total_basis(W):
    c, h = W
    _set_tot()
    _set("charity_basis_mode", "total")
    _set("charity_migration_done", {"doneAt": "y"})                     # 管銷是 legacy ⇒ 公益基數無效
    r = c.put(URL, json={"settlement": page_payload(c, h)}, headers=h)
    assert r.status_code == 200, r.text
    s = _saved_summary()
    assert "charityBasis" not in s and "formulaVer" not in s
