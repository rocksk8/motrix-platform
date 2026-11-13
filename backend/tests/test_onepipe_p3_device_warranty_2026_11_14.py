# -*- coding: utf-8 -*-
"""T85 一條龍 P3「出貨／設備／保固對齊」（旗標 onepipe.ship_device_warranty；決策 D4＝A）。

關＝與今天逐位元相同（兩個新端點 404、庫存序號歷史 404、提供者回空、保固通知去重鍵維持舊格式、LINE 鑰匙不含到期日）；
開＝出貨序號預填設備（只預填、不寫）、保固起始日 D4 的退路順序與完工日優先設定、序號歷史（其他案件遮罩）、保固通知去重含到期日（舊鍵相容）。
"""
import json
from datetime import date, timedelta

import pytest

from tests._requires import requires_module
pytestmark = requires_module("supply", "本檔測出貨序號與案件設備的對齊")
needs_m01 = requires_module("case", "本檔測 M01 設備頁預填")

from tests.test_api_integration import _auth, _login

NO = "MQ-P3-001"
OTHER = "MQ-P3-OTHER"


def _flags(monkeypatch, **on):
    from helpers import onepipe_flags
    monkeypatch.setattr(onepipe_flags, "flag_on", lambda field, conn=None: bool(on.get(field)))


def _x(sql, args=()):
    import db
    conn = db.get_db()
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def _q(sql, args=()):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def _admin(client, make_user, name="p3_admin"):
    return _auth(_login(client, *make_user(username=name, role="admin")))


