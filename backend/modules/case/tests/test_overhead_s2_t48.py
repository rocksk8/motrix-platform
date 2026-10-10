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


def _migrated():
    cn = db.get_db()
    try:
        cn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES ('overhead_migration_done', ?, '2031-01-01T00:00:00') "
                   "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json", (json.dumps({"doneAt": "2026-10-09T00:00:00", "by": "test"}),))
        cn.commit()
    finally:
        cn.close()


def _mode(client, su, mode):
    if mode == "v2":
        _migrated()                                      # 伺服器要求遷移完成標記＋明確確認才准切到新口徑
    r = client.put("/api/overhead/settings", json={"ruleMode": mode, "confirm": True}, headers=su)
    assert r.status_code == 200, r.text


# ── 預設（legacy）：數字不變 ───────────────────────────────────────────────────────
def test_legacy_mode_keeps_numbers_and_stamps_default_pct_on_create(client, who):
    su, ad = who
    forged = _q()
    forged["tot"]["netMarginPct"] = 99.9                       # legacy：伺服器不改前端送來的值（只做影子比對）
    r = _post(client, ad, forged)
    assert r.status_code == 201, r.text
    data, nm, _ = _row(r.json()["quote_no"])
    assert "overheadPct" not in data and "formulaVer" not in data["tot"], "legacy 新單不憑空長出比率欄位"
    assert data["tot"]["adminCost"] == 10000 and data["tot"]["netMarginPct"] == 99.9 and nm == 99.9


def test_legacy_existing_quote_without_pct_does_not_grow_the_key(client, who):
    su, ad = who
    qno = _post(client, ad, _q()).json()["quote_no"]
    cn = db.get_db()                                           # 模擬舊單：沒有 overheadPct
    d = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (qno,)).fetchone()["data_json"])
    d.pop("overheadPct", None)
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
    assert client.get("/api/overhead/settings", headers=ad).json() == {"ruleMode": "legacy", "defaultPct": 25, "ver": 1, "migrationDone": False,
                                                                                         "charityBasis": "direct", "charityMode": "direct", "charityMigrationDone": False}   # 第 52 班：加性欄位
    assert client.put("/api/overhead/settings", json={"defaultPct": 20}, headers=ad).status_code == 403
    assert client.put("/api/overhead/settings", json={"defaultPct": 120}, headers=su).status_code == 422
    assert client.put("/api/overhead/settings", json={"ruleMode": "x"}, headers=su).status_code == 422
    assert client.put("/api/overhead/settings", json={"defaultPct": 20}, headers=su).status_code == 200
    assert _audits("settings.overhead.update") and "20" in _audits("settings.overhead.update")[0]["target_label"]
    _mode(client, su, "v2")
    qno = _post(client, ad, _q()).json()["quote_no"]
    assert _row(qno)[0]["overheadPct"] == 20, "新建沿用全域預設（v2 模式蓋章）"
    _mode(client, su, "legacy")
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
    assert t["totalIndirect"] == 0 and t["netProfit"] == t["directProfit"], "新口徑不再計入五項間接成本（使用者 2026-10-09）"
    _mode(client, su, "legacy")


def test_v2_custom_pct_by_superadmin_drives_the_amount(client, who):
    su, ad = who
    _mode(client, su, "v2")
    t = _row(_post(client, su, _q(overheadPct=10)).json()["quote_no"])[0]["tot"]
    assert t["adminCost"] == 3700 and t["overheadPct"] == 10
    _mode(client, su, "legacy")


def test_migration_recalc_equals_the_server_recompute():
    """S5 遷移（凍結算式，從存的 tot 推）與 S2 伺服器重算（從品項推）在一致的報價單上逐欄位相同——遷移後第一次存檔不會讓數字再跳。"""
    recalc = pytest.importorskip("migrations_frozen.t48_overhead25.recalc")      # S5（遷移）不在這條分支時略過
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


