# -*- coding: utf-8 -*-
"""第 48 班 S2：報價單 `overheadPct`（權限／驗證／稽核／預設值）＋ `overhead_rule_mode` 開關 ＋ 伺服器端利潤重算。

預設 `legacy`（新行為關閉）：數字完全不變；`v2` 才用 直接毛利×pct% 重算。設計：docs/platform/plans/OVERHEAD-25PCT-OPERATING-PROFIT-DESIGN-T48.md。
"""
import json

import pytest

import db


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def who(client, make_user):
    su, sp = make_user(username="oh_su", role="superadmin")
    ad, ap = make_user(username="oh_admin", role="admin")
    return _login(client, su, sp), _login(client, ad, ap)


def _q(**over):
    d = {"customerName": "管銷測客", "projectName": "管銷測專", "salesPerson": "", "quoteDate": "2026-10-09",
         "items": [{"type": "item", "qty": 1, "unitPrice": 100000, "amount": 100000, "cost": 60000}],
         "tot": {"subtotal": 100000, "pretax": 100000, "tax": 5000, "total": 105000, "totalCost": 60000, "inputVat": 3000,
                 "directProfit": 37000, "directMarginPct": 37.0, "adminCost": 10000, "charityDonation": 370, "totalIndirect": 10370,
                 "netProfit": 26630, "netMarginPct": 26.6}}
    d.update(over)
    return d


def _post(client, h, data, status="草稿"):
    return client.post("/api/quotations", json={"status": status, "data": data}, headers=h)


def _row(qno):
    cn = db.get_db()
    try:
        r = cn.execute("SELECT data_json, net_margin_pct, deal_tag, settle_status FROM quotations WHERE quote_no=?", (qno,)).fetchone()
        return json.loads(r["data_json"]), r["net_margin_pct"], r
    finally:
        cn.close()


def _audits(action):
    cn = db.get_db()
    try:
        return [dict(r) for r in cn.execute("SELECT * FROM audit_log WHERE action=?", (action,)).fetchall()]
    finally:
        cn.close()


def _mode(client, su, mode):
    r = client.put("/api/overhead/settings", json={"ruleMode": mode}, headers=su)
    assert r.status_code == 200, r.text


# ── 預設（legacy）：數字不變 ───────────────────────────────────────────────────────
def test_legacy_mode_keeps_numbers_and_stamps_default_pct_on_create(client, who):
    su, ad = who
    forged = _q()
    forged["tot"]["netMarginPct"] = 99.9                       # legacy：伺服器不改前端送來的值（只做影子比對）
    r = _post(client, ad, forged)
    assert r.status_code == 201, r.text
    data, nm, _ = _row(r.json()["quote_no"])
    assert data["overheadPct"] == 25 and "formulaVer" not in data["tot"]
    assert data["tot"]["adminCost"] == 10000 and data["tot"]["netMarginPct"] == 99.9 and nm == 99.9


def test_legacy_existing_quote_without_pct_does_not_grow_the_key(client, who):
    su, ad = who
    qno = _post(client, ad, _q()).json()["quote_no"]
    cn = db.get_db()                                           # 模擬舊單：沒有 overheadPct
    d = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (qno,)).fetchone()["data_json"])
    d.pop("overheadPct")
    cn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), qno))
    cn.commit()
    cn.close()
    body = _q(customerName="改名")
    r = client.put("/api/quotations/%s" % qno, json={"status": "草稿", "data": body}, headers=ad)
    assert r.status_code == 200, r.text
    assert "overheadPct" not in _row(qno)[0]


# ── 權限／驗證／稽核 ──────────────────────────────────────────────────────────────
def test_only_superadmin_may_change_the_pct_create_and_update(client, who):
    su, ad = who
    assert _post(client, ad, _q(overheadPct=30)).status_code == 403
    assert _post(client, ad, _q(overheadPct=25)).status_code == 201, "和預設相同＝沒有改"
    r = _post(client, su, _q(overheadPct=30))
    assert r.status_code == 201, r.text
    qno = r.json()["quote_no"]
    assert _row(qno)[0]["overheadPct"] == 30
    a = _audits("quotation.overhead_pct_change")
    assert len(a) == 1 and a[0]["target_id"] == qno and json.loads(a[0]["detail"]) == {"old": 25, "new": 30, "default": 25}
    r = client.put("/api/quotations/%s" % qno, json={"status": "草稿", "data": _q(overheadPct=40)}, headers=ad)
    assert r.status_code == 403 and "最高管理者" in r.text
    assert _row(qno)[0]["overheadPct"] == 30, "被擋的請求不寫入"
    r = client.put("/api/quotations/%s" % qno, json={"status": "草稿", "data": _q()}, headers=ad)       # 沒帶 ⇒ 保留存值
    assert r.status_code == 200 and _row(qno)[0]["overheadPct"] == 30
    r = client.put("/api/quotations/%s" % qno, json={"status": "草稿", "data": _q(overheadPct=40)}, headers=su)
    assert r.status_code == 200 and _row(qno)[0]["overheadPct"] == 40
    assert len(_audits("quotation.overhead_pct_change")) == 2


@pytest.mark.parametrize("bad", [101, -1, 12.34, "25", True, float("nan")])
def test_invalid_pct_is_422(client, who, bad):
    su, ad = who
    r = client.post("/api/quotations", content=json.dumps({"status": "草稿", "data": _q(overheadPct=bad)}, allow_nan=True),
                    headers=dict(su, **{"Content-Type": "application/json"}))
    assert r.status_code in (422, 400), r.text


