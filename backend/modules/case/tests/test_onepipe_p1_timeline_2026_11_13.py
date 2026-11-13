# -*- coding: utf-8 -*-
"""一條龍 P1'（旗標 onepipe.timeline）：案件物料流程時間軸 `GET /api/quotations/{no}/material-flow`。

- 旗標關 ⇒ 404（與端點不存在相同）；開 ⇒ 依今天算得出來的資料出七格。
- 雙帳號負向：非案件成員＝查無（同一個 404）；回應**沒有任何金額欄位／數字**（種了金額，掃整份回應）。
- 降級：M03 不在 ⇒ 入庫、出貨兩格不出現；供應端出錯 ⇒「庫存暫時讀不到」；出貨單無權限 ⇒ 該段不回傳。
"""
import json
import re

import pytest

from core import registry as _registry
from tests._requires import requires_module

pytestmark = requires_module("case", "本檔打 M01（案件）的物料流程端點")

NO = "MQ-P1T-001"
MONEY_WORDS = re.compile(r"price|cost|amount|total|money|pretax|tax|金額|單價|成本", re.I)


def _flag(monkeypatch, on):
    from helpers import onepipe_flags
    monkeypatch.setattr(onepipe_flags, "flag_on", lambda field, conn=None: bool(on) and field == "timeline")


def _uid(username):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()[0]
    finally:
        conn.close()


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _seed(assigned=(), devices=None, orders=None):
    import db
    cr = {"devices": devices if devices is not None else [], "materialOrders": orders or []}
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (NO, "已送出", "流程客戶", "流程工程", 424242, 400000, json.dumps({"dealTag": "已成案", "caseRecord": cr}, ensure_ascii=False), now, now, "已成案",
                      json.dumps([_uid(u) for u in assigned])))
        conn.commit()
    finally:
        conn.close()


def _rows(sql, args=()):
    import db
    conn = db.get_db()
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def _member(make_user, client, name="p1t_m"):
    u = make_user(username=name, role="admin")
    return _login(client, *u)


def _cells(body):
    return {c["key"]: c for c in body["cells"]}


def test_flag_off_is_404_like_a_missing_route(client, make_user, monkeypatch):
    _flag(monkeypatch, False)
    h = _member(make_user, client)
    _seed()
    assert client.get("/api/quotations/%s/material-flow" % NO, headers=h).status_code == 404


def test_flag_on_empty_case_shows_na_cells_and_next_step(client, make_user, monkeypatch):
    _flag(monkeypatch, True)
    h = _member(make_user, client)
    _seed()
    b = client.get("/api/quotations/%s/material-flow" % NO, headers=h).json()
    c = _cells(b)
    assert list(c) == ["call", "purchase", "arrive", "stock", "ship", "device", "warranty"]
    assert {x["state"] for x in b["cells"]} == {"na"}
    assert b["next"]["key"] == "call" and "sub=materials" in b["next"]["href"] and NO in b["next"]["href"]
    assert c["stock"]["summary"].endswith("第 2 階段後提供")