# ── 稽核 1d 的修正 ────────────────────────────────────────────────────────────────
def test_client_supplied_stamps_are_never_trusted_in_either_mode(client, who):
    su, ad = who
    forged = _q()
    forged["tot"].update(formulaVer=2, overheadPct=40, _legacy={"x": 1}, _recalc={"y": 1})
    t = _row(_post(client, ad, forged).json()["quote_no"])[0]["tot"]
    assert "formulaVer" not in t and "overheadPct" not in t and "_legacy" not in t and "_recalc" not in t, "legacy：偽造的戳記一律丟掉"
    _mode(client, su, "v2")
    forged = _q()
    forged["tot"].update(formulaVer=1, overheadPct=40, _legacy={"x": 1})
    t = _row(_post(client, ad, forged).json()["quote_no"])[0]["tot"]
    assert t["formulaVer"] == 2 and t["overheadPct"] == 25 and "_legacy" not in t, "v2：戳記只由伺服器蓋"
    _mode(client, su, "legacy")


def test_migration_rollback_basis_survives_form_saves_and_settled_stamps_are_frozen(client, who):
    su, ad = who
    qno = _post(client, ad, _q()).json()["quote_no"]
    cn = db.get_db()
    d = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (qno,)).fetchone()["data_json"])
    d["tot"]["_legacy"] = {"adminCost": 10000, "formulaVer": 1}
    d["tot"]["_recalc"] = {"at": "2026-10-09"}
    cn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), qno))
    cn.commit()
    cn.close()
    forged = _q(customerName="改名")
    forged["tot"]["_legacy"] = {"adminCost": 1}                     # 表單重建的 tot 沒有（或偽造）_legacy
    assert client.put("/api/quotations/%s" % qno, json={"status": "草稿", "data": forged}, headers=ad).status_code == 200
    t = _row(qno)[0]["tot"]
    assert t["_legacy"] == {"adminCost": 10000, "formulaVer": 1} and t["_recalc"] == {"at": "2026-10-09"}, "沿用資料庫現值"
    cn = db.get_db()                                                # 已結案：所有戳記沿用現值
    cn.execute("UPDATE quotations SET deal_tag='已結案' WHERE quote_no=?", (qno,))
    cn.commit()
    cn.close()
    forged = _q()
    forged["tot"].update(formulaVer=2, overheadPct=40)
    client.put("/api/quotations/%s" % qno, json={"status": "草稿", "data": forged}, headers=su)
    t = _row(qno)[0]["tot"]
    assert "formulaVer" not in t and "overheadPct" not in t


def test_mode_flip_needs_confirmation_and_the_migration_marker(client, who):
    su, ad = who
    r = client.put("/api/overhead/settings", json={"ruleMode": "v2"}, headers=su)
    assert r.status_code == 422 and "confirm" in r.text
    r = client.put("/api/overhead/settings", json={"ruleMode": "v2", "confirm": True}, headers=su)
    assert r.status_code == 409 and "遷移" in r.text, "沒有遷移完成標記不准切"
    assert client.get("/api/overhead/settings", headers=ad).json()["ruleMode"] == "legacy"
    assert client.put("/api/overhead/settings", json={"ruleMode": "v2", "confirm": True}, headers=ad).status_code == 403
    _mode(client, su, "v2")
    assert client.get("/api/overhead/settings", headers=ad).json()["migrationDone"] is True
    assert client.put("/api/overhead/settings", json={"ruleMode": "legacy"}, headers=su).status_code == 200, "退回舊口徑（回滾）不需確認"
    assert any("口徑" in a["target_label"] for a in _audits("settings.overhead.update"))


def test_v2_recomputes_pretax_tax_and_total_from_items(client, who):
    su, ad = who
    _mode(client, su, "v2")
    forged = _q()
    forged["tot"].update(pretax=999999, total=1, tax=0, subtotal=5)
    t = _row(_post(client, ad, forged).json()["quote_no"])[0]["tot"]
    assert (t["subtotal"], t["pretax"], t["tax"], t["total"]) == (100000, 100000, 5000, 105000)
    assert t["adminCost"] == 9250, "利潤欄位用重算後的稅前"
    _mode(client, su, "legacy")


def test_rejected_pct_change_happens_before_any_write_or_notification(client, who):
    su, ad = who
    qno = _post(client, su, _q(overheadPct=30)).json()["quote_no"]
    cn = db.get_db()
    n0 = cn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
    cn.close()
    r = client.put("/api/quotations/%s" % qno, json={"status": "待審核", "data": _q(overheadPct=40)}, headers=ad)
    assert r.status_code == 403
    cn = db.get_db()
    assert cn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0] == n0, "被擋下的請求不可寄出簽核通知"
    assert cn.execute("SELECT status FROM quotations WHERE quote_no=?", (qno,)).fetchone()["status"] == "草稿"
    cn.close()