def _case(devices=(), assigned=(), no=NO):
    data = {"dealTag": "已成案", "caseRecord": {"devices": list(devices)}}
    _x("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, sales_person, assigned_user_ids)"
       " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
       (no, "已送出", "客", "專案", 1000, 952, json.dumps(data), "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "", json.dumps(list(assigned))))


def _shipped(serial, ship_date, quote=NO, part="NET-P3", note=None, status="shipped"):
    note = note or "SN-" + serial                       # 每個序號各一張出貨單（INSERT OR IGNORE 共用單號會讓後面的序號沿用第一張的出貨日）
    _x("INSERT OR IGNORE INTO parts (part_no, name, active, cost, created_at, updated_at) VALUES (?,?,1,0,?,?)", (part, "測試交換器", "2026-01-01T00:00:00", "2026-01-01T00:00:00"))
    _x("INSERT OR IGNORE INTO shipping_notes (note_no, quote_no, status, ship_date, created_at, updated_at) VALUES (?,?,?,?,?,?)",
       (note, quote, "已核准", ship_date, "2026-01-01T00:00:00", "2026-01-01T00:00:00"))
    _x("INSERT INTO stock_items (part_no, serial_no, status, quote_no, shipping_note_no, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
       (part, serial, status, quote, note, "2026-01-01T00:00:00", "2026-01-01T00:00:00"))


def _event(serial, event, quote="", frm="", to="", ref="", reason="", part="NET-P3"):
    from modules.supply import stock_events
    import db
    conn = db.get_db()
    try:
        stock_events.record(conn, event=event, part_no=part, serial_no=serial, stock_item_id=0, from_status=frm, to_status=to, quote_no=quote, ref=ref, reason=reason, actor="tester")
        conn.commit()
    finally:
        conn.close()


ON = dict(ship_device_warranty=True, receive_ledger=True)
PRE = "/api/quotations/%s/device-prefill" % NO
HIS = "/api/quotations/%s/device-history" % NO


# ── 旗標關＝今天 ──────────────────────────────────────────────────────────

@needs_m01
def test_flag_off_endpoints_404_and_providers_empty(client, make_user, monkeypatch):
    _flags(monkeypatch, receive_ledger=True)
    admin = _admin(client, make_user)
    _case()
    _shipped("S-OFF-1", "2026-11-01")
    assert client.get(PRE, headers=admin).status_code == 404
    assert client.get(HIS, params={"sn": "S-OFF-1"}, headers=admin).status_code == 404
    assert client.get("/api/inventory/serial-history", params={"part_no": "NET-P3", "serial_no": "S-OFF-1"}, headers=admin).status_code == 404
    from modules.supply import serial_view as SV
    import db
    conn = db.get_db()
    try:
        assert SV.shipped_serials(conn, NO) == {"serials": [], "firstShipDate": ""} and SV.serial_history(conn, "NET-P3", "S-OFF-1") == []
    finally:
        conn.close()


def test_flag_off_guard_key_and_line_key_are_the_old_ones(monkeypatch):
    from modules.case import case_deadlines as CD
    from helpers import email_notify as EN
    _flags(monkeypatch)
    monkeypatch.setattr(CD, "_get_setting", lambda k: None)
    done, key = CD._warranty_guard("Q1", "SN1", 7, date(2027, 1, 31), with_expiry=False)
    assert (done, key) == (False, "warranty_notif.Q1_SN1_7")
    assert EN._warranty_line_key("Q1", "SN1", 5, "2027-01-31") == EN._warranty_line_key("Q1", "SN1", 5)          # 旗標關：鑰匙不含到期日


# ── 預填 ──────────────────────────────────────────────────────────────────

@needs_m01
def test_prefill_lists_shipped_unregistered_serials_with_ship_date_default(client, make_user, monkeypatch):
    _flags(monkeypatch, **ON)
    admin = _admin(client, make_user)
    _case(devices=[{"id": 1, "sn": "S-REG", "name": "已登載", "warrantyStart": "", "warrantyMonths": 12}])
    _shipped("S-1", "2026-11-03")
    _shipped("S-2", "2026-11-05")
    _shipped("S-REG", "2026-11-05")                                 # 已在設備清單 ⇒ 不再預填
    _shipped("S-INST", "2026-11-05", status="installed")           # 已安裝 ⇒ 不列
    _shipped("S-OTHER", "2026-11-05", quote=OTHER, note="SN-P3-2")     # 別的案件 ⇒ 不列
    r = client.get(PRE, headers=admin)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["available"] is True and b["basis"] == 0 and b["missingStart"] == 1
    assert [(s["serialNo"], s["suggestedStart"], s["startSource"]) for s in b["serials"]] == [("S-1", "2026-11-03", "出貨日"), ("S-2", "2026-11-05", "出貨日")]
    assert all("cost" not in s and "price" not in s for s in b["serials"])                       # 沒有金額欄位
    data = json.loads(_q("SELECT data_json FROM quotations WHERE quote_no=?", (NO,))[0]["data_json"])
    assert [d["sn"] for d in data["caseRecord"]["devices"]] == ["S-REG"]                          # 只預填、什麼都沒寫


def test_pick_start_order_follows_basis():
    from modules.case.device_warranty import pick_start
    assert pick_start(0, "2026-11-03", "2026-11-01", "2026-11-20") == ("2026-11-03", "ship")
    assert pick_start(0, "", "2026-11-01", "2026-11-20") == ("2026-11-01", "arrival")        # 沒有出貨單（直送）⇒ 到貨日
    assert pick_start(0, "", "", "2026-11-20") == ("2026-11-20", "completion")                # 再退到完工日
    assert pick_start(1, "2026-11-03", "2026-11-01", "2026-11-20") == ("2026-11-20", "completion")   # 完工日優先
    assert pick_start(1, "2026-11-03", "2026-11-01", "") == ("2026-11-03", "ship")
    assert pick_start(0, "", "", "") == ("", "")


@needs_m01
def test_prefill_falls_back_to_arrival_then_completion_and_basis_setting(client, make_user, monkeypatch):
    _flags(monkeypatch, **ON)
    from modules.case import device_warranty as DW
    admin = _admin(client, make_user)
    _case()
    _shipped("S-FB", "")                                            # 出貨單沒有出貨日
    _x("INSERT INTO case_material_approvals (quote_no, item_id, doc_code, status, received_on) VALUES (?,?,?,?,?)", (NO, "m1", "MR-1", "已核准", "2026-11-08"))
    s = client.get(PRE, headers=admin).json()["serials"][0]
    assert (s["suggestedStart"], s["startSource"]) == ("2026-11-08", "到貨日")
    _x("INSERT INTO completion_notes (note_no, quote_no, status, completion_date, created_at, updated_at) VALUES (?,?,?,?,?,?)", ("CN-P3-1", NO, "已完成", "2026-11-20", "2026-11-20T00:00:00", "2026-11-20T00:00:00"))
    assert client.get(PRE, headers=admin).json()["serials"][0]["suggestedStart"] == "2026-11-08"
    monkeypatch.setattr(DW, "start_basis", lambda conn=None: 1)
    s2 = client.get(PRE, headers=admin).json()["serials"][0]
    assert (s2["suggestedStart"], s2["startSource"]) == ("2026-11-20", "完工日")


@needs_m01
def test_prefill_requires_case_membership_and_stock_module_absent_degrades(client, make_user, monkeypatch):
    _flags(monkeypatch, **ON)
    _case(assigned=[])
    other = _auth(_login(client, *make_user(username="p3_other", role="sales")))
    assert client.get(PRE, headers=other).status_code in (403, 404)
    from core import registry
    real = registry.single_provider
    monkeypatch.setattr(registry, "single_provider", lambda cap: None if cap == "stock.shipped_serials" else real(cap))
    admin = _admin(client, make_user)
    b = client.get(PRE, headers=admin).json()
    assert b["available"] is False and b["serials"] == []


# ── 序號歷史 ──────────────────────────────────────────────────────────────

@needs_m01
def test_history_masks_other_cases_and_only_covers_this_cases_serials(client, make_user, monkeypatch):
    _flags(monkeypatch, **ON)
    admin = _admin(client, make_user)
    _case(devices=[{"id": 1, "sn": "S-H1", "name": "設備", "warrantyStart": "2026-11-01", "warrantyMonths": 12}])
    _event("S-H1", "receive", quote=OTHER, to="in_stock", ref="PO-9", reason="前一個案件的入庫備註")
    _event("S-H1", "ship", quote=OTHER, frm="in_stock", to="shipped", ref="SN-OTHER-1", reason="退回原因")
    _event("S-H1", "install", quote=NO, frm="shipped", to="installed", ref="")
    b = client.get(HIS, params={"sn": "S-H1"}, headers=admin).json()
    assert [e["event"] for e in b["events"]] == ["receive", "ship", "install"]
    assert [e["quoteNo"] for e in b["events"]] == ["其他案件", "其他案件", NO]
    assert all(e["ref"] == "" and e["reason"] == "" for e in b["events"][:2])                     # 其他案件的單號與原因一併遮掉
    assert b["since"] == b["events"][0]["at"]
    _event("S-NOTMINE", "receive", quote=OTHER, to="in_stock")
    assert client.get(HIS, params={"sn": "S-NOTMINE"}, headers=admin).json()["events"] == []      # 不是本案的序號 ⇒ 不當成全庫查詢入口


@needs_m01
def test_history_masks_events_without_quote_and_ignores_typed_serials(client, make_user, monkeypatch):
    """h11／h9：沒有案件編號的異動（撤銷出貨備註、入庫批號）是自由文字，案件成員不得看到；設備清單自己打的序號不當成與本案有庫存關係。"""
    _flags(monkeypatch, **ON)
    admin = _admin(client, make_user)
    _case(devices=[{"id": 1, "sn": "S-H2", "name": "設備", "warrantyStart": "2026-11-01", "warrantyMonths": 12},
                   {"id": 2, "sn": "S-TYPED", "name": "手打", "warrantyStart": "2026-11-01", "warrantyMonths": 12}])
    _shipped("S-H2", "2026-11-05")
    _event("S-H2", "receive", quote="", to="in_stock", ref="PO-SECRET", reason="入庫備註")
    _event("S-H2", "revoke_ship", quote="", frm="shipped", to="in_stock", ref="SN-OTHER-9", reason="別案撤銷備註")
    _event("S-H2", "ship", quote=NO, frm="in_stock", to="shipped", ref="SN-S-H2")
    b = client.get(HIS, params={"sn": "S-H2"}, headers=admin).json()
    assert [e["event"] for e in b["events"]] == ["receive", "revoke_ship", "ship"]
    assert all(e["ref"] == "" and e["reason"] == "" and e["actor"] == "" for e in b["events"][:2])
    assert b["events"][0]["quoteNo"] == "" and b["events"][2]["quoteNo"] == NO and b["events"][2]["ref"] == "SN-S-H2"
    blob = json.dumps(b, ensure_ascii=False)
    assert "PO-SECRET" not in blob and "別案撤銷備註" not in blob and "SN-OTHER-9" not in blob
    _event("S-TYPED", "receive", quote=OTHER, to="in_stock", ref="PO-X", reason="別案")           # 只在案件設備清單打了序號、庫存與本案無關
    assert client.get(HIS, params={"sn": "S-TYPED"}, headers=admin).json()["events"] == []


@needs_m01
def test_inventory_serial_history_needs_inventory_module_and_returns_events(client, make_user, monkeypatch):
    _flags(monkeypatch, **ON)
    admin = _admin(client, make_user)
    _event("S-INV-1", "receive", quote=OTHER, to="in_stock")
    r = client.get("/api/inventory/serial-history", params={"part_no": "NET-P3", "serial_no": "S-INV-1"}, headers=admin)
    assert r.status_code in (200, 403)
    if r.status_code == 200:
        b = r.json()
        assert [e["event"] for e in b["events"]] == ["receive"] and b["since"] == b["events"][0]["at"]


# ── 保固通知去重含到期日 ──────────────────────────────────────────────────

def _store(monkeypatch):
    from modules.case import case_deadlines as CD
    kv = {}
    monkeypatch.setattr(CD, "_get_setting", lambda k: kv.get(k))
    monkeypatch.setattr(CD, "_set_setting", lambda k, v: kv.__setitem__(k, v))
    return CD, kv


def test_guard_key_includes_expiry_and_new_expiry_can_notify_again(monkeypatch):
    CD, kv = _store(monkeypatch)
    e1, e2 = date(2027, 1, 31), date(2027, 6, 30)
    done, key = CD._warranty_guard("Q1", "SN1", 30, e1, True)
    assert not done and key == "warranty_notif.Q1_SN1_30_2027-01-31"
    kv[key] = "2027-01-05"
    assert CD._warranty_guard("Q1", "SN1", 30, e1, True)[0] is True                 # 同到期日 ⇒ 已通知
    assert CD._warranty_guard("Q1", "SN1", 30, e2, True) == (False, "warranty_notif.Q1_SN1_30_2027-06-30")   # 到期日換了 ⇒ 可再通知


def test_guard_old_key_compat_suppresses_only_for_the_same_expiry(monkeypatch):
    CD, kv = _store(monkeypatch)
    e = date(2027, 1, 31)
    kv["warranty_notif.Q1_SN1_30"] = (e - timedelta(days=12)).isoformat()                # 對這個到期日寄的（在提醒期間內）
    assert CD._warranty_guard("Q1", "SN1", 30, e, True)[0] is True                   # 舊鍵相容：不重寄
    kv["warranty_notif.Q1_SN2_30"] = (e - timedelta(days=200)).isoformat()               # 對更早的到期日寄的
    assert CD._warranty_guard("Q1", "SN2", 30, e, True)[0] is False
    kv["warranty_notif.Q1_SN3_30"] = "壞值"
    assert CD._warranty_guard("Q1", "SN3", 30, e, True)[0] is True                    # 壞值保守視為已通知
    assert CD._warranty_guard("Q1", "SN1", 30, e, False) == (True, "warranty_notif.Q1_SN1_30")   # 旗標關＝只看舊鍵


def test_guard_old_urgent_key_is_compared_with_the_urgent_threshold_not_the_early_one(monkeypatch):
    """h11：舊的緊急鍵（到期前 7 天寄的）＋保固延長 ≤23 天，不能被當成「新到期日的緊急通知已寄」。"""
    CD, kv = _store(monkeypatch)
    e0 = date(2027, 1, 31)
    kv["warranty_notif.Q1_SN1_7"] = (e0 - timedelta(days=7)).isoformat()                 # 對舊到期日寄的緊急通知
    assert CD._warranty_guard("Q1", "SN1", 7, e0, True)[0] is True                       # 到期日沒變 ⇒ 已通知
    for ext in (1, 10, 23):                                                                # 延長不到一個提醒期：新到期日的緊急通知還沒寄
        assert CD._warranty_guard("Q1", "SN1", 7, e0 + timedelta(days=ext), True)[0] is False, ext


def test_line_key_carries_expiry_only_when_flag_on(monkeypatch):
    from helpers import email_notify as EN
    _flags(monkeypatch)
    off = EN._warranty_line_key("Q1", "SN1", 5, "2027-01-31")
    _flags(monkeypatch, ship_device_warranty=True)
    on = EN._warranty_line_key("Q1", "SN1", 5, "2027-01-31")
    assert on == off + "|2027-01-31" and EN._warranty_line_key("Q1", "SN1", 5) == off