def test_flag_on_full_picture_and_per_document_arrival(client, make_user, monkeypatch):
    _flag(monkeypatch, True)
    h = _member(make_user, client)
    _seed(devices=[{"id": 1, "sn": "SN-1", "warrantyStart": "2099-01-01", "warrantyMonths": 12}, {"id": 2, "sn": ""}],
          orders=[{"itemId": "i1", "itemName": "交換器", "unitPrice": 98765, "totalPrice": 987650}])
    for item, code, st, rec in (("i1", "MO-1", "已核准", "2026-02-01"), ("i2", "MO-2", "已核准", ""), ("i3", "MO-3", "草稿", "")):
        _rows("INSERT INTO case_material_approvals (quote_no, item_id, doc_code, status, received_on) VALUES (?,?,?,?,?)", (NO, item, code, st, rec))
    _rows("INSERT INTO case_extra_expenses (quote_no, kind, doc_code, status, expense_date, total_cost, description, created_by) VALUES (?,?,?,?,?,?,?,?)", (NO, "purchase_req", "PR-1", "已核准", "2026-01-05", 777777, "請購", "x"))
    _rows("INSERT INTO case_extra_expenses (quote_no, kind, doc_code, status, expense_date, total_cost, description, created_by) VALUES (?,?,?,?,?,?,?,?)", (NO, "purchase_order", "PO-1", "待審核", "2026-01-06", 888888, "採購", "x"))
    _rows("INSERT INTO case_extra_expenses (quote_no, kind, doc_code, status, expense_date, total_cost, description, created_by) VALUES (?,?,?,?,?,?,?,?)", (NO, "purchase_order", "PO-X", "已作廢", "2026-01-06", 999999, "作廢", "x"))
    _rows("INSERT INTO stock_items (part_no, serial_no, status, quote_no, created_at, updated_at, cost) VALUES (?,?,?,?,?,?,?)", ("NET-1", "SN-1", "installed", NO, "2026-01-01T00:00:00", "2026-01-01T00:00:00", 55555))
    _rows("INSERT INTO stock_items (part_no, serial_no, status, quote_no, created_at, updated_at) VALUES (?,?,?,?,?,?)", ("NET-1", "SN-2", "shipped", NO, "2026-01-01T00:00:00", "2026-01-01T00:00:00"))
    _rows("INSERT INTO stock_items (part_no, serial_no, status, quote_no, created_at, updated_at) VALUES (?,?,?,?,?,?)", ("NET-1", "SN-OTHER", "shipped", "MQ-OTHER", "2026-01-01T00:00:00", "2026-01-01T00:00:00"))
    _rows("INSERT INTO shipping_notes (note_no, quote_no, status, customer_name, items_json, data_json, is_signed, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
          ("SH-1", NO, "已核准", "流程客戶", "[]", "{}", 0, "2026-01-01T00:00:00", "2026-01-01T00:00:00"))
    r = client.get("/api/quotations/%s/material-flow" % NO, headers=h)
    assert r.status_code == 200, r.text
    b = r.json()
    c = _cells(b)
    assert c["call"]["state"] == "inprogress" and "3 張材料申請單，2 張已核准" in c["call"]["summary"]
    assert [(i["docCode"], i["arrived"]) for i in c["arrive"]["items"]] == [("MO-1", True), ("MO-2", False)]      # 逐張：到了／沒到
    assert c["arrive"]["state"] == "inprogress"
    assert [i["docCode"] for i in c["purchase"]["items"]] == ["PR-1", "PO-1"]                                      # 作廢的不列
    assert c["stock"]["summary"].startswith("已安裝 1 台、已出貨 1 台")                                             # 他案的序號不算
    assert c["ship"]["state"] == "done" and c["device"]["summary"].startswith("已登載 2 台")
    assert c["warranty"]["earliestEnd"] == "2100-01-01"
    assert b["next"]["key"] == "call"
    # 沒有任何金額：鍵名與數字都不得出現（種的金額 98765／987650／777777／888888／999999／55555／424242／400000）
    raw = json.dumps(b, ensure_ascii=False)
    for n in ("98765", "987650", "777777", "888888", "999999", "55555", "424242", "400000"):
        assert n not in raw, n

    def keys(o):
        if isinstance(o, dict):
            for k, v in o.items():
                yield k
                yield from keys(v)
        elif isinstance(o, list):
            for v in o:
                yield from keys(v)
    assert not [k for k in keys(b) if MONEY_WORDS.search(k)]


def test_non_member_gets_the_same_404_as_a_missing_case(client, make_user, monkeypatch):
    _flag(monkeypatch, True)
    out = make_user(username="p1t_out", role="engineer", modules=["case_manage"])
    inn = make_user(username="p1t_in", role="engineer", modules=["case_manage"])
    _seed(assigned=["p1t_in"])
    assert client.get("/api/quotations/%s/material-flow" % NO, headers=_login(client, *out)).status_code == 404
    assert client.get("/api/quotations/NO-SUCH-CASE/material-flow", headers=_login(client, *out)).status_code == 404
    assert client.get("/api/quotations/%s/material-flow" % NO, headers=_login(client, *inn)).status_code == 200
    assert client.get("/api/quotations/%s/material-flow" % NO).status_code in (401, 403)


def test_supply_absent_hides_stock_and_ship_cells(client, make_user, monkeypatch):
    _flag(monkeypatch, True)
    h = _member(make_user, client)
    _seed()
    real = _registry.single_provider
    monkeypatch.setattr(_registry, "single_provider", lambda cap: None if cap in ("stock.case_summary", "shipping.list_for_case") else real(cap))
    b = client.get("/api/quotations/%s/material-flow" % NO, headers=h).json()
    assert [c["key"] for c in b["cells"]] == ["call", "purchase", "arrive", "device", "warranty"]
    assert b["stockPresent"] is False and b["shipPresent"] is False