def test_unstamped_quote_is_not_a_false_403_after_the_default_changes(client, who):
    su, ad = who
    qno = _post(client, ad, _q()).json()["quote_no"]               # legacy：沒有比率欄位
    assert client.put("/api/overhead/settings", json={"defaultPct": 20}, headers=su).status_code == 200
    r = client.put("/api/quotations/%s" % qno, json={"status": "草稿", "data": _q(customerName="改名")}, headers=ad)
    assert r.status_code == 200, r.text
    client.put("/api/overhead/settings", json={"defaultPct": 25}, headers=su)


def test_overhead_pct_is_hidden_from_roles_without_money_visibility():
    from helpers import financial_mask
    assert "overheadPct" in financial_mask.QUOTE_MONEY_KEYS


def test_v2_without_the_migration_marker_is_treated_as_legacy(client, who):
    """失效安全：有人（含離線工具）把 overhead_rule_mode 直接寫成 v2 但沒有遷移完成標記 ⇒ 伺服器照 legacy 算。"""
    su, ad = who
    cn = db.get_db()
    cn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES ('overhead_rule_mode', '\"v2\"', '2031-01-01T00:00:00') "
               "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json")
    cn.commit()
    cn.close()
    assert client.get("/api/overhead/settings", headers=ad).json()["ruleMode"] == "legacy"
    t = _row(_post(client, ad, _q()).json()["quote_no"])[0]["tot"]
    assert t["adminCost"] == 10000 and "formulaVer" not in t
    _migrated()
    assert client.get("/api/overhead/settings", headers=ad).json()["ruleMode"] == "v2"
    cn = db.get_db()
    cn.execute("DELETE FROM system_settings WHERE key IN ('overhead_rule_mode', 'overhead_migration_done')")
    cn.commit()
    cn.close()


def test_v2_recomputes_item_amounts_from_qty_times_unit_price(client, who):
    su, ad = who
    _mode(client, su, "v2")
    forged = _q(items=[{"type": "header", "title": "標題", "amount": 777},
                       {"type": "item", "qty": 2, "unitPrice": 50000, "amount": 1, "cost": 60000}])
    d, _, _ = _row(_post(client, ad, forged).json()["quote_no"])
    assert d["items"][1]["amount"] == 100000 and d["items"][0]["amount"] == 0, "品項金額由伺服器重算（標題列 0）"
    assert (d["tot"]["subtotal"], d["tot"]["pretax"], d["tot"]["total"]) == (100000, 100000, 105000)
    _mode(client, su, "legacy")


def test_server_tax_rate_rule_keeps_the_old_semantics(client):
    """稽核 #5：不靜默改舊單語意——缺鍵＝5%；鍵存在但 null／空字串＝舊 calcTotals 的 0%（以資料庫存的 tot.tax 為準）；零稅率／免稅恆 0。"""
    from modules.case import profit_guard as PG
    base = {"items": [{"type": "item", "qty": 1, "unitPrice": 10000, "cost": 0}]}
    tax = lambda q, st=None: PG.server_totals(q, st)["tax"]      # noqa: E731
    assert tax(dict(base)) == 500, "新單（沒有 taxRate 鍵）＝5%"
    assert tax(dict(base, taxRate=5)) == 500 and tax(dict(base, taxRate=0)) == 0
    assert tax(dict(base, taxRate=None), {"tax": 0}) == 0 and tax(dict(base, taxRate=""), {"tax": 0}) == 0, "舊儲存形狀：存的稅額是 0 ⇒ 維持 0"
    assert tax(dict(base, taxRate=None), {"tax": 500}) == 500 and tax(dict(base, taxRate=None)) == 500, "存的稅額不是 0／沒有存值 ⇒ 5%"
    assert tax(dict(base, taxType="exempt", taxRate=0)) == 0 and tax(dict(base, taxType="zero")) == 0, "免稅／零稅率恆 0"
    assert tax(dict(base, taxType="taxable")) == 500