def test_settled_quote_pct_and_numbers_are_frozen(client, who):
    su, ad = who
    qno = _post(client, su, _q(overheadPct=30)).json()["quote_no"]
    cn = db.get_db()
    cn.execute("UPDATE quotations SET deal_tag='已結案' WHERE quote_no=?", (qno,))
    cn.commit()
    cn.close()
    r = client.put("/api/quotations/%s" % qno, json={"status": "草稿", "data": _q(overheadPct=50)}, headers=su)
    assert r.status_code in (200, 403), r.text                  # 狀態鎖可能先擋；通過時比率也不得被改
    assert _row(qno)[0]["overheadPct"] == 30


# ── 設定端點 ──────────────────────────────────────────────────────────────────────
def test_settings_endpoint_authz_audit_and_default_applies_to_new_quotes(client, who):
    su, ad = who
    assert client.get("/api/overhead/settings", headers=ad).json() == {"ruleMode": "legacy", "defaultPct": 25, "ver": 1}
    assert client.put("/api/overhead/settings", json={"defaultPct": 20}, headers=ad).status_code == 403
    assert client.put("/api/overhead/settings", json={"defaultPct": 120}, headers=su).status_code == 422
    assert client.put("/api/overhead/settings", json={"ruleMode": "x"}, headers=su).status_code == 422
    assert client.put("/api/overhead/settings", json={"defaultPct": 20}, headers=su).status_code == 200
    assert _audits("settings.overhead.update") and "20" in _audits("settings.overhead.update")[0]["target_label"]
    qno = _post(client, ad, _q()).json()["quote_no"]
    assert _row(qno)[0]["overheadPct"] == 20, "新建沿用全域預設"
    assert _post(client, ad, _q(overheadPct=25)).status_code == 403, "預設改成 20 之後 25 就是『偏離』"
    client.put("/api/overhead/settings", json={"defaultPct": 25}, headers=su)


# ── v2：伺服器重算 ────────────────────────────────────────────────────────────────
def test_v2_mode_recomputes_profit_fields_server_side_and_ignores_forged_tot(client, who):
    su, ad = who
    _mode(client, su, "v2")
    forged = _q()
    forged["tot"].update(netMarginPct=99.9, netProfit=999999, adminCost=1)
    r = _post(client, ad, forged)
    assert r.status_code == 201, r.text
    data, nm, _ = _row(r.json()["quote_no"])
    t = data["tot"]
    # 稅前 100000、成本 60000、進項稅 3000 ⇒ 直毛 37000；管銷 25%×37000=9250；公益 370；營業利益 27380（27.4%）
    assert (t["directProfit"], t["adminCost"], t["charityDonation"], t["totalIndirect"], t["netProfit"], t["netMarginPct"]) == (37000, 9250, 370, 9620, 27380, 27.4)
    assert t["formulaVer"] == 2 and t["overheadPct"] == 25 and nm == 27.4 and data["overheadPct"] == 25
    _mode(client, su, "legacy")


def test_v2_negative_direct_profit_has_zero_overhead_and_five_items_count(client, who):
    su, ad = who
    _mode(client, su, "v2")
    loss = _q(items=[{"type": "item", "qty": 1, "unitPrice": 100000, "amount": 100000, "cost": 99000}],
              indirectLogistics=1000, indirectOther=500)
    t = _row(_post(client, ad, loss).json()["quote_no"])[0]["tot"]
    assert t["directProfit"] == 100000 - 99000 - 4950 and t["adminCost"] == 0 and t["charityDonation"] == 0
    assert t["totalIndirect"] == 1500 and t["netProfit"] == t["directProfit"] - 1500
    _mode(client, su, "legacy")


def test_v2_custom_pct_by_superadmin_drives_the_amount(client, who):
    su, ad = who
    _mode(client, su, "v2")
    t = _row(_post(client, su, _q(overheadPct=10)).json()["quote_no"])[0]["tot"]
    assert t["adminCost"] == 3700 and t["overheadPct"] == 10
    _mode(client, su, "legacy")


def test_migration_recalc_equals_the_server_recompute():
    """S5 遷移（凍結算式，從存的 tot 推）與 S2 伺服器重算（從品項推）在一致的報價單上逐欄位相同——遷移後第一次存檔不會讓數字再跳。"""
    from migrations_frozen.t48_overhead25 import recalc
    from modules.case import profit_guard as PG
    for pretax, cost, five, pct in [(100000, 60000, [1000, 2000, 500, 300, 200], 25), (100000, 60000, [0] * 5, 12.5),
                                    (35000, 20001, [0, 0, 0, 0, 0], 25), (100000, 99000, [1000, 0, 0, 0, 500], 25), (50, 40, [0] * 5, 7.1)]:
        vat = PG.round_half_up(cost, 0.05)
        direct = pretax - cost - vat
        admin_old = PG.round_half_up(pretax, 0.10)
        charity = max(0, PG.round_half_up(direct, 0.01))
        q = {"items": [{"type": "item", "qty": 1, "cost": cost}], "tot": {"pretax": pretax}, **dict(zip(PG.INDIRECT_KEYS, five))}
        tot = {"pretax": pretax, "directProfit": direct, "adminCost": admin_old, "charityDonation": charity,
               "totalIndirect": admin_old + charity + sum(five)}
        mig = recalc.new_tot_fields(tot, pct)
        srv = PG.server_profit(q, pct, 2)
        assert {k: mig[k] for k in ("adminCost", "totalIndirect", "netProfit", "netMarginPct", "charityDonation")} == \
               {k: srv[k] for k in ("adminCost", "totalIndirect", "netProfit", "netMarginPct", "charityDonation")}, (pretax, cost, pct)