def test_provider_error_says_stock_temporarily_unreadable_not_hidden(client, make_user, monkeypatch):
    _flag(monkeypatch, True)
    h = _member(make_user, client)
    _seed()
    real = _registry.single_provider

    def boom(*a, **k):
        raise RuntimeError("供應端壞了")
    monkeypatch.setattr(_registry, "single_provider", lambda cap: boom if cap == "stock.case_summary" else real(cap))
    b = client.get("/api/quotations/%s/material-flow" % NO, headers=h).json()
    c = _cells(b)
    assert c["stock"]["summary"] == "庫存暫時讀不到" and c["stock"].get("unavailable") is True
    assert b["stockPresent"] is True and "call" in c and "device" in c                 # 其餘格照常


def test_ship_without_permission_drops_the_whole_segment(client, make_user, monkeypatch):
    _flag(monkeypatch, True)
    h = _member(make_user, client)
    _seed()
    from fastapi import HTTPException
    real = _registry.single_provider

    def deny(*a, **k):
        raise HTTPException(403, "no")
    monkeypatch.setattr(_registry, "single_provider", lambda cap: deny if cap == "shipping.list_for_case" else real(cap))
    b = client.get("/api/quotations/%s/material-flow" % NO, headers=h).json()
    assert "ship" not in _cells(b) and b["shipPresent"] is False and "stock" in _cells(b)


def test_provider_stock_case_summary_counts_by_case_and_has_no_money(client):
    import db
    from modules.supply.case_summary import case_summary
    _rows("INSERT INTO stock_items (part_no, serial_no, status, quote_no, cost, created_at, updated_at) VALUES (?,?,?,?,?,?,?)", ("P-A", "S-A1", "installed", "MQ-CS", 123456, "x", "x"))
    _rows("INSERT INTO stock_items (part_no, serial_no, status, quote_no, created_at, updated_at) VALUES (?,?,?,?,?,?)", ("P-A", "S-A2", "shipped", "MQ-CS", "x", "x"))
    _rows("INSERT INTO stock_items (part_no, serial_no, status, quote_no, created_at, updated_at) VALUES (?,?,?,?,?,?)", ("P-B", "S-B1", "void", "MQ-CS", "x", "x"))
    conn = db.get_db()
    try:
        s = case_summary(conn, "MQ-CS", {"username": "u", "role": "superadmin"})
        assert (s["installed"], s["shipped"], s["void"]) == (1, 1, 1) and s["parts"] == [{"partNo": "P-A", "installed": 1, "shipped": 1}]
        assert "123456" not in json.dumps(s)
        assert case_summary(conn, "", None) == {"installed": 0, "shipped": 0, "void": 0, "parts": []}
    finally:
        conn.close()


def test_stock_cell_without_stock_view_permission_says_no_access_and_shows_no_numbers(client, make_user, monkeypatch):
    """入庫格要有「檢視庫存」同一組權限；沒有 ⇒ 只顯示「無權限檢視」，沒有任何台數／料號。"""
    _flag(monkeypatch, True)
    h = _member(make_user, client)
    _seed()
    _rows("INSERT INTO stock_items (part_no, serial_no, status, quote_no, created_at, updated_at) VALUES (?,?,?,?,?,?)", ("P-SECRET", "S-NP1", "installed", NO, "x", "x"))
    from fastapi import HTTPException
    real = _registry.single_provider

    def deny(*a, **k):
        raise HTTPException(403, "no")
    monkeypatch.setattr(_registry, "single_provider", lambda cap: deny if cap == "stock.case_summary" else real(cap))
    b = client.get("/api/quotations/%s/material-flow" % NO, headers=h).json()
    c = _cells(b)["stock"]
    assert c["summary"] == "無權限檢視" and c["state"] == "na" and not c.get("items")
    assert "P-SECRET" not in json.dumps(b) and b["stockPresent"] is True


def test_provider_checks_the_same_module_keys_as_inventory_view():
    import db
    from fastapi import HTTPException
    from modules.supply.case_summary import case_summary
    conn = db.get_db()
    try:
        for mods in ("[]", '["hr"]'):
            try:
                case_summary(conn, "MQ-CS", {"role": "engineer", "modules": mods})
                raise AssertionError("沒有庫存相關模組的人不該讀得到")
            except HTTPException as e:
                assert e.status_code == 403
        for key in ("inventory", "procurement", "case_manage", "netplan_edit"):
            assert case_summary(conn, "MQ-CS", {"role": "engineer", "modules": json.dumps([key])})["parts"] is not None
        assert case_summary(conn, "MQ-CS", None)["installed"] >= 0                       # 內部呼叫（沒給 caller）不檢查
    finally:
        conn.close()