def test_switching_back_to_legacy_removes_the_migration_marker(client, who):
    """退回舊口徑後標記一併移除：再切 v2 必須重新 recalc（legacy 期間存檔的單是舊口徑，不能被當成已遷移）。"""
    su, ad = who
    _mode(client, su, "v2")
    assert client.get("/api/overhead/settings", headers=ad).json()["migrationDone"] is True
    assert client.put("/api/overhead/settings", json={"ruleMode": "legacy"}, headers=su).status_code == 200
    assert client.get("/api/overhead/settings", headers=ad).json()["migrationDone"] is False
    r = client.put("/api/overhead/settings", json={"ruleMode": "v2", "confirm": True}, headers=su)
    assert r.status_code == 409, "標記不見 ⇒ 不能直接再切回 v2"
    assert any(json.loads(a["detail"]).get("migrationMarker") == "removed" for a in _audits("settings.overhead.update"))


def test_v2_save_of_a_legacy_shaped_quote_keeps_zero_tax(client, who):
    """舊儲存形狀（taxRate:null、稅額 0）在 v2 第一次存檔時不會憑空多 5% 稅；新單（沒有 taxRate 鍵）才是 5%。"""
    su, ad = who
    legacy = _q(taxRate=None)
    legacy["tot"].update(tax=0, total=100000)
    qno = _post(client, ad, legacy).json()["quote_no"]               # legacy 模式建立：伺服器不改
    assert _row(qno)[0]["tot"]["tax"] == 0
    _mode(client, su, "v2")
    r = client.put("/api/quotations/%s" % qno, json={"status": "草稿", "data": dict(_q(taxRate=None, customerName="改名"), tot=dict(_q()["tot"], tax=0, total=100000))}, headers=ad)
    assert r.status_code == 200, r.text
    t = _row(qno)[0]["tot"]
    assert (t["pretax"], t["tax"], t["total"]) == (100000, 0, 100000), "存的稅額是 0 ⇒ 維持 0%"
    fresh = _q()
    fresh.pop("taxRate", None)
    t2 = _row(_post(client, ad, fresh).json()["quote_no"])[0]["tot"]
    assert t2["tax"] == 5000, "新單（沒有 taxRate 鍵）＝5%"
    _mode(client, su, "legacy")


def test_unsettled_ignores_legacy_indirect_values_settled_keeps_them(client, who):
    """五項間接成本拿掉（使用者 2026-10-09）：未精算單在新口徑一律不計舊值；已結案單保留存值（數字不變）；legacy 模式照舊計入。"""
    su, ad = who
    five = dict(indirectLogistics=1000, indirectInstallation=2000, indirectTravel=500, indirectWarranty=300, indirectOther=200)
    legacy = _q(**five)
    legacy["tot"].update(totalIndirect=10370 + 4000, netProfit=37000 - 14370, netMarginPct=22.6)
    qno = _post(client, ad, legacy).json()["quote_no"]                 # legacy 模式：不改前端送來的值，五項仍計入
    assert _row(qno)[0]["tot"]["totalIndirect"] == 14370
    cn = db.get_db()                                                    # 另一張：已結案，同樣有舊值
    settled = _post(client, ad, _q(**five)).json()["quote_no"]
    cn.execute("UPDATE quotations SET deal_tag='已結案' WHERE quote_no=?", (settled,))
    cn.commit()
    d0 = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (settled,)).fetchone()["data_json"])
    cn.close()
    _mode(client, su, "v2")
    r = client.put("/api/quotations/%s" % qno, json={"status": "草稿", "data": _q(customerName="改名", **five)}, headers=ad)
    assert r.status_code == 200, r.text
    t = _row(qno)[0]["tot"]
    assert (t["adminCost"], t["charityDonation"], t["totalIndirect"], t["netProfit"]) == (9250, 370, 9620, 27380), "未精算：五項舊值（共 4000）不計入"
    assert _row(qno)[0]["indirectLogistics"] == 1000, "舊值留在資料裡（歷史／回滾），只是不計"
    client.put("/api/quotations/%s" % settled, json={"status": "草稿", "data": _q(**five)}, headers=su)        # 已結案：存檔端點不重算
    assert _row(settled)[0]["tot"] == d0["tot"], "已結案單的 tot 逐位不變"
    _mode(client, su, "legacy")
